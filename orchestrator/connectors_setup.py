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
    Instances are loaded from connectors.yaml and upserted into PostgreSQL on every
    startup, so YAML changes propagate automatically without manual DB edits.
    """
    import json

    import profiles
    import store
    import yaml

    registry = ConnectorRegistry()

    folder = _PROJECT_ROOT / "connectors"
    if folder.exists():
        load_connectors(folder, registry)

    profile_id = profiles.get_active_profile()
    if not profile_id:
        # No profile yet (First Breath) — nothing to load
        return registry

    db_rows = store.list_connectors_sync(profile_id)

    # Sync YAML → DB: upsert all entries so config changes in YAML propagate to DB
    manifest = _HERE / "config" / "connectors.yaml"
    yaml_ids: set[str] = set()
    if manifest.exists():
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        for c in data.get("connectors", []):
            yaml_ids.add(c["id"])
            config_json = json.dumps(c, ensure_ascii=False)
            store.save_connector_sync(profile_id, c["id"], config_json)
            # Replace or append the row so db_rows reflects the current YAML state
            db_rows = [r for r in db_rows if r["instance_id"] != c["id"]]
            db_rows.append({"instance_id": c["id"], "config_json": config_json})

    if db_rows:
        registry.load_from_db(db_rows)
    else:
        registry.load_manifest(manifest)

    return registry
