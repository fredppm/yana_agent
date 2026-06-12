"""
connectors/loader.py — Auto-discovery of Connector implementations.

Scans a folder for Python files, imports each module, and registers
all Connector subclasses found with a ConnectorRegistry.

Files starting with '_' are skipped.
Import errors for individual files are isolated — one bad file
does not prevent others from loading.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .base import Connector
from .registry import ConnectorRegistry


def load_connectors(folder: Path, registry: ConnectorRegistry) -> list[str]:
    """
    Scan *folder* for .py files and register all Connector subclasses found.

    Returns the list of registered type names (class names), in load order.
    Raises FileNotFoundError if *folder* does not exist.
    """
    if not folder.exists():
        raise FileNotFoundError(f"connector folder not found: {folder}")

    registered: list[str] = []
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        for cls in _extract_connectors(path):
            registry.register_type(cls)
            registered.append(cls.__name__)
    return registered


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_connectors(path: Path) -> list[type[Connector]]:
    """
    Import a .py file and return all non-base Connector subclasses defined in it.
    Returns [] on import error (error is re-raised as RuntimeError with context).
    """
    module_name = f"_yana_connector_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return []

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise RuntimeError(f"failed to load connector module {path.name}: {exc}") from exc

    return [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, Connector) and obj is not Connector
    ]
