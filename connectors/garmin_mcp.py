"""
connectors/garmin_mcp.py — GarminMCPConnector.

Routes YANA connector calls to a local garmin-connect-mcp MCP server process
(eddmann/garmin-connect-mcp) via the Python MCP SDK.

Declares the same contract as GarminActivityConnector so the existing
contract tests pass unchanged with this backend.

Setup:
  1. Install garmin-connect-mcp: pip install garmin-connect-mcp
     (or use uvx — no local install required)
  2. Run auth once per user:
       GARMINTOKENS=~/.yana/tokens/garmin_fred garmin-connect-mcp auth
  3. Register in orchestrator/config/connectors.yaml:
       - type: GarminMCPConnector
         id: garmin_fred
         name: "Garmin do Fred"
         owner: fred
         config:
           mcp_command: ["garmin-connect-mcp"]
           env:
             GARMINTOKENS: "~/.yana/tokens/garmin_fred"
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import AsyncExitStack
from datetime import date
from typing import Any

from connectors import Connector, event, query


class GarminMCPConnector(Connector):
    connector_description = "Health and activity data via Garmin Connect MCP — steps, sleep, stress, runs"

    def __init__(
        self,
        mcp_command: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        # mcp_command: command + args to launch the MCP server process via stdio.
        # Defaults to the installed CLI. Override with ["uvx", "garmin-connect-mcp"]
        # if not installing locally.
        self._mcp_command = mcp_command or ["garmin-connect-mcp"]

        # Merge caller-supplied env into the current process env.
        # Expand ~ in path-like values so GARMINTOKENS=~/.yana/... works.
        merged: dict[str, str] = dict(os.environ)
        for k, v in (env or {}).items():
            merged[k] = os.path.expanduser(v) if isinstance(v, str) else v
        self._env = merged

        # Dedicated event loop running in a background thread — keeps the MCP
        # session (and the garmin-connect-mcp subprocess) alive across calls.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name=f"garmin-mcp-{id(self)}",
        )
        self._thread.start()
        self._session: Any = None
        self._exit_stack: AsyncExitStack | None = None
        self._connect()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._run(self._start_session())

    def _run(self, coro: Any) -> Any:
        """Submit a coroutine to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    async def _start_session(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._mcp_command[0],
            args=self._mcp_command[1:],
            env=self._env,
        )
        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = ClientSession(read, write)
        self._session = await self._exit_stack.enter_async_context(session)
        await self._session.initialize()

    async def _call_async(self, tool: str, args: dict[str, Any]) -> Any:
        result = await self._session.call_tool(tool, args)
        if not result.content:
            return None
        text = getattr(result.content[0], "text", None)
        if text:
            parsed = json.loads(text)
            # All tools wrap payload under "data"
            return parsed.get("data", parsed)
        return None

    def _call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        return self._run(self._call_async(tool, args))

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @query(
        description="Steps taken today",
        returns={"type": "number", "unit": "steps/day"},
    )
    def steps_today(self) -> int:
        data = self._call_tool("query_activity_metrics", {
            "date": "today",
            "metrics": ["steps"],
        })
        steps = (data or {}).get("steps") or {}
        return int(steps.get("totalSteps") or 0)

    @query(
        description="Calories burned today (active + resting)",
        returns={"type": "number", "unit": "kcal"},
    )
    def calories_today(self) -> int:
        data = self._call_tool("query_activity_metrics", {
            "date": "today",
            "metrics": ["steps"],
        })
        steps = (data or {}).get("steps") or {}
        return int(steps.get("totalKilocalories") or steps.get("activeKilocalories") or 0)

    @query(
        description="Average stress level today (0-100). Returns -1 if no data yet.",
        returns={"type": "number", "unit": "stress_score"},
    )
    def stress_level(self) -> int:
        data = self._call_tool("query_activity_metrics", {
            "date": "today",
            "metrics": ["stress"],
        })
        stress = (data or {}).get("stress") or {}
        value = stress.get("avgStressLevel")
        return int(value) if value is not None and value >= 0 else -1

    @query(
        description="Last night's sleep summary",
        returns={"type": "object"},
    )
    def last_sleep(self) -> dict:
        data = self._call_tool("query_sleep_data", {"date": "today"})
        dto = (data or {}).get("dailySleepDTO") or data or {}
        return self._format_sleep(dto)

    @query(
        description="Most recent recorded physical activity",
        returns={"type": "object"},
    )
    def last_activity(self) -> dict:
        data = self._call_tool("query_activities", {
            "start_date": date.today().isoformat(),
            "limit": 1,
        })
        activities = data if isinstance(data, list) else (data or {}).get("activities") or []
        return self._format_activity(activities[0]) if activities else {}

    @query(
        description="Heart rate readings over the last N hours (default 24)",
        params={"hours": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def heart_rate_history(self, hours: int = 24) -> list:
        data = self._call_tool("query_heart_rate_data", {"date": "today"})
        readings = (data or {}).get("heartRateValues") or []
        if hours < 24:
            import time as _time
            cutoff_ms = int((_time.time() - hours * 3600) * 1000)
            readings = [r for r in readings if r and r[0] and r[0] >= cutoff_ms]
        return [
            {"timestamp_ms": r[0], "bpm": r[1]}
            for r in readings
            if r and len(r) >= 2 and r[1] is not None
        ]

    # ------------------------------------------------------------------
    # Events — not implemented; YANA uses PULSE polling for this backend
    # ------------------------------------------------------------------

    # (No @event decorators — GarminMCPConnector is a polling-only connector)

    # ------------------------------------------------------------------
    # Response transformers — must produce the exact contract shape
    # ------------------------------------------------------------------

    def _format_sleep(self, dto: dict) -> dict:
        def _sec_to_h(sec: int | None) -> float | None:
            return round(sec / 3600, 2) if sec else None

        sleep_scores = dto.get("sleepScores") or {}
        overall = sleep_scores.get("overall") or {} if isinstance(sleep_scores, dict) else {}
        score = overall.get("value") if isinstance(overall, dict) else None

        return {
            "total_sleep_h": _sec_to_h(dto.get("sleepTimeSeconds")),
            "deep_h": _sec_to_h(dto.get("deepSleepSeconds")),
            "light_h": _sec_to_h(dto.get("lightSleepSeconds")),
            "rem_h": _sec_to_h(dto.get("remSleepSeconds")),
            "awake_h": _sec_to_h(dto.get("awakeSleepSeconds")),
            "score": score,
            "start_gmt": dto.get("sleepStartTimestampGMT"),
            "end_gmt": dto.get("sleepEndTimestampGMT"),
        }

    def _format_activity(self, raw: dict) -> dict:
        activity_type = raw.get("activityType") or {}
        return {
            "id": raw.get("activityId"),
            "name": raw.get("activityName"),
            "type": activity_type.get("typeKey") if isinstance(activity_type, dict) else None,
            "start": raw.get("startTimeLocal"),
            "duration_min": round((raw.get("duration") or 0) / 60, 1),
            "distance_km": round((raw.get("distance") or 0) / 1000, 2)
            if raw.get("distance")
            else None,
            "calories": raw.get("calories"),
            "avg_hr": raw.get("averageHR"),
            "max_hr": raw.get("maxHR"),
            "avg_pace_min_km": raw.get("averageSpeed"),
        }
