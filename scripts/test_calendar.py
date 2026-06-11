"""
Quick smoke test for Google Calendar connector.
Run this once to trigger OAuth browser consent and verify real API calls.

Usage:
    python scripts/test_calendar.py
"""

import sys
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "orchestrator"))  # so `import connectors` works
sys.path.insert(0, str(root))                   # so `import orchestrator.connectors` works

import importlib.util

def _load(name: str, filepath: Path):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

from connectors import ConnectorRegistry
_gcal_mod = _load("google_calendar_mod", root / "connectors" / "google_calendar.py")
GoogleCalendarConnector = _gcal_mod.GoogleCalendarConnector

CREDENTIALS = Path("~/.yana/google_credentials.json").expanduser()
TOKEN = Path("~/.yana/tokens/calendar_fred.json").expanduser()

print(f"Credentials: {CREDENTIALS}")
print(f"Token:       {TOKEN}")
print(f"Credentials exist: {CREDENTIALS.exists()}")
print()

registry = ConnectorRegistry()
registry.add_instance(
    GoogleCalendarConnector(
        credentials_file=str(CREDENTIALS),
        token_file=str(TOKEN),
    ),
    instance_id="calendar_fred",
    name="Fred's Calendar",
    owner="fred",
)

print("Calling events_today()...")
result = registry.call("calendar_fred", "events_today")

if result.ok:
    events = result.data
    print(f"OK — {len(events)} event(s) today:")
    for e in events:
        print(f"  • {e['start']} | {e['title']}")
    if not events:
        print("  (no events today)")
else:
    print(f"ERROR: {result.error}")
    sys.exit(1)

print()
print("Calling next_event()...")
result2 = registry.call("calendar_fred", "next_event")
if result2.ok:
    e = result2.data
    if e:
        print(f"  Next: {e['start']} | {e['title']}")
    else:
        print("  (no upcoming events)")
else:
    print(f"ERROR: {result2.error}")
