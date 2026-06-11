"""
connectors/garmin.py — GarminActivity connector stub.

Validates the connector contract against real Garmin data shapes.
Implementation methods raise NotImplementedError until the Garmin API
integration is wired up.
"""

from __future__ import annotations

from orchestrator.connectors import Connector, command, event, query


class GarminActivityConnector(Connector):
    connector_description = "Dados de saúde e atividade física via Garmin — passos, sono, stress, corridas"


    @query(
        description="Passos dados hoje",
        returns={"type": "number", "unit": "steps/day"},
    )
    def steps_today(self) -> int:
        raise NotImplementedError

    @query(
        description="Calorias queimadas hoje",
        returns={"type": "number", "unit": "kcal"},
    )
    def calories_today(self) -> int:
        raise NotImplementedError

    @query(
        description="Nível de stress atual (0–100)",
        returns={"type": "number", "unit": "stress_score"},
    )
    def stress_level(self) -> int:
        raise NotImplementedError

    @query(
        description="Dados do sono da última noite",
        returns={"type": "object"},
    )
    def last_sleep(self) -> dict:
        raise NotImplementedError

    @query(
        description="Última atividade física registrada",
        returns={"type": "object"},
    )
    def last_activity(self) -> dict:
        raise NotImplementedError

    @query(
        description="Histórico de batimento cardíaco das últimas horas",
        params={
            "hours": {"type": "number", "required": False},
        },
        returns={"type": "list"},
    )
    def heart_rate_history(self, hours: int = 24) -> list:
        raise NotImplementedError

    @command(
        description="Sincroniza dados do dispositivo manualmente",
        returns={"type": "boolean"},
    )
    def sync(self) -> bool:
        raise NotImplementedError

    @event(
        description="Nova atividade física registrada no dispositivo",
        schema={"type": "object"},
    )
    def on_new_activity(self, callback) -> None:  # type: ignore[type-arg]
        raise NotImplementedError
