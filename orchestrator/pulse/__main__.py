"""
pulse/__main__.py — entry point for `python -m pulse`.

Usage:
    cd orchestrator
    python -m pulse
    python -m pulse --port 7891
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure orchestrator/ is on sys.path when running as `python -m pulse`
_orch = Path(__file__).parent.parent
if str(_orch) not in sys.path:
    sys.path.insert(0, str(_orch))

from pulse.runner import main  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YANA Pulse daemon")
    parser.add_argument(
        "--port",
        type=int,
        default=7891,
        help="localhost port for the Pulse HTTP API (default: 7891)",
    )
    args = parser.parse_args()
    main(port=args.port)
