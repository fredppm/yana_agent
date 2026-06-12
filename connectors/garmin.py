"""
connectors/garmin.py — GarminActivity connector stub.

Contract definition only — methods raise NotImplementedError until
the Garmin Connect API integration is wired up.
"""

from __future__ import annotations

from connectors import Connector, command, event, query


class GarminActivityConnector(Connector):
    connector_description = "Health and activity data via Garmin — steps, sleep, stress, runs"

    @query(
        description="Steps taken today",
        returns={"type": "number", "unit": "steps/day"},
    )
    def steps_today(self) -> int:
        raise NotImplementedError

    @query(
        description="Calories burned today",
        returns={"type": "number", "unit": "kcal"},
    )
    def calories_today(self) -> int:
        raise NotImplementedError

    @query(
        description="Current stress level (0–100)",
        returns={"type": "number", "unit": "stress_score"},
    )
    def stress_level(self) -> int:
        raise NotImplementedError

    @query(
        description="Last night's sleep data",
        returns={"type": "object"},
    )
    def last_sleep(self) -> dict:
        raise NotImplementedError

    @query(
        description="Most recent recorded physical activity",
        returns={"type": "object"},
    )
    def last_activity(self) -> dict:
        raise NotImplementedError

    @query(
        description="Heart rate history over the last N hours",
        params={
            "hours": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def heart_rate_history(self, hours: int = 24) -> list:
        raise NotImplementedError

    @command(
        description="Manually sync data from the device",
        returns={"type": "boolean"},
    )
    def sync(self) -> bool:
        raise NotImplementedError

    @event(
        description="New physical activity recorded on the device",
        schema={"type": "object"},
    )
    def on_new_activity(self, callback) -> None:  # type: ignore[type-arg]
        raise NotImplementedError
