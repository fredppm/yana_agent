"""
sanctum_writer.py — post-session sanctum persistence.

After a conversation ends, asks YANA to output structured sanctum content,
then writes the files to disk. This is the ONLY way sanctum files get updated.

Format YANA must use in her output:
    <<<FILE:BOND.md>>>
    [content]
    <<<END>>>
"""

from __future__ import annotations

import re
from datetime import datetime

import core
import providers as prov

# ---------------------------------------------------------------------------
# Files YANA should write after First Breath
# ---------------------------------------------------------------------------

FIRST_BREATH_FILES = [
    "PERSONA.md",
    "CREED.md",
    "BOND.md",
    "MEMORY.md",
    "PULSE.md",
    "pulse-config.yaml",
    "INDEX.md",
]

REGULAR_SESSION_FILES = [
    "BOND.md",
    "MEMORY.md",
]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _build_sanctum_prompt(files: list[str], session_date: str) -> str:
    file_list = "\n".join(f"- {f}" for f in files)
    session_file = f"sessions/{session_date}.md"

    return f"""The conversation is over. Now write the sanctum files based on everything we discussed.

For each file, use this exact format — no deviations:

<<<FILE:FILENAME>>>
[full file content here]
<<<END>>>

Files to write:
{file_list}
- {session_file}

Rules:
- Replace ALL {{...}} placeholders with real content from our conversation. None should remain.
- BOND.md: who Fred IS (enduring truths). Not what he's going through right now.
- MEMORY.md: current situations, open threads, tracked items. Things that change.
- {session_file}: raw log of this session. What happened, what you learned, observations.
- PERSONA.md: your identity as it crystallized through this conversation. Include your first evolution log entry.
- CREED.md: your mission, values, standing orders — filled in from what you learned about Fred.
- PULSE.md: autonomous routines configured, quiet hours confirmed, any specific triggers discussed.
- pulse-config.yaml: valid YAML with quiet hours and scheduled task config.
- INDEX.md: list of all sanctum files with one-line descriptions.

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
) -> dict[str, str]:
    """
    Call YANA with the full conversation history + sanctum write prompt.
    Parse the response and write files to the sanctum.

    Returns dict of {filename: content} for files written.
    """
    if config is None:
        config = prov.load_providers()

    if session_date is None:
        session_date = datetime.now().strftime("%Y-%m-%d")

    files = FIRST_BREATH_FILES if is_first_breath else REGULAR_SESSION_FILES
    sanctum_prompt = _build_sanctum_prompt(files, session_date)

    # Add the write request as a final user message
    write_messages = [*messages, {"role": "user", "content": sanctum_prompt}]

    print("\n[salvando sanctum...]", flush=True)
    response = prov.call_llm(
        write_messages,
        system_prompt,
        task="conversation",
        stream=True,  # stream to avoid timeout on large responses
        config=config,
        timeout=300.0,  # 5 min — writing 8 files takes time
    )

    written = _parse_and_write(response)

    if written:
        print(f"[sanctum atualizado: {len(written)} arquivo(s)]")
        for fname in written:
            print(f"  ✓ {fname}")
    else:
        print("[aviso: nenhum arquivo foi gerado — verifique o log da sessão]")
        # Save raw response for debugging
        _save_raw_response(response, session_date)

    return written


def _parse_and_write(response: str) -> dict[str, str]:
    """Parse <<<FILE:name>>> ... <<<END>>> blocks and write to sanctum."""
    pattern = re.compile(
        r"<<<FILE:([^>]+)>>>\n(.*?)<<<END>>>",
        re.DOTALL,
    )

    sanctum = core.sanctum_path()
    written: dict[str, str] = {}

    for match in pattern.finditer(response):
        filename = match.group(1).strip()
        content = match.group(2).strip()

        # Resolve path — allow sessions/ subfolder
        file_path = sanctum / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        written[filename] = content

    return written


def _save_raw_response(response: str, session_date: str) -> None:
    """Save raw LLM response when parsing fails, for debugging."""
    debug_path = core.sanctum_path() / f"_debug-sanctum-write-{session_date}.txt"
    debug_path.write_text(response, encoding="utf-8")
    print(f"  [resposta bruta salva em {debug_path.name} para inspeção]")
