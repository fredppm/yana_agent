"""
connectors/base.py — Connector contract framework for YANA.

Provides @query, @command, @event decorators and the Connector base class.
ConnectorResult is the typed envelope returned by every call().

Error strings: "timeout" | "auth" | "validation_error" | str(exc) for unexpected errors

CommunicationChannel: optional interface for connectors that can send/receive messages.
A connector that supports messaging implements both Connector and CommunicationChannel:
    class GmailConnector(Connector, CommunicationChannel): ...
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, cast

# ---------------------------------------------------------------------------
# Schema types
# ---------------------------------------------------------------------------

VALID_TYPES = {"boolean", "number", "string", "array", "object", "list"}


@dataclass
class ParamSchema:
    type: str
    required: bool = True
    unit: str | None = None
    format: str | None = None
    description: str | None = None


@dataclass
class ReturnSchema:
    type: str
    unit: str | None = None
    format: str | None = None


# ---------------------------------------------------------------------------
# Operation metadata
# ---------------------------------------------------------------------------


@dataclass
class OperationMeta:
    name: str
    description: str
    kind: str  # "query" | "command" | "event"
    params: dict[str, ParamSchema] = field(default_factory=dict)
    returns: ReturnSchema | None = None  # query / command
    schema: ReturnSchema | None = None  # event payload schema


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass
class ConnectorResult:
    ok: bool
    data: Any = None
    error: str | None = None  # "timeout" | "auth" | "validation_error" | str(exc)
    detail: str | None = None  # optional hint for the LLM (e.g. available operations)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def query(
    description: str,
    params: dict[str, dict] | None = None,
    returns: dict | None = None,
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        cast(Any, fn)._connector_meta = OperationMeta(
            name=fn.__name__,
            description=description,
            kind="query",
            params=_parse_params(params),
            returns=ReturnSchema(**returns) if returns else ReturnSchema(type="any"),
        )
        return fn

    return decorator


def command(
    description: str,
    params: dict[str, dict] | None = None,
    returns: dict | None = None,
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        cast(Any, fn)._connector_meta = OperationMeta(
            name=fn.__name__,
            description=description,
            kind="command",
            params=_parse_params(params),
            returns=ReturnSchema(**returns) if returns else ReturnSchema(type="boolean"),
        )
        return fn

    return decorator


def event(
    description: str,
    schema: dict | None = None,
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        cast(Any, fn)._connector_meta = OperationMeta(
            name=fn.__name__,
            description=description,
            kind="event",
            schema=ReturnSchema(**schema) if schema else None,
        )
        return fn

    return decorator


def _parse_params(params: dict[str, dict] | None) -> dict[str, ParamSchema]:
    if not params:
        return {}
    return {k: ParamSchema(**v) for k, v in params.items()}


# ---------------------------------------------------------------------------
# Connector base class
# ---------------------------------------------------------------------------


class Connector:
    """
    Base class for all YANA connectors.

    Subclass this and decorate methods with @query, @command, @event.
    The framework collects decorated methods at class definition time.

    Class attributes (optional):
        connector_description: str  — one-line description used in the lightweight
            manifest when no per-instance description is provided in connectors.yaml.
    """

    connector_description: str = ""
    _operations: ClassVar[dict[str, OperationMeta]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._operations = {}
        for attr in vars(cls).values():
            if hasattr(attr, "_connector_meta"):
                meta: OperationMeta = cast(Any, attr)._connector_meta
                cls._operations[meta.name] = meta

    def call(self, operation: str, params: dict[str, Any] | None = None) -> ConnectorResult:
        params = params or {}

        if operation not in self._operations:
            available = ", ".join(self._operations.keys())
            return ConnectorResult(
                ok=False, error="validation_error", detail=f"available: {available}"
            )

        meta = self._operations[operation]

        if meta.kind == "event":
            return ConnectorResult(ok=False, error="validation_error")

        error = _validate_params(params, meta.params)
        if error:
            return ConnectorResult(ok=False, error="validation_error")

        try:
            method = getattr(self, operation)
            data = method(**params)
            return ConnectorResult(ok=True, data=data)
        except TimeoutError:
            return ConnectorResult(ok=False, error="timeout")
        except PermissionError:
            return ConnectorResult(ok=False, error="auth")
        except Exception as exc:
            return ConnectorResult(ok=False, error=str(exc))

    def contract(self) -> dict[str, Any]:
        """Full contract for on-demand loading into AI context."""
        queries = []
        commands = []
        events = []

        for meta in self._operations.values():
            entry: dict[str, Any] = {
                "name": meta.name,
                "description": meta.description,
            }
            if meta.params:
                entry["params"] = {
                    k: {
                        f: getattr(v, f)
                        for f in ("type", "required", "unit", "format", "description")
                        if getattr(v, f) is not None
                    }
                    for k, v in meta.params.items()
                }
            if meta.returns:
                entry["returns"] = {
                    f: getattr(meta.returns, f)
                    for f in ("type", "unit", "format")
                    if getattr(meta.returns, f) is not None
                }
            if meta.schema:
                entry["schema"] = {
                    f: getattr(meta.schema, f)
                    for f in ("type", "unit", "format")
                    if getattr(meta.schema, f) is not None
                }

            if meta.kind == "query":
                queries.append(entry)
            elif meta.kind == "command":
                commands.append(entry)
            elif meta.kind == "event":
                events.append(entry)

        result: dict[str, Any] = {
            "type": self.__class__.__name__,
            "queries": queries,
            "commands": commands,
        }
        if events:
            result["events"] = events
        return result


# ---------------------------------------------------------------------------
# Param validation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CommunicationChannel interface
# ---------------------------------------------------------------------------


class CommunicationChannel:
    """
    Interface for connectors that can send and receive messages.

    A connector that supports messaging declares both base classes:
        class GmailConnector(Connector, CommunicationChannel): ...

    The registry can discover communication-capable connectors via:
        isinstance(connector, CommunicationChannel)

    Credential naming convention for communication connectors:
        app_credential  — OAuth Client ID/Secret or API key. YANA owns. Immutable.
        persona_token   — Per-user OAuth token. Persona owns. Expires and refreshes.
    """

    def send_message(self, address: str, text: str) -> bool:
        """
        Send *text* to *address* on this channel.

        *address* is channel-specific: an email address, a phone number,
        a Slack user/channel ID, etc.

        Returns True on successful delivery, False otherwise.
        """
        raise NotImplementedError

    def get_messages(
        self,
        address: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Retrieve recent messages from *address* (or all inboxes if None).

        Returns a list of message dicts. Schema is channel-specific but
        should always include: {"from": str, "text": str, "timestamp": str}.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------

_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "boolean": lambda v: isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "array": lambda v: isinstance(v, list),
    "list": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "any": lambda v: True,
}


def _validate_params(params: dict[str, Any], schema: dict[str, ParamSchema]) -> str | None:
    for name, spec in schema.items():
        if spec.required and name not in params:
            return f"missing required param: {name}"
        if name in params:
            check = _TYPE_CHECKS.get(spec.type, lambda v: True)
            if not check(params[name]):
                return f"param '{name}' expected {spec.type}"
    return None
