"""
connectors/google_calendar.py — GoogleCalendar connector stub.
"""

from __future__ import annotations

from orchestrator.connectors import Connector, command, event, query


class GoogleCalendarConnector(Connector):
    connector_description = "Eventos e compromissos do Google Calendar — leitura e criação"


    @query(
        description="Eventos de hoje em todos os calendários",
        returns={"type": "list"},
    )
    def events_today(self) -> list:
        raise NotImplementedError

    @query(
        description="Próximo evento agendado a partir de agora",
        returns={"type": "object"},
    )
    def next_event(self) -> dict:
        raise NotImplementedError

    @query(
        description="Eventos nos próximos N dias",
        params={"days": {"type": "number", "required": False}},
        returns={"type": "list"},
    )
    def upcoming_events(self, days: int = 7) -> list:
        raise NotImplementedError

    @query(
        description="Verifica disponibilidade num horário específico",
        params={
            "start_iso": {"type": "string"},
            "end_iso":   {"type": "string"},
        },
        returns={"type": "boolean"},
    )
    def is_available(self, start_iso: str, end_iso: str) -> bool:
        raise NotImplementedError

    @command(
        description="Cria um novo evento no calendário",
        params={
            "title":     {"type": "string"},
            "start_iso": {"type": "string"},
            "end_iso":   {"type": "string"},
            "notes":     {"type": "string", "required": False},
        },
        returns={"type": "object"},
    )
    def create_event(self, title: str, start_iso: str, end_iso: str, notes: str = "") -> dict:
        raise NotImplementedError

    @command(
        description="Cancela um evento existente pelo ID",
        params={"event_id": {"type": "string"}},
        returns={"type": "boolean"},
    )
    def cancel_event(self, event_id: str) -> bool:
        raise NotImplementedError

    @event(
        description="Novo evento adicionado ao calendário",
        schema={"type": "object"},
    )
    def on_event_created(self, callback) -> None:  # type: ignore[type-arg]
        raise NotImplementedError

    @event(
        description="Evento com início em 15 minutos",
        schema={"type": "object"},
    )
    def on_event_reminder(self, callback) -> None:  # type: ignore[type-arg]
        raise NotImplementedError
