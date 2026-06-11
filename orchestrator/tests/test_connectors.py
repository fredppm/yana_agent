"""Tests for the connector framework (base.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors import (
    Connector,
    ConnectorResult,
    command,
    event,
    query,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class SimpleConnector(Connector):

    @query(
        description="Returns a number",
        returns={"type": "number", "unit": "steps/day"},
    )
    def get_steps(self) -> int:
        return 1234

    @query(
        description="Returns steps for a given day offset",
        params={"days_ago": {"type": "number", "required": False}},
        returns={"type": "number", "unit": "steps/day"},
    )
    def get_steps_for_day(self, days_ago: int = 0) -> int:
        return 1000 + days_ago

    @command(
        description="Toggle something on/off",
        params={"state": {"type": "boolean"}},
        returns={"type": "boolean"},
    )
    def set_state(self, state: bool) -> bool:
        return state

    @event(
        description="Fires when a new record is set",
        schema={"type": "object"},
    )
    def on_new_record(self, callback) -> None:  # type: ignore[type-arg]
        pass


class ErrorConnector(Connector):

    @query(description="Raises TimeoutError", returns={"type": "number"})
    def timeout_op(self) -> int:
        raise TimeoutError

    @query(description="Raises PermissionError", returns={"type": "number"})
    def auth_op(self) -> int:
        raise PermissionError

    @query(description="Raises generic error", returns={"type": "number"})
    def crash_op(self) -> int:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Operation discovery
# ---------------------------------------------------------------------------

def test_operations_collected():
    assert "get_steps" in SimpleConnector._operations
    assert "set_state" in SimpleConnector._operations
    assert "on_new_record" in SimpleConnector._operations


def test_operation_kinds():
    ops = SimpleConnector._operations
    assert ops["get_steps"].kind == "query"
    assert ops["set_state"].kind == "command"
    assert ops["on_new_record"].kind == "event"


def test_returns_schema():
    meta = SimpleConnector._operations["get_steps"]
    assert meta.returns is not None
    assert meta.returns.type == "number"
    assert meta.returns.unit == "steps/day"


def test_params_schema():
    meta = SimpleConnector._operations["set_state"]
    assert "state" in meta.params
    assert meta.params["state"].type == "boolean"
    assert meta.params["state"].required is True


# ---------------------------------------------------------------------------
# call() — happy paths
# ---------------------------------------------------------------------------

def test_call_query_no_params():
    c = SimpleConnector()
    result = c.call("get_steps")
    assert result.ok is True
    assert result.data == 1234
    assert result.error is None


def test_call_query_optional_param_default():
    c = SimpleConnector()
    result = c.call("get_steps_for_day")
    assert result.ok is True
    assert result.data == 1000


def test_call_query_with_param():
    c = SimpleConnector()
    result = c.call("get_steps_for_day", {"days_ago": 3})
    assert result.ok is True
    assert result.data == 1003


def test_call_command():
    c = SimpleConnector()
    result = c.call("set_state", {"state": True})
    assert result.ok is True
    assert result.data is True


# ---------------------------------------------------------------------------
# call() — validation errors
# ---------------------------------------------------------------------------

def test_call_unknown_operation():
    c = SimpleConnector()
    result = c.call("nonexistent")
    assert result.ok is False
    assert result.error == "validation_error"


def test_call_event_operation_rejected():
    c = SimpleConnector()
    result = c.call("on_new_record")
    assert result.ok is False
    assert result.error == "validation_error"


def test_call_missing_required_param():
    c = SimpleConnector()
    result = c.call("set_state", {})
    assert result.ok is False
    assert result.error == "validation_error"


def test_call_wrong_param_type():
    c = SimpleConnector()
    result = c.call("set_state", {"state": "yes"})
    assert result.ok is False
    assert result.error == "validation_error"


# ---------------------------------------------------------------------------
# call() — implementation errors mapped to envelope
# ---------------------------------------------------------------------------

def test_call_timeout_error():
    c = ErrorConnector()
    result = c.call("timeout_op")
    assert result.ok is False
    assert result.error == "timeout"


def test_call_auth_error():
    c = ErrorConnector()
    result = c.call("auth_op")
    assert result.ok is False
    assert result.error == "auth"


def test_call_generic_error():
    c = ErrorConnector()
    result = c.call("crash_op")
    assert result.ok is False
    assert result.error == "unavailable"


# ---------------------------------------------------------------------------
# contract()
# ---------------------------------------------------------------------------

def test_contract_structure():
    c = SimpleConnector()
    contract = c.contract()
    assert contract["type"] == "SimpleConnector"
    assert isinstance(contract["queries"], list)
    assert isinstance(contract["commands"], list)
    assert "events" in contract


def test_contract_queries_have_description_and_returns():
    c = SimpleConnector()
    queries = {q["name"]: q for q in c.contract()["queries"]}
    assert "get_steps" in queries
    assert queries["get_steps"]["description"] == "Returns a number"
    assert queries["get_steps"]["returns"]["type"] == "number"
    assert queries["get_steps"]["returns"]["unit"] == "steps/day"


def test_contract_no_events_key_when_empty():
    class NoEventConnector(Connector):
        @query(description="x", returns={"type": "string"})
        def do_x(self) -> str:
            return "x"

    c = NoEventConnector()
    assert "events" not in c.contract()
