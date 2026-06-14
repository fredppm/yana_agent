"""
pulse/runner.py — APScheduler-based task runner.

Loads pulse-tasks.yaml, schedules each task, and runs the blocking event loop.
Respects quiet_hours from pulse-config.yaml — skips execution silently when
the current time falls in the quiet window.

Entry point: main() — called by __main__.py.
"""
from __future__ import annotations

import threading
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from apscheduler.triggers.date import DateTrigger  # type: ignore[import-untyped]

import output
from connectors.loader import load_connectors
from connectors.registry import ConnectorRegistry
from core import is_quiet_hours, sanctum_path

from .api import PulseAPI
from .config_loader import PulseTask, TaskConfigError, load_tasks, remove_task

# ---------------------------------------------------------------------------
# Days mapping
# ---------------------------------------------------------------------------

_DAYS_MAP = {
    "daily": None,          # no day_of_week restriction
    "weekdays": "mon-fri",
    "weekends": "sat,sun",
}


def _day_of_week(days: str) -> str | None:
    return _DAYS_MAP.get(days, days)  # pass-through for custom e.g. "mon,wed,fri"


# ---------------------------------------------------------------------------
# Scheduler construction
# ---------------------------------------------------------------------------


def build_scheduler(
    tasks_file: Path,
    registry: ConnectorRegistry,
) -> BackgroundScheduler:
    """
    Build a BackgroundScheduler with one job per task in pulse-tasks.yaml.

    Returns the scheduler (not yet started).
    """
    scheduler = BackgroundScheduler()
    tasks = _load_safe(tasks_file)

    for task in tasks:
        if task.schedule.mode == "once":
            trigger = DateTrigger(run_date=task.schedule.at)
            scheduler.add_job(
                _once_execute,
                trigger,
                args=[task, registry, tasks_file],
                id=task.name,
                replace_existing=True,
                name=f"pulse:{task.name}",
            )
            output.status(f"[pulse] scheduled '{task.name}' once at {task.schedule.at}")
        else:
            hour, minute = task.schedule.time.split(":", 1)
            dow = _day_of_week(task.schedule.days)
            trigger_kwargs: dict = {"hour": int(hour), "minute": int(minute)}
            if dow:
                trigger_kwargs["day_of_week"] = dow
            scheduler.add_job(
                _guarded_execute,
                CronTrigger(**trigger_kwargs),
                args=[task, registry],
                id=task.name,
                replace_existing=True,
                name=f"pulse:{task.name}",
            )
            output.status(f"[pulse] scheduled '{task.name}' at {task.schedule.time} ({task.schedule.days})")

    return scheduler


def _guarded_execute(task: PulseTask, registry: ConnectorRegistry) -> None:
    """Job wrapper for fixed tasks: checks quiet hours before executing."""
    if is_quiet_hours():
        output.debug(f"[pulse] quiet hours — skipping '{task.name}'")
        return
    from .executor import execute_task
    execute_task(task, registry)


def _once_execute(task: PulseTask, registry: ConnectorRegistry, tasks_file: Path) -> None:
    """Job wrapper for once tasks: executes then auto-removes from config."""
    from .executor import execute_task
    execute_task(task, registry)
    remove_task(tasks_file, task.name)
    output.status(f"[pulse] once task '{task.name}' completed and removed")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(host: str = "127.0.0.1", port: int = 7891, connectors_dir: Path | None = None) -> None:
    """
    Start the Pulse daemon:
      1. Load connectors from connectors/ directory
      2. Build APScheduler with tasks from pulse-tasks.yaml
      3. Start the HTTP API for YANA to call
      4. Run until interrupted
    """
    output.status("[pulse] starting")

    registry = ConnectorRegistry()
    connectors_path = connectors_dir or (Path(__file__).parent.parent.parent / "connectors")
    if connectors_path.exists():
        load_connectors(connectors_path, registry)
        output.status(f"[pulse] loaded connectors from {connectors_path}")
    manifest = Path(__file__).parent.parent / "config" / "connectors.yaml"
    if manifest.exists():
        registry.load_manifest(manifest)
        output.status(f"[pulse] loaded {len(registry._instances)} connector instance(s)")

    tasks_file = sanctum_path() / "pulse-tasks.yaml"
    scheduler = build_scheduler(tasks_file, registry)
    scheduler.start()
    output.status(f"[pulse] scheduler started — {len(scheduler.get_jobs())} job(s)")

    api = PulseAPI(tasks_file=tasks_file, scheduler=scheduler, registry=registry, host=host, port=port)
    api_thread = threading.Thread(target=api.serve_forever, daemon=True)
    api_thread.start()
    output.status(f"[pulse] API listening on {host}:{port}")
    output.status("[pulse] running — POST /shutdown or Ctrl+C to stop")

    try:
        while not api.stop_event.is_set():
            api.stop_event.wait(timeout=1)  # short timeout keeps Ctrl+C responsive on Windows
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        output.status("[pulse] shutting down")
        scheduler.shutdown(wait=False)
        api.shutdown()


def _load_safe(tasks_file: Path) -> list[PulseTask]:
    try:
        return load_tasks(tasks_file)
    except TaskConfigError as exc:
        output.warn(f"[pulse] invalid task config: {exc}")
        return []
    except Exception as exc:
        output.warn(f"[pulse] could not load tasks: {exc}")
        return []
