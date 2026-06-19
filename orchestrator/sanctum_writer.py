"""
sanctum_writer.py — post-session sanctum persistence.

After a conversation ends, asks YANA to output structured sanctum content,
then persists the fields to Neo4j via memory.py.

Format YANA must use in her output:
    <<<FILE:BOND>>>
    [content]
    <<<END>>>
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import errors
import llm as prov
import output
import profiles

# ---------------------------------------------------------------------------
# Files YANA should write after First Breath
# ---------------------------------------------------------------------------

FIRST_BREATH_FILES = [
    "OWNER_NAME",
    "PERSONA",
    "CREED",
    "BOND",
    "PULSE",
    "PULSE_CONFIG",
]

REGULAR_SESSION_FILES = [
    "BOND",
]

SANCTUM_CONTEXT_LIMIT = 20  # max messages sent to LLM for sanctum write


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_sanctum_prompt(files: list[str]) -> str:
    file_list = "\n".join(f"- {f}" for f in files)

    return f"""The conversation is over. Now write the sanctum files based on everything we discussed.

For each file, use this exact format — no deviations:

<<<FILE:FILENAME>>>
[full file content here]
<<<END>>>

Files to write:
{file_list}

Rules:
- Replace ALL {{...}} placeholders with real content from our conversation. None should remain.
- OWNER_NAME: a single word — the owner's first name, exactly as they said it. Nothing else.
- BOND: who the owner IS (enduring truths). Not what they're going through right now.
- PERSONA: your identity as it crystallized through this conversation. Include your first evolution log entry.
- CREED: your mission, values, standing orders — filled in from what you learned about the owner.
- PULSE: autonomous routines configured, quiet hours confirmed, any specific triggers discussed.
- PULSE_CONFIG: valid YAML with quiet hours and scheduled task config.

Write every file. No skipping. No summarizing with "same as template". Real content only."""


# ---------------------------------------------------------------------------
# Write sanctum
# ---------------------------------------------------------------------------


def write_sanctum(
    messages: list[dict],
    system_prompt: str,
    is_first_breath: bool,
    config: dict | None = None,
    session_date: str | None = None,
    silent: bool = False,
    save: bool = True,
) -> dict[str, str]:
    """
    Call YANA with conversation history + sanctum write prompt.
    Parse the response and write files to the sanctum.

    Returns dict of {filename: content} for files written.
    silent=True suppresses all terminal output (for TUI mode).
    """
    if config is None:
        config = prov.load_providers()

    if session_date is None:
        session_date = datetime.now().strftime("%Y-%m-%d")

    files = FIRST_BREATH_FILES if is_first_breath else REGULAR_SESSION_FILES
    sanctum_prompt = _build_sanctum_prompt(files)

    # Truncate context — recent messages carry all the relevant signal
    context = messages[-SANCTUM_CONTEXT_LIMIT:]
    write_messages = [*context, {"role": "user", "content": sanctum_prompt}]

    if not silent:
        output.status("saving sanctum...")
    response = prov.call_llm(
        write_messages,
        system_prompt,
        task="sanctum_write",
        stream=True,
        config=config,
        timeout=300.0,
        on_token=None if silent else output.stream_token,
    )
    if not silent:
        print()  # newline after stream

    written = _parse_and_write(response)

    if written and save:
        active = profiles.get_active_profile()
        owner_id = profiles.owner_id_from_profile(active)
        import store

        store.save_sanctum_fields_sync(owner_id, active, written)

    if not silent:
        if written:
            output.status(f"sanctum updated: {len(written)} file(s)")
            for fname in written:
                output.status(f"  ✓ {fname}")
        else:
            output.warn(errors.e("MEM-003"))
            _save_raw_response(response, session_date)

    return written


def _parse_and_write(response: str) -> dict[str, str]:
    """Parse <<<FILE:name>>> ... <<<END>>> blocks. Returns {filename: content}."""
    pattern = re.compile(
        r"<<<FILE:([^>]+)>>>\n(.*?)<<<END>>>",
        re.DOTALL,
    )

    written: dict[str, str] = {}

    for match in pattern.finditer(response):
        filename = match.group(1).strip()
        content = match.group(2).strip()

        # Security: reject absolute paths, traversal, and dot-prefixed names
        # Note: PurePosixPath normalises "./" away, so check raw string first
        from pathlib import PurePosixPath

        if not filename or filename.startswith((".", "/", "\\")):
            output.warn(errors.e("MEM-001", filename=filename))
            continue
        parts = PurePosixPath(filename).parts
        if any(p in ("..", ".") for p in parts) or PurePosixPath(filename).is_absolute():
            output.warn(errors.e("MEM-001", filename=filename))
            continue

        written[filename] = content

    return written


def _save_raw_response(response: str, session_date: str) -> None:
    """Save raw LLM response when parsing fails, for debugging."""
    debug_path = Path(__file__).parent / "config" / f"_debug-sanctum-{session_date}.txt"
    debug_path.write_text(response, encoding="utf-8")
    output.status(errors.e("MEM-004", filename=debug_path.name))


# ---------------------------------------------------------------------------
# Session title + summary generation
# ---------------------------------------------------------------------------

_TITLE_CONTEXT_LIMIT = 20  # max messages for title generation

_TITLE_PROMPT = """Analyze this conversation and generate a title and summary.

