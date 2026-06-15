"""
migrate_connectors.py — one-time import of connectors.yaml into PostgreSQL.

Run from orchestrator/:
    python scripts/migrate_connectors.py --profile fred::pessoal

After this, connectors_setup.py reads from PostgreSQL and ignores the YAML.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure orchestrator/ is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import store
import yaml

_YAML_PATH = Path(__file__).parent.parent / "config" / "connectors.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate connectors.yaml → PostgreSQL")
    parser.add_argument("--profile", required=True, help="Profile id, e.g. fred::pessoal")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be saved, don't write")
    args = parser.parse_args()

    if not _YAML_PATH.exists():
        print(f"[error] Not found: {_YAML_PATH}")
        sys.exit(1)

    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8")) or {}
    connectors = data.get("connectors", [])

    if not connectors:
        print("[warn] No connectors found in YAML.")
        return

    print(f"Profile: {args.profile}")
    print(f"Found {len(connectors)} connector(s) in {_YAML_PATH.name}:\n")

    for c in connectors:
        print(f"  {c['id']} ({c['type']})")
        if args.dry_run:
            continue
        store.save_connector_sync(args.profile, c["id"], json.dumps(c, ensure_ascii=False))

    if args.dry_run:
        print("\n[dry-run] Nothing written.")
    else:
        print(f"\nDone — {len(connectors)} connector(s) saved to PostgreSQL.")
        print("You can now remove or archive connectors.yaml.")


if __name__ == "__main__":
    main()
