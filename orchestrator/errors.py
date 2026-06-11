"""
errors.py — error code catalog for YANA.

Format: {MODULE}-{SEQ}: {message}

Modules:
  CFG — config loading (providers.yaml)
  LLM — model routing / API keys
  SYS — core system (sanctum, session)
  MEM — sanctum writer / memory files
  VOX — voice I/O (STT / TTS)
"""

from __future__ import annotations

_CATALOG: dict[str, str] = {
    # Config
    "CFG-001": "providers.yaml not found at {path}",
    # LLM routing
    "LLM-001": "Could not resolve model for task='{task}' tier='{tier}'. Check providers.yaml routing and models sections.",
    "LLM-002": "API key not found. Set the {env_var} environment variable.",
    # Core / system
    "SYS-001": "SANCTUM NOT FOUND — First Breath required before proceeding.",
    # Memory / sanctum writer
    "MEM-001": "path rejected for security: {filename}",
    "MEM-002": "error writing {filename}: {error}",
    "MEM-003": "no files generated — check session log",
    "MEM-004": "raw response saved at {filename} for inspection",
    # Voice
    "VOX-001": "TTS playback error: {error}",
}


def e(code: str, **kwargs: object) -> str:
    """
    Format an error message with its code prefix.

    Usage:
        raise FileNotFoundError(errors.e("CFG-001", path=path))
        output.warn(errors.e("MEM-001", filename=fname))
    """
    template = _CATALOG.get(code)
    if template is None:
        return f"{code}: (unknown error code)"
    try:
        return f"{code}: {template.format(**kwargs)}"
    except KeyError as missing:
        return f"{code}: {template} [missing param: {missing}]"
