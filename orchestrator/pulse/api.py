"""
pulse/api.py — lightweight localhost HTTP API for YANA to manage Pulse tasks.

Pulse is the persistent process; YANA is the ephemeral caller.
YANA sends POST/DELETE requests here when the user creates or removes tasks.

Endpoints:
  GET  /health                → 200 {"status": "ok", "jobs": N}
  GET  /tasks                 → 200 {"tasks": [...]}
  POST /tasks                 → 201 (upsert task from JSON body)
  DELETE /tasks/{name}        → 200 | 404

Request/response bodies are JSON. All errors return {"error": "..."}.
Server binds to 127.0.0.1 only — never exposed to the network.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import output
from .config_loader import (
    DeliverConfig,
    ObserveConfig,
    PulseTask,
    ScheduleConfig,
    TaskConfigError,
    _serialise_schedule,
    load_tasks,
    remove_task,
    upsert_task,
)

_DEFAULT_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    tasks_file: Path
    scheduler: Any
    registry: Any

    # Silence default access log — operational logs go through output module
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: ARG002
        pass

    def log_error(self, fmt: str, *args: object) -> None:  # noqa: ARG002
        output.warn(f"[pulse-api] {fmt % args}")

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path == "/health":
            self._json({"status": "ok", "jobs": len(self.scheduler.get_jobs())})
        elif path == "/tasks":
            tasks = load_tasks(self.tasks_file)
            self._json({"tasks": [_task_to_dict(t) for t in tasks]})
        else:
            self._error(404, "not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        # POST /tasks/{name}/run — immediate execution, bypasses scheduler
        if path.endswith("/run"):
            name = path[len("/tasks/"):-len("/run")]
            if not name:
                self._error(400, "task name required")
                return
            tasks = load_tasks(self.tasks_file)
            task = next((t for t in tasks if t.name == name), None)
            if task is None:
                self._error(404, f"task '{name}' not found")
                return
            from .executor import execute_task
            execute_task(task, self.registry)
            output.status(f"[pulse-api] ran task '{name}' immediately")
            self._json({"ok": True, "name": name})
            return
        if path != "/tasks":
            self._error(404, "not found")
            return
        body = self._read_body()
        if body is None:
            return
        try:
            task = _dict_to_task(body)
        except (TaskConfigError, KeyError, TypeError) as exc:
            self._error(400, str(exc))
            return
        upsert_task(self.tasks_file, task)
        _reschedule(self.scheduler, self.tasks_file, self.registry)
        output.status(f"[pulse-api] upserted task '{task.name}'")
        self._json({"ok": True, "name": task.name}, status=201)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        prefix = "/tasks/"
        if not path.startswith(prefix):
            self._error(404, "not found")
            return
        name = path[len(prefix):]
        if not name:
            self._error(400, "task name required")
            return
        removed = remove_task(self.tasks_file, name)
        if not removed:
            self._error(404, f"task '{name}' not found")
            return
        _reschedule(self.scheduler, self.tasks_file, self.registry)
        output.status(f"[pulse-api] removed task '{name}'")
        self._json({"ok": True, "name": name})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _json(self, body: dict, status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, msg: str) -> None:
        self._json({"error": msg}, status=status)

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._error(400, "empty body")
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            self._error(400, f"invalid JSON: {exc}")
            return None


# ---------------------------------------------------------------------------
# Scheduler reload helper
# ---------------------------------------------------------------------------


def _reschedule(scheduler: Any, tasks_file: Path, registry: Any) -> None:
    """
    Rebuild scheduler jobs from the current tasks file.
    Called after every upsert/delete via the API.
    """
    from .runner import build_scheduler

    # Remove all existing pulse jobs
    for job in scheduler.get_jobs():
        job.remove()
    # Re-add from updated file
    for job in build_scheduler(tasks_file, registry).get_jobs():
        trigger = job.trigger
        scheduler.add_job(
            job.func,
            trigger,
            args=job.args,
            id=job.id,
            replace_existing=True,
            name=job.name,
        )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class PulseAPI:
    """Wraps HTTPServer with handler pre-configured with Pulse context."""

    def __init__(
        self,
        tasks_file: Path,
        scheduler: Any,
        registry: Any,
        host: str = _DEFAULT_HOST,
        port: int = 7891,
    ) -> None:
        # Inject dependencies into handler via class attributes
        handler = type(
            "_BoundHandler",
            (_Handler,),
            {"tasks_file": tasks_file, "scheduler": scheduler, "registry": registry},
        )
        self._server = HTTPServer((host, port), handler)

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _task_to_dict(task: PulseTask) -> dict:
    return {
        "name": task.name,
        "observe": {
            "source": task.observe.source,
            "operation": task.observe.operation,
            "params": task.observe.params,
        },
        "schedule": _serialise_schedule(task.schedule),
        "deliver": {
            "action": task.deliver.action,
            "prompt": task.deliver.prompt,
        },
    }


def _dict_to_task(d: dict) -> PulseTask:
    obs = d["observe"]
    sch = d["schedule"]
    dlv = d["deliver"]
    return PulseTask(
        name=d["name"],
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
