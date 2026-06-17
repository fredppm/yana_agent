"""
connectors/registry.py — ConnectorInstance + ConnectorRegistry for YANA.

Two-level discovery:
  Level 1: lightweight_manifest() — id, name, description (always in AI context)
  Level 2: load_contract(id)      — full typed schema (loaded on demand)

Events:
  subscribe(instance_id, event_name, handler) — register a callback
  activate_events(instance_id)               — start all event listeners
  polling_candidates()                        — instances with no events (for PULSE)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .base import Connector, ConnectorResult

# ---------------------------------------------------------------------------
# ConnectorInstance — manifest entry
# ---------------------------------------------------------------------------


@dataclass
class ConnectorInstance:
    id: str
    name: str
    description: str
    type: str  # ConnectorType class name
    owner: str | None = None
    config: dict[str, Any] = field(default_factory=dict)  # constructor kwargs


# ---------------------------------------------------------------------------
# ConnectorRegistry
# ---------------------------------------------------------------------------


class ConnectorRegistry:
    """
    Manages connector instances and their implementations.

    Usage:
        registry = ConnectorRegistry()
        registry.register_type(GarminActivityConnector)
        registry.load_manifest(Path("orchestrator/config/connectors.yaml"))

        # Level 1 — AI context
        manifest = registry.lightweight_manifest()

        # Level 2 — on demand
        contract = registry.load_contract("garmin_fred")

        # Call
        result = registry.call("garmin_fred", "steps_today")
    """

    def __init__(self) -> None:
        self._instances: dict[str, ConnectorInstance] = {}
        self._types: dict[str, type[Connector]] = {}
        self._cache: dict[str, Connector] = {}
        # (instance_id, event_name) → list of handlers
        self._handlers: dict[tuple[str, str], list[Callable]] = {}

    def register_type(self, cls: type[Connector]) -> None:
        self._types[cls.__name__] = cls

    def add_instance(
        self,
        connector: type[Connector] | Connector,
        instance_id: str,
        name: str,
        owner: str | None = None,
        description: str = "",
        config: dict[str, Any] | None = None,
    ) -> ConnectorInstance:
        """
        Register a connector instance programmatically — no YAML required.

        *connector* may be:
          - a Connector subclass — instantiated lazily via *config* kwargs
          - an already-configured Connector instance — used as-is

        *config* is passed as **kwargs to the constructor on first call.
        *description* defaults to the class-level ``connector_description``
        when not supplied.
        """
        if isinstance(connector, type):
            cls = connector
        else:
            cls = type(connector)
            self._cache[instance_id] = connector

        self.register_type(cls)
        instance = ConnectorInstance(
            id=instance_id,
            name=name,
            description=description or cls.connector_description,
            type=cls.__name__,
            owner=owner,
            config=config or {},
        )
        self._instances[instance_id] = instance
        return instance

    def load_manifest(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for entry in data.get("connectors", []):
            self._load_entry(entry)

    def load_from_db(self, rows: list[dict]) -> None:
        """Load connector instances from PostgreSQL rows ({instance_id, config_json})."""
        import json

        for row in rows:
            try:
                entry = json.loads(row["config_json"])
                self._load_entry(entry)
            except Exception:
                continue

    def _load_entry(self, entry: dict) -> None:
        cls = self._types.get(entry["type"])
        fallback_desc = cls.connector_description if cls else ""
        instance = ConnectorInstance(
            id=entry["id"],
            name=entry["name"],
            description=entry.get("description") or fallback_desc,
            type=entry["type"],
            owner=entry.get("owner"),
            config=entry.get("config") or {},
        )
        self._instances[instance.id] = instance

    def lightweight_manifest(self) -> list[dict[str, Any]]:
        result = []
        for inst in self._instances.values():
            entry: dict[str, Any] = {
                "id": inst.id,
                "name": inst.name,
                "description": inst.description,
            }
            if inst.owner:
                entry["owner"] = inst.owner
            cls = self._types.get(inst.type)
            if cls is not None:
                ops = []
                for name, meta in cls._operations.items():
                    if meta.kind not in ("query", "command"):
                        continue
                    if meta.params:
                        params_str = ", ".join(meta.params.keys())
                        ops.append(f"{name}({params_str})")
                    else:
                        ops.append(name)
                if ops:
                    entry["operations"] = ops
            result.append(entry)
        return result

    def load_contract(self, instance_id: str) -> dict[str, Any]:
        connector = self._get_connector(instance_id)
        instance = self._instances[instance_id]
        contract = connector.contract()
        contract["instance_id"] = instance_id
        contract["name"] = instance.name
        if instance.owner:
            contract["owner"] = instance.owner
        return contract

    def call(
        self,
        instance_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> ConnectorResult:
        if instance_id not in self._instances:
            return ConnectorResult(ok=False, error="unavailable")
        try:
            connector = self._get_connector(instance_id)
        except PermissionError:
            return ConnectorResult(ok=False, error="auth")
        except Exception as exc:
            return ConnectorResult(ok=False, error=str(exc))
        return connector.call(operation, params)

    def get_instance(self, instance_id: str) -> ConnectorInstance:
        if instance_id not in self._instances:
            raise KeyError(f"unknown connector instance: {instance_id}")
        return self._instances[instance_id]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def subscribe(
        self,
        instance_id: str,
        event_name: str,
        handler: Callable[[Any], None],
    ) -> None:
        """Register *handler* to be called when *event_name* fires on *instance_id*."""
        key = (instance_id, event_name)
        self._handlers.setdefault(key, []).append(handler)

    def activate_events(self, instance_id: str) -> list[str]:
        """
        Start all event listeners declared on *instance_id*.

        For each @event method on the connector, calls
        `connector.method(callback=dispatch_fn)` where dispatch_fn
        routes payloads to all subscribed handlers.

        Returns the list of activated event names.
        The connector's implementation decides whether to use a thread,
        async loop, or polling internally — the framework is agnostic.
        """
        connector = self._get_connector(instance_id)
        activated: list[str] = []

        for name, meta in connector._operations.items():
            if meta.kind != "event":
                continue
            dispatch = self._make_dispatch(instance_id, name)
            method = getattr(connector, name)
            method(callback=dispatch)
            activated.append(name)

        return activated

    def polling_candidates(self) -> list[dict[str, str]]:
        """
        Return instances that have NO events declared — they need PULSE polling.

        Each entry: {"instance_id": ..., "query": ...} for every query
        operation on poll-only instances.
        """
        candidates: list[dict[str, str]] = []
        for instance_id in self._instances:
            try:
                connector = self._get_connector(instance_id)
            except Exception:
                continue
            has_events = any(m.kind == "event" for m in connector._operations.values())
            if not has_events:
                for name, meta in connector._operations.items():
                    if meta.kind == "query":
                        candidates.append({"instance_id": instance_id, "query": name})
        return candidates

    def _make_dispatch(self, instance_id: str, event_name: str) -> Callable[[Any], None]:
        def dispatch(payload: Any) -> None:
            for handler in self._handlers.get((instance_id, event_name), []):
                handler(payload)

        return dispatch

    def evict(self, instance_id: str) -> None:
        """Remove a cached connector so it is re-initialized on the next call.

        Call this after credentials are saved so the connector picks up the new file.
        """
        self._cache.pop(instance_id, None)

    # ------------------------------------------------------------------

    def _get_connector(self, instance_id: str) -> Connector:
        if instance_id not in self._cache:
            instance = self._instances[instance_id]
            cls = self._types.get(instance.type)
            if cls is None:
                raise KeyError(f"no implementation registered for type: {instance.type}")
            self._cache[instance_id] = cls(**instance.config)
        return self._cache[instance_id]
