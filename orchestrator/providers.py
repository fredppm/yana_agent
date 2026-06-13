"""
providers.py — multi-model LLM routing.

Reads providers.yaml, selects the right model for each task type,
and calls the appropriate API (Anthropic direct | Bedrock | OpenAI).

Routing resolution order:
  1. routing.<task> may be "provider:tier" (e.g. "bedrock:fast") — explicit provider
  2. Otherwise tier name is looked up across providers in yaml order (first match wins)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import errors
import yaml

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _config_path() -> Path:
    return Path(__file__).parent / "config" / "providers.yaml"


def load_providers() -> dict:
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(errors.e("CFG-001", path=path))
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_model(task: str = "conversation", config: dict | None = None) -> tuple[str, str]:
    """
    Return (provider_name, model_id) for the given task type.

    Supports explicit routing like "bedrock:fast" in providers.yaml routing section.
    """
    if config is None:
        config = load_providers()

    llm = config.get("llm", {})
    routing = llm.get("routing", {})
    tier_spec = routing.get(task, routing.get("conversation", "default"))
    providers_cfg = llm.get("providers", {})

    # Explicit "provider:tier" routing
    if ":" in str(tier_spec):
        provider_name, tier = tier_spec.split(":", 1)
        provider_cfg = providers_cfg.get(provider_name, {})
        model_id = provider_cfg.get("models", {}).get(tier)
        if model_id:
            return provider_name, model_id

    tier = tier_spec

    # Scan providers in yaml order — first provider that defines this tier wins
    for provider_name, provider_cfg in providers_cfg.items():
        model_id = provider_cfg.get("models", {}).get(tier)
        if model_id:
            return provider_name, model_id

    # Fallback: first provider's default model
    for provider_name, provider_cfg in providers_cfg.items():
        model_id = provider_cfg.get("models", {}).get("default")
        if model_id:
            return provider_name, model_id

    raise ValueError(errors.e("LLM-001", task=task, tier=tier_spec))


def get_api_key(provider: str, config: dict | None = None) -> str | None:
    """Return API key for provider, or None if provider uses ambient credentials (Bedrock)."""
    if provider == "bedrock":
        return None  # uses AWS env vars / profile

    if config is None:
        config = load_providers()

    llm = config.get("llm", {})
    providers_cfg = llm.get("providers", {})
    provider_cfg = providers_cfg.get(provider, {})
    env_var = provider_cfg.get("api_key_env", f"{provider.upper()}_API_KEY")

    key = os.environ.get(env_var, "")
    if not key:
        raise OSError(errors.e("LLM-002", env_var=env_var))
    return key


# ---------------------------------------------------------------------------
# Connector tool definitions (CAP-6 — fixed surface, at most 2 tools)
# ---------------------------------------------------------------------------

CONNECTOR_TOOLS: list[dict] = [
    {
        "name": "call_connector",
        "description": (
            "Invoke a registered connector operation to read data or execute an action. "
            "Use the connector manifest in the system prompt to find the right instance_id and operation. "
            "If the response contains {\"error\": \"validation_error\", \"detail\": \"available: ...\"}, "
            "the operation name was wrong — use the listed names directly without calling get_connector_contract."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Connector instance ID from the manifest (e.g. 'calendar_fred', 'garmin_fred')",
                },
                "operation": {
                    "type": "string",
                    "description": "Operation name on the connector (e.g. 'events_today', 'steps_today')",
                },
                "params": {
                    "type": "object",
                    "description": "Optional parameters for the operation",
                },
            },
            "required": ["instance_id", "operation"],
        },
    },
    {
        "name": "get_connector_contract",
        "description": (
            "Load the full operation schema for a connector instance — use this when you need "
            "to know exact operation names or parameter details before calling call_connector."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Connector instance ID from the manifest",
                },
            },
            "required": ["instance_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# LLM call — dispatcher
# ---------------------------------------------------------------------------


def _auto_task(messages: list[dict], task: str) -> str:
    """
    Auto-downgrade 'conversation' to 'conversation_fast' for short/simple exchanges.
    Saves cost and latency — Haiku handles small talk, Sonnet handles depth.
    """
    if task != "conversation":
        return task
    last = messages[-1].get("content", "") if messages else ""
    # Short message + short history = fast tier
    if len(last) < 120 and len(messages) <= 6:
        return "conversation_fast"
    return task


def call_llm(
    messages: list[dict],
    system_prompt: str,
    task: str = "conversation",
    stream: bool = True,
    config: dict | None = None,
    timeout: float = 60.0,
    on_token: Callable[[str], None] | None = None,
) -> str:
    """
    Route to the correct provider and return the assistant's reply as a string.

    messages:  list of {role, content} — the conversation history
    system:    YANA's assembled identity context
    task:      routing key (conversation | conversation_fast | pulse_scheduled | first_breath)
    stream:    stream tokens while accumulating
    on_token:  callback(char) for each streamed token — output layer hooks in here.
               Normalised to a no-op internally so internals never guard against None.
    """
    if config is None:
        config = load_providers()

    # Normalise once — internals receive a guaranteed callable
    _on_token: Callable[[str], None] = on_token if on_token is not None else lambda _: None

    task = _auto_task(messages, task)
    provider, model_id = resolve_model(task, config)

    if provider == "anthropic":
        api_key = get_api_key("anthropic", config)
        assert api_key is not None  # get_api_key raises OSError if key is missing
        return _call_anthropic(
            messages, system_prompt, model_id, api_key, stream, timeout, _on_token
        )
    elif provider == "bedrock":
        region, profile = _bedrock_config(config)
        return _call_bedrock(
            messages, system_prompt, model_id, region, profile, stream, timeout, _on_token
        )
    elif provider == "openai":
        api_key = get_api_key("openai", config)
        assert api_key is not None  # get_api_key raises OSError if key is missing
        return _call_openai(messages, system_prompt, model_id, api_key, stream, timeout, _on_token)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _bedrock_config(config: dict) -> tuple[str, str | None]:
    """Return (region, profile) for Bedrock."""
    llm = config.get("llm", {})
    bedrock_cfg = llm.get("providers", {}).get("bedrock", {})
    region = os.environ.get("AWS_DEFAULT_REGION", bedrock_cfg.get("region", "us-east-1"))
    profile = os.environ.get("AWS_PROFILE", bedrock_cfg.get("profile"))
    return region, profile


# ---------------------------------------------------------------------------
# Anthropic (direct API)
# ---------------------------------------------------------------------------


def _call_anthropic(
    messages: list[dict],
    system_prompt: str,
    model_id: str,
    api_key: str,
    stream: bool,
    timeout: float,
    on_token: Callable[[str], None],
) -> str:
    import anthropic
    import httpx

    client = anthropic.Anthropic(api_key=api_key, timeout=httpx.Timeout(timeout, connect=10.0))

    if stream:
        full_text = ""
        with client.messages.stream(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
        ) as s:
            for text in s.text_stream:
                on_token(text)
                full_text += text
        return full_text
    else:
        response = client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
        )
        block = response.content[0]
        return block.text if hasattr(block, "text") else ""


# ---------------------------------------------------------------------------
# Bedrock (AnthropicBedrock — same SDK, different client)
# ---------------------------------------------------------------------------


def _call_bedrock(
    messages: list[dict],
    system_prompt: str,
    model_id: str,
    region: str,
    profile: str | None,
    stream: bool,
    timeout: float,
    on_token: Callable[[str], None],
) -> str:
    import anthropic
    import httpx

    client = anthropic.AnthropicBedrock(
        aws_region=region,
        aws_profile=profile,  # None = use default credential chain
        timeout=httpx.Timeout(timeout, connect=10.0),
    )

    if stream:
        full_text = ""
        with client.messages.stream(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
        ) as s:
            for text in s.text_stream:
                on_token(text)
                full_text += text
        return full_text
    else:
        response = client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
        )
        block = response.content[0]
        return block.text if hasattr(block, "text") else ""


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


def _call_openai(
    messages: list[dict],
    system_prompt: str,
    model_id: str,
    api_key: str,
    stream: bool,
    timeout: float,
    on_token: Callable[[str], None],
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=timeout)
    full_messages = [{"role": "system", "content": system_prompt}, *messages]

    if stream:
        full_text = ""
        response = client.chat.completions.create(
            model=model_id,
            messages=full_messages,  # type: ignore[arg-type]
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta  # type: ignore[union-attr]
            if delta.content:
                on_token(delta.content)
                full_text += delta.content
        return full_text
    else:
        response = client.chat.completions.create(
            model=model_id,
            messages=full_messages,  # type: ignore[arg-type]
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Tool-aware LLM call (Anthropic only; other providers fall back to plain call)
# ---------------------------------------------------------------------------


def call_llm_with_tools(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    task: str = "conversation",
    config: dict | None = None,
    timeout: float = 60.0,
) -> tuple[str, list[dict], list]:
    """
    Single LLM call with tool support.

    Returns (text, tool_use_blocks, raw_content_blocks):
      - text: concatenated text from response (may be empty if only tool_use)
      - tool_use_blocks: list of {id, name, input} dicts; empty if no tool calls
      - raw_content_blocks: full content list for the assistant message in history

    Non-Anthropic providers fall back to plain call_llm (no tool support).
    """
    if config is None:
        config = load_providers()

    provider, model_id = resolve_model(task, config)

    import anthropic
    import httpx

    if provider == "anthropic":
        api_key = get_api_key("anthropic", config)
        client = anthropic.Anthropic(api_key=api_key, timeout=httpx.Timeout(timeout, connect=10.0))
    elif provider == "bedrock":
        region, profile = _bedrock_config(config)
        client = anthropic.AnthropicBedrock(  # type: ignore[assignment]
            aws_region=region,
            aws_profile=profile,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
    else:
        # Provider doesn't support tools — fall back to plain call (no tool use)
        text = call_llm(
            messages, system_prompt, task=task, stream=False, config=config, timeout=timeout
        )
        return text, [], [{"type": "text", "text": text}]

    response = client.messages.create(
        model=model_id,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
    )

    text_parts: list[str] = []
    tool_uses: list[dict] = []
    raw_content: list = []

    for block in response.content:
        raw_content.append(block)
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_uses.append({"id": block.id, "name": block.name, "input": block.input})

    return "".join(text_parts), tool_uses, raw_content
