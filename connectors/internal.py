"""
connectors/internal.py — InternalConnector.

Lightweight connector for YANA-internal operations that need no external
service. Primary use: one-time Pulse reminders where the content is
a plain message, not data fetched from a third-party connector.

Register in connectors.yaml:
  - type: InternalConnector
    id: internal
    name: "Internal"
    description: "Internal YANA operations — reminders, messages, signals"
"""
from __future__ import annotations

from connectors import Connector, query


class InternalConnector(Connector):
    connector_description = "Internal YANA operations — reminders and plain messages, no external service required"

    @query(
        description=(
            "Return a plain message as the operation result. "
            "Use as the source for Pulse one-time reminders: "
            "observe.source='internal', observe.operation='remind', "
            "observe.params={'message': 'your text here'}."
        ),
        params={
            "message": {"type": "string", "description": "The reminder text to deliver"},
        },
        returns={"type": "string"},
    )
    def remind(self, message: str) -> str:
        return message
