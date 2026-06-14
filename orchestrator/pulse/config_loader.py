"""
pulse/config_loader.py — load, validate, and persist pulse-tasks.yaml.

Task schema:
  name: str
  observe:
    source: str            # connector instance ID (e.g. "gmail_fred_personal")
    operation: str         # connector operation name (e.g. "search")
    params: dict           # operation parameters (optional, defaults to {})
  schedule:
    mode: fixed|once
    # mode=fixed: recurring cron-style
    time: HH:MM            # local time
    days: daily|weekdays|weekends|mon,wed,fri
    # mode=once: single fire, auto-removed after execution
    at: ISO datetime       # e.g. "2026-06-14T17:05:00"
  deliver:
    action: summarize|notify|store
    prompt: str            # LLM instruction for "summarize" action
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ObserveConfig:
    source: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScheduleConfig:
    mode: str               # "fixed" | "once"
    time: str = ""          # "HH:MM" — required for mode=fixed
    days: str = "daily"     # for mode=fixed
    at: str | None = None   # ISO datetime — required for mode=once, e.g. "2026-06-14T17:05:00"


@dataclass
class DeliverConfig:
    action: str  # "summarize" | "notify" | "store"
    prompt: str = ""


@dataclass
class PulseTask:
    name: str
    observe: ObserveConfig
    schedule: ScheduleConfig
    deliver: DeliverConfig


class TaskConfigError(ValueError):
    """Raised when a task definition is invalid."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_tasks(tasks_file: Path) -> list[PulseTask]:
    """Load and validate tasks from pulse-tasks.yaml. Returns [] if file missing."""
    if not tasks_file.exists():
        return []
    raw = yaml.safe_load(tasks_file.read_text(encoding="utf-8")) or {}
    return [_parse_task(t) for t in raw.get("tasks", [])]


def save_tasks(tasks_file: Path, tasks: list[PulseTask]) -> None:
    """Serialise tasks list to pulse-tasks.yaml, creating parent dirs as needed."""
    tasks_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "tasks": [
            {
                "name": t.name,
                "observe": {
                    "source": t.observe.source,
                    "operation": t.observe.operation,
                    "params": t.observe.params,
                },
                "schedule": _serialise_schedule(t.schedule),
                "deliver": {
                    "action": t.deliver.action,
                    "prompt": t.deliver.prompt,
                },
            }
            for t in tasks
        ]
    }
    tasks_file.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def upsert_task(tasks_file: Path, task: PulseTask) -> None:
    """Insert or replace a task by name."""
    existing = load_tasks(tasks_file)
    updated = [t for t in existing if t.name != task.name] + [task]
    save_tasks(tasks_file, updated)


def remove_task(tasks_file: Path, name: str) -> bool:
    """Remove a task by name. Returns True if found and removed."""
    tasks = load_tasks(tasks_file)
    filtered = [t for t in tasks if t.name != name]
    if len(filtered) == len(tasks):
        return False
    save_tasks(tasks_file, filtered)
    return True


# ---------------------------------------------------------------------------
# Internal parsing
# ---------------------------------------------------------------------------


def _serialise_schedule(s: ScheduleConfig) -> dict:
    if s.mode == "once":
        return {"mode": "once", "at": s.at}
    return {"mode": s.mode, "time": s.time, "days": s.days}


def _parse_task(raw: dict) -> PulseTask:
    _require(raw, "name")
    _require(raw, "observe")
    _require(raw, "schedule")
    _require(raw, "deliver")

    obs = raw["observe"]
    _require(obs, "source", parent="observe")
    _require(obs, "operation", parent="observe")

    sch = raw["schedule"]
    _require(sch, "mode", parent="schedule")
    _valid_modes = ("fixed", "once")
    if sch["mode"] not in _valid_modes:
        raise TaskConfigError(
            f"task '{raw['name']}': schedule.mode must be one of {_valid_modes} (got '{sch['mode']}')"
        )
    if sch["mode"] == "fixed":
        _require(sch, "time", parent="schedule")
    if sch["mode"] == "once":
        _require(sch, "at", parent="schedule")

    dlv = raw["deliver"]
    _require(dlv, "action", parent="deliver")
    valid_actions = ("summarize", "notify", "store")
    if dlv["action"] not in valid_actions:
        raise TaskConfigError(
            f"task '{raw['name']}': deliver.action must be one of {valid_actions}"
        )

    return PulseTask(
        name=raw["name"],
        observe=ObserveConfig(
            source=obs["source"],
            operation=obs["operation"],
            params=obs.get("params") or {},
        ),
        schedule=ScheduleConfig(
            mode=sch["mode"],
            time=sch.get("time", ""),
            days=sch.get("days", "daily"),
            at=sch.get("at"),
        ),
        deliver=DeliverConfig(
            action=dlv["action"],
            prompt=dlv.get("prompt", ""),
        ),
    )


def _require(d: dict, key: str, parent: str = "task") -> None:
    if key not in d:
        raise TaskConfigError(f"{parent} missing required field: '{key}'")
