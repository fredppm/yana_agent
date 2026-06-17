"""
agent.py — LLM agent tool loop.

Handles one conversation turn, resolving connector tool calls until the model
returns a final text response.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import llm as prov
import log
import sandbox as sb
import voice as v


def _execute_tool(tool_call: dict, registry) -> str:
    """Execute a single connector tool call and return the result as a JSON string."""
    name = tool_call["name"]
    inp = tool_call["input"]

    if name == "call_connector":
        result = registry.call(
            inp["instance_id"],
            inp["operation"],
            inp.get("params") or {},
        )
        if result.ok:
            return json.dumps({"ok": True, "data": result.data})
        payload: dict = {"ok": False, "error": result.error}
        if result.detail:
            payload["detail"] = result.detail
        return json.dumps(payload)

    if name == "get_connector_contract":
        try:
            contract = registry.load_contract(inp["instance_id"])
            return json.dumps(contract)
        except KeyError as exc:
            return json.dumps({"error": str(exc)})

    if name == "run_code":
        result = sb.run(
            code=inp.get("code", ""),
            deps=inp.get("deps") or [],
            allow_network=bool(inp.get("allow_network", False)),
        )
        return json.dumps({
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        })

    return json.dumps({"error": f"unknown tool: {name}"})


def call_with_tool_loop(
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    registry,
    providers_config: dict,
    task: str,
    text_mode: bool = True,
    clear_line: bool = False,
    silent: bool = False,
    on_tool_event: Callable[[str, str, str | None], None] | None = None,
) -> str:
    """
    Run one conversation turn handling any connector tool calls.

    *messages* must already include the latest user message.
    Returns the final text reply after all tool calls are resolved.

    silent=True: skip all terminal output (used by TUI mode — the caller
    renders the reply itself).
    on_tool_event: optional callback(instance_id, operation, error_or_none) fired
    after each tool call resolves — used by the TUI to display tool activity.
    """
    work = list(messages)
    _text_mode = text_mode

    while True:
        text, tool_uses, raw_content = prov.call_llm_with_tools(
            work, system_prompt, tools, task=task, config=providers_config
        )

        if not tool_uses:
            if not silent:
                # Final text response — optionally clear a pending "thinking" line
                if clear_line:
                    log.console.print(" " * 60, end="\r")
                    clear_line = False  # only clear once
                log.yana_prefix(v.ts())
                if text:
                    log.yana_response(text, markdown=_text_mode)
            return text or ""

        # Print any thinking text that preceded the tool calls
        if text and not silent:
            log.console.print(text, end="")

        # Add assistant message (with tool_use blocks) to working history
        work.append({"role": "assistant", "content": raw_content})

        # Execute each tool and collect results
        tool_results = []
        for tc in tool_uses:
            inp = tc["input"]
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except (json.JSONDecodeError, ValueError):
                    inp = {}
                tc = {**tc, "input": inp}
            result_str = _execute_tool(tc, registry)
            instance = inp.get("instance_id", "")
            op = inp.get("operation", tc["name"])
            try:
                _r = json.loads(result_str)
                _err = _r.get("error") if not _r.get("ok", True) else None
            except Exception:
                _err = None
            if not silent:
                if _err:
                    log.connector_err(v.ts(), instance, op, _err)
                else:
                    log.connector_ok(v.ts(), instance, op)
            if on_tool_event is not None:
                on_tool_event(instance, op, _err)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc["id"],
                    "content": result_str,
                }
            )

        # Feed results back as a user message and loop
        work.append({"role": "user", "content": tool_results})
