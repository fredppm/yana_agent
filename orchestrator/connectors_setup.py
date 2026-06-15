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
    sys.path.insert(0, str(_HERE))  # so `import connectors` works inside connector files

from connectors.loader import load_connectors  # noqa: E402

from connectors import ConnectorRegistry  # noqa: E402


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

    # When Graphiti enabled, sync connector configs to Neo4j for this workspace
    try:
        import json

        import memory as mem
        import yaml

        cfg = mem._load_config()
        if cfg.get("enabled"):
            workspace_id = cfg.get("active_profile") or cfg.get("group_id", "")
            if workspace_id and manifest.exists():
                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                for c in data.get("connectors", []):
                    config_str = json.dumps(c, ensure_ascii=False)
                    mem.save_connector_sync(workspace_id, c["id"], config_str)
    except Exception:
        pass

    return registry
