"""
tests/test_strings.py — validate strings.py catalog integrity.

Checks:
  1. No orphaned keys in _STRINGS (defined but never called via t()).
  2. Both locales define the same key set (no locale gaps).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Collect all keys actually used via t("key") anywhere in the codebase
# ---------------------------------------------------------------------------

_SRC_ROOT = Path(__file__).parent.parent.parent  # yana_agent/


def _collect_used_keys() -> set[str]:
    """Scan all .py files for t("key") or t('key') calls."""
    pattern = re.compile(r"""t\(\s*["']([\w_]+)["']""")
    used: set[str] = set()
    for py_file in _SRC_ROOT.rglob("*.py"):
        # Skip hidden dirs relative to the scan root (e.g. .venv, __pycache__)
        if any(part.startswith(".") for part in py_file.relative_to(_SRC_ROOT).parts):
            continue
        try:
            src = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        used.update(pattern.findall(src))
    return used


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_orphaned_string_keys() -> None:
    """Every key in _STRINGS['en'] must be called somewhere via t()."""
    from strings import _STRINGS

    defined = set(_STRINGS["en"].keys())
    used = _collect_used_keys()
    orphaned = defined - used
    assert not orphaned, (
        f"Orphaned string keys (defined but never used): {sorted(orphaned)}\n"
        "Remove them from strings.py or add a t() call."
    )


def test_locale_parity() -> None:
    """All locales must define the same keys — no gaps between en and pt_BR."""
    from strings import _STRINGS

    locales = list(_STRINGS.keys())
    if len(locales) < 2:
        pytest.skip("Only one locale defined — parity check skipped.")

    reference = set(_STRINGS[locales[0]].keys())
    for locale in locales[1:]:
        current = set(_STRINGS[locale].keys())
        missing = reference - current
        extra = current - reference
        assert not missing, f"Locale '{locale}' missing keys: {sorted(missing)}"
        assert not extra, f"Locale '{locale}' has extra keys not in '{locales[0]}': {sorted(extra)}"