Skip any greetings, pleasantries, or small talk. Extract the real topic(s) discussed.

Use this exact format — no deviations:

<<<TITLE>>>
[One line, 80-120 chars. Topic + key detail. No quotes, no period at the end]
<<<END>>>

<<<SUMMARY>>>
[1-3 sentences. Last state of the discussion + any pending decisions or follow-ups]
<<<END>>>

Rules:
- Title must capture WHAT was discussed, not that a conversation happened
- If multiple topics: focus on the most substantive one
- Summary should help the user remember where they left off
- Write in the same language as the conversation
- If the conversation is too short or trivial (only greetings), return nothing"""


def write_session_title(
    messages: list[dict],
    config: dict | None = None,
) -> dict[str, str]:
    """
    Generate a title and summary for a conversation session.

    Calls the LLM with task "conversation_fast" (cheap, fast) to produce a
    one-line title and a 1-3 sentence summary.

    Returns {"title": "...", "summary": "..."} or empty dict if parsing fails.
    Never raises — always returns a dict.
    """
    try:
        if config is None:
            config = prov.load_providers()

        context = messages[-_TITLE_CONTEXT_LIMIT:]
        if not context:
            return {}

        # Strip tool_use / tool_result blocks — they break LLM calls without tool config.
        # Keep only messages that have plain text content.
        def _text_only(msg: dict) -> dict | None:
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text = " ".join(text_parts).strip()
                if not text:
                    return None
                return {**msg, "content": text}
            return msg if str(content).strip() else None

        clean_context = [m for msg in context if (m := _text_only(msg)) is not None]
        if not clean_context:
            return {}

        title_messages = [*clean_context, {"role": "user", "content": _TITLE_PROMPT}]

        response = prov.call_llm(
            title_messages,
            "You are a session summarizer. Generate a title and summary for this conversation.",
            task="conversation_fast",
            stream=False,
            config=config,
            timeout=30.0,
        )

        result = _parse_title_response(response)
        from pathlib import Path as _Path
        _log = _Path(__file__).parent / "title-debug.log"
        _log.write_text(f"OK\nresponse={response[:500]}\nparsed={result}", encoding="utf-8")
        return result
    except Exception as _e:
        import traceback as _tb
        from pathlib import Path as _Path
        _log = _Path(__file__).parent / "title-debug.log"
        _log.write_text(f"ERROR: {_e}\n{_tb.format_exc()}", encoding="utf-8")
        return {}


def _parse_title_response(response: str) -> dict[str, str]:
    """Parse <<<TITLE>>>...<<<END>>> and <<<SUMMARY>>>...<<<END>>> blocks.

    Returns {"title": "...", "summary": "..."} or empty dict if parsing fails.
    """
    title_match = re.search(r"<<<TITLE>>>\n(.*?)<<<END>>>", response, re.DOTALL)
    summary_match = re.search(r"<<<SUMMARY>>>\n(.*?)<<<END>>>", response, re.DOTALL)

    if not title_match:
        return {}

    title = title_match.group(1).strip()
    if not title:
        return {}

    result: dict[str, str] = {"title": title[:200]}

    if summary_match:
        summary = summary_match.group(1).strip()
        if summary:
            result["summary"] = summary

    return result
