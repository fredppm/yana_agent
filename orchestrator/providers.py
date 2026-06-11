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
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    return Path(__file__).parent / "config" / "providers.yaml"


def load_providers() -> dict:
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(f"providers.yaml not found at {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_model(task: str = "conversation", config: Optional[dict] = None) -> tuple[str, str]:
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

    return "anthropic", llm.get("default", "claude-sonnet-4-6")


def get_api_key(provider: str, config: Optional[dict] = None) -> Optional[str]:
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
        raise EnvironmentError(
            f"API key not found. Set the {env_var} environment variable."
        )
    return key


# ---------------------------------------------------------------------------
# LLM call — dispatcher
# ---------------------------------------------------------------------------

def call_llm(
    messages: list[dict],
    system_prompt: str,
    task: str = "conversation",
    stream: bool = True,
    config: Optional[dict] = None,
    timeout: float = 60.0,
) -> str:
    """
    Route to the correct provider and return the assistant's reply as a string.

    messages: list of {role, content} — the conversation history
    system_prompt: YANA's assembled identity context
    task: routing key (conversation | pulse_scheduled | pulse_triggered | first_breath)
    stream: stream tokens to stdout while accumulating
    """
    if config is None:
        config = load_providers()

    provider, model_id = resolve_model(task, config)

    if provider == "anthropic":
        api_key = get_api_key("anthropic", config)
        return _call_anthropic(messages, system_prompt, model_id, api_key, stream, timeout)
    elif provider == "bedrock":
        region, profile = _bedrock_config(config)
        return _call_bedrock(messages, system_prompt, model_id, region, profile, stream, timeout)
    elif provider == "openai":
        api_key = get_api_key("openai", config)
        return _call_openai(messages, system_prompt, model_id, api_key, stream, timeout)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _bedrock_config(config: dict) -> tuple[str, Optional[str]]:
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
    timeout: float = 60.0,
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
            messages=messages,
        ) as s:
            for text in s.text_stream:
                print(text, end="", flush=True)
                full_text += text
        print()
        return full_text
    else:
        response = client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text


# ---------------------------------------------------------------------------
# Bedrock (AnthropicBedrock — same SDK, different client)
# ---------------------------------------------------------------------------

def _call_bedrock(
    messages: list[dict],
    system_prompt: str,
    model_id: str,
    region: str,
    profile: Optional[str],
    stream: bool,
    timeout: float = 60.0,
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
            messages=messages,
        ) as s:
            for text in s.text_stream:
                print(text, end="", flush=True)
                full_text += text
        print()
        return full_text
    else:
        response = client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _call_openai(
    messages: list[dict],
    system_prompt: str,
    model_id: str,
    api_key: str,
    stream: bool,
    timeout: float = 60.0,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    if stream:
        full_text = ""
        response = client.chat.completions.create(
            model=model_id,
            messages=full_messages,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                print(delta.content, end="", flush=True)
                full_text += delta.content
        print()
        return full_text
    else:
        response = client.chat.completions.create(
            model=model_id,
            messages=full_messages,
        )
        return response.choices[0].message.content
