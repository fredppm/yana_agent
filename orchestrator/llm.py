"""
llm.py — LLM routing via LiteLLM proxy.

All calls go through a single Anthropic SDK client pointed at the LiteLLM base URL.
LiteLLM translates to Bedrock (or any backend) transparently.

Config is read from environment variables. Place a .env file in orchestrator/ for local dev.

Required env vars:
  LITELLM_URL                   LiteLLM proxy base URL (default: http://127.0.0.1:4000)
  YANA_MODEL_CONVERSATION       model alias for main conversation
  YANA_MODEL_CONVERSATION_FAST  model alias for short/fast exchanges
  YANA_MODEL_FIRST_BREATH       model alias for first-breath setup
  YANA_MODEL_SANCTUM_WRITE      model alias for sanctum writes
  YANA_MODEL_PULSE_SCHEDULED    model alias for scheduled PULSE tasks
  YANA_MODEL_PULSE_TRIGGERED    model alias for triggered PULSE tasks
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ---------------------------------------------------------------------------
# Task → env var mapping
# ---------------------------------------------------------------------------

_TASK_ENV: dict[str, str] = {
    "conversation": "YANA_MODEL_CONVERSATION",
    "conversation_fast": "YANA_MODEL_CONVERSATION_FAST",
    "first_breath": "YANA_MODEL_FIRST_BREATH",
    "sanctum_write": "YANA_MODEL_SANCTUM_WRITE",
    "pulse_scheduled": "YANA_MODEL_PULSE_SCHEDULED",
    "pulse_triggered": "YANA_MODEL_PULSE_TRIGGERED",
}

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_providers() -> dict:
    """Return config dict built from environment variables."""
    return {
        "litellm_url": os.environ.get("LITELLM_URL", "http://127.0.0.1:4000"),
        "models": {task: os.environ.get(env) for task, env in _TASK_ENV.items()},
    }


def resolve_model(task: str = "conversation", config: dict | None = None) -> tuple[str, str]:
    """Return ("litellm", model_alias) for the given task. Raises ValueError if no model configured."""
    if config is None:
        config = load_providers()
    models = config.get("models", {})
    model = models.get(task) or models.get("conversation")
    if not model:
        raise ValueError(
            f"No model configured for task {task!r} — set YANA_MODEL_CONVERSATION (and optionally YANA_MODEL_{task.upper()})"
        )
    return "litellm", model


# ---------------------------------------------------------------------------
# Auto-downgrade (contract: do not change thresholds without updating tests)
# ---------------------------------------------------------------------------


def _auto_task(messages: list[dict], task: str) -> str:
    """Downgrade 'conversation' to 'conversation_fast' for short/simple exchanges."""
    if task != "conversation":
        return task
    last = messages[-1].get("content", "") if messages else ""
    if len(last) < 120 and len(messages) <= 6:
        return "conversation_fast"
    return task


# ---------------------------------------------------------------------------
# Connector tool definitions (fixed surface — at most 2 tools)
# ---------------------------------------------------------------------------


RUN_CODE_TOOL: dict = {
    "name": "run_code",
    "description": (
        "Execute Python code in an isolated sandbox container. "
        "Use this whenever you need to run code, perform calculations, process data, "
        "or verify that generated code works. "
        "The sandbox has no access to the host filesystem or local commands. "
        "Network is blocked by default — set allow_network=true only when the code "
        "explicitly needs to reach an external API."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
            "deps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "PyPI packages to install before execution (e.g. ['requests', 'numpy==1.26.0']).",
            },
            "allow_network": {
                "type": "boolean",
                "description": "Grant outbound network access during execution. Default false.",
            },
        },
        "required": ["code"],
    },
}

CONNECTOR_TOOLS: list[dict] = [
    {
        "name": "call_connector",
        "description": (
            "Invoke a registered connector operation to read data or execute an action. "
            "Use the connector manifest in the system prompt to find the right instance_id and operation. "
            'If the response contains {"error": "validation_error", "detail": "available: ..."}, '
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
# Client factory
# ---------------------------------------------------------------------------


def _make_client(config: dict):
    import anthropic
    import httpx

    url = config.get("litellm_url", "http://127.0.0.1:4000")
    return anthropic.Anthropic(
        api_key="litellm",
        base_url=url,
        http_client=httpx.Client(timeout=None),  # timeout controlled per-call
    )


# ---------------------------------------------------------------------------
# Message sanitisation
# ---------------------------------------------------------------------------

_MSG_KEYS = {"role", "content"}


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Strip non-standard top-level fields (e.g. 'ts', 'payload') from messages.

    The Anthropic API (and Bedrock via LiteLLM) only accepts 'role' and 'content'
    at the message top level. Extra fields added by the TUI for display/storage
    purposes must be removed before the API call.
    """
    return [
        {k: v for k, v in m.items() if k in _MSG_KEYS}
        for m in messages
    ]


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def call_llm(
    messages: list[dict],
    system_prompt: str,
    task: str = "conversation",
    stream: bool = True,
    config: dict | None = None,
    timeout: float = 60.0,
    on_token: Callable[[str], None] | None = None,
) -> str:
    if config is None:
        config = load_providers()

    _on_token: Callable[[str], None] = on_token if on_token is not None else lambda _: None
    task = _auto_task(messages, task)
    _, model = resolve_model(task, config)
    client = _make_client(config)
    clean = _sanitize_messages(messages)

    import httpx

    if stream:
        full_text = ""
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=clean,
            timeout=httpx.Timeout(timeout, connect=10.0),
        ) as s:
            for text in s.text_stream:
                _on_token(text)
                full_text += text
        return full_text
    else:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=clean,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        block = response.content[0]
        return block.text if hasattr(block, "text") else ""


# ---------------------------------------------------------------------------
# Tool-aware LLM call
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
    """
    if config is None:
        config = load_providers()

    _, model = resolve_model(task, config)
    client = _make_client(config)
    clean = _sanitize_messages(messages)

    import httpx

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=clean,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        timeout=httpx.Timeout(timeout, connect=10.0),
    )

    text_parts: list[str] = []
    tool_uses: list[dict] = []
    raw_content: list = list(response.content)

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            block_input = block.input
            if isinstance(block_input, str):
                try:
                    block_input = json.loads(block_input)
                except (json.JSONDecodeError, ValueError):
                    block_input = {}
            tool_uses.append({"id": block.id, "name": block.name, "input": block_input})

    return "".join(text_parts), tool_uses, raw_content
