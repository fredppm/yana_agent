"""
connectors_setup.py — populate a ConnectorRegistry for the YANA runtime.

Scans the project connectors/ folder for connector type implementations,
then loads instance configuration from orchestrator/config/connectors.yaml.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from connectors import ConnectorRegistry
from connectors.loader import load_connectors


def build_registry() -> ConnectorRegistry:
    """Build and return a populated ConnectorRegistry.

    Types are discovered by scanning the project-level connectors/ folder.
    Instances are loaded from orchestrator/config/connectors.yaml.
    """
    registry = ConnectorRegistry()

    folder = _PROJECT_ROOT / "connectors"
    if folder.exists():
        load_connectors(folder, registry)

    manifest = _HERE / "config" / "connectors.yaml"
    if manifest.exists():
        registry.load_manifest(manifest)

    return registry
