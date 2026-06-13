"""Syntax check for all real connector source files.

These tests run py_compile on every .py file in the connectors/ folder
(excluding __init__, __pycache__, and underscore-prefixed files).
A syntax error in any connector will fail here before it can silently
blow up at runtime when the loader tries to import it.
"""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_CONNECTORS_DIR = Path(__file__).parent.parent.parent / "connectors"


def _connector_files() -> list[Path]:
    if not _CONNECTORS_DIR.exists():
        return []
    return [p for p in sorted(_CONNECTORS_DIR.glob("*.py")) if not p.name.startswith("_")]


@pytest.mark.parametrize("path", _connector_files(), ids=lambda p: p.name)
def test_connector_syntax(path: Path) -> None:
    """Each connector file must compile without a SyntaxError."""
    py_compile.compile(str(path), doraise=True)
