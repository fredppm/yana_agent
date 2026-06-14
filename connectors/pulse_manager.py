"""
connectors/pulse_manager.py — PulseManagerConnector.

Wraps the Pulse daemon's localhost HTTP API as a standard YANA connector.
YANA uses this to create, list, and remove Pulse tasks through natural language.

The Pulse daemon must be running (`python -m pulse`) for calls to succeed.
If Pulse is not running, operations return a clear error — no crash.

Register in connectors.yaml:
  - type: PulseManagerConnector
    id: pulse
    name: "Pulse"
    description: "Agenda tarefas autônomas do Pulse — criar, listar e remover"
    config:
      port: 7891   # optional, defaults to 7891
"""
from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from connectors import Connector, command, query

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 7891
_TIMEOUT = 5  # seconds


class PulseManagerConnector(Connector):
    connector_description = "Pulse task manager — create, list, and remove autonomous Pulse tasks"

    def __init__(self, host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT) -> None:
        self._base = f"http://{host}:{port}"

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="List all currently scheduled Pulse tasks.",
        returns={"type": "list"},
    )
    def list_tasks(self) -> list[dict]:
        resp = self._get("/tasks")
        return resp.get("tasks", [])

    @query(
        description="Check whether the Pulse daemon is running.",
        returns={"type": "object"},
    )
    def health(self) -> dict:
        return self._get("/health")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @command(
        description=(
            "Create or update a Pulse task. Use when the user asks YANA to schedule "
            "an autonomous observation (e.g. 'me manda um resumo das newsletters todo dia às 10h'). "
            "YANA resolves the correct connector source, operation, and params before calling this. "
            "Task schema: observe(source, operation, params) + schedule(time, days) + deliver(action, prompt)."
        ),
        params={
            "name": {"type": "string"},
            "source": {"type": "string"},
            "operation": {"type": "string"},
            "params": {"type": "object", "required": False},
            "time": {"type": "string"},
            "days": {"type": "string", "required": False},
            "action": {"type": "string"},
            "prompt": {"type": "string", "required": False},
        },
        returns={"type": "boolean"},
    )
    def create_task(
        self,
        name: str,
        source: str,
        operation: str,
        time: str,
        action: str,
        params: dict | None = None,
        days: str = "daily",
        prompt: str = "",
    ) -> bool:
        body = {
            "name": name,
            "observe": {"source": source, "operation": operation, "params": params or {}},
            "schedule": {"mode": "fixed", "time": time, "days": days},
            "deliver": {"action": action, "prompt": prompt},
        }
        self._post("/tasks", body)
        return True

    @command(
        description="Remove a Pulse task by name.",
        params={"name": {"type": "string"}},
        returns={"type": "boolean"},
    )
    def remove_task(self, name: str) -> bool:
        self._delete(f"/tasks/{name}")
        return True

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> dict:
        try:
            with urlopen(f"{self._base}{path}", timeout=_TIMEOUT) as resp:
                return json.loads(resp.read())
        except URLError as exc:
            raise ConnectionError(f"Pulse not reachable at {self._base}: {exc}") from exc

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = Request(
            f"{self._base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read())
        except URLError as exc:
            raise ConnectionError(f"Pulse not reachable at {self._base}: {exc}") from exc

    def _delete(self, path: str) -> dict:
        req = Request(f"{self._base}{path}", method="DELETE")
        try:
            with urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read())
        except URLError as exc:
            raise ConnectionError(f"Pulse not reachable at {self._base}: {exc}") from exc
