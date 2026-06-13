"""
Integration tests for GoogleTasksConnector.

These tests hit the real Google Tasks API. On first run with no token,
the connector opens a browser for OAuth consent automatically.

Run:
    pytest -m integration -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import connectors_setup


@pytest.fixture(scope="module")
def registry():
    return connectors_setup.build_registry()


@pytest.mark.integration
def test_list_tasklists_returns_list(registry):
    result = registry.call("tasks_fred", "list_tasklists")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_list_tasklists_fields_present(registry):
    result = registry.call("tasks_fred", "list_tasklists")
    assert result.ok is True
    for tl in result.data:
        assert "id" in tl
        assert "title" in tl


@pytest.mark.integration
def test_list_tasks_default_list(registry):
    result = registry.call("tasks_fred", "list_tasks")
    assert result.ok is True, f"call failed: {result.error}"
    assert isinstance(result.data, list)


@pytest.mark.integration
def test_list_tasks_fields_present(registry):
    result = registry.call("tasks_fred", "list_tasks")
    assert result.ok is True
    for task in result.data:
        assert "id" in task
        assert "title" in task
        assert "status" in task


@pytest.mark.integration
def test_create_complete_delete_task(registry):
    # create
    create_result = registry.call(
        "tasks_fred",
        "create_task",
        {"title": "YANA integration test task — safe to delete"},
    )
    assert create_result.ok is True, f"create failed: {create_result.error}"
    task = create_result.data
    assert task.get("id")
    assert task["title"] == "YANA integration test task — safe to delete"

    task_id = task["id"]

    # complete
    complete_result = registry.call("tasks_fred", "complete_task", {"task_id": task_id})
    assert complete_result.ok is True, f"complete failed: {complete_result.error}"
    assert complete_result.data["status"] == "completed"

    # delete
    delete_result = registry.call("tasks_fred", "delete_task", {"task_id": task_id})
    assert delete_result.ok is True, f"delete failed: {delete_result.error}"
    assert delete_result.data is True


@pytest.mark.integration
def test_create_task_with_due_date(registry):
    create_result = registry.call(
        "tasks_fred",
        "create_task",
        {
            "title": "YANA integration test task with due — safe to delete",
            "due_iso": "2099-12-31",
            "notes": "Created by integration test",
        },
    )
    assert create_result.ok is True, f"create failed: {create_result.error}"
    task = create_result.data
    task_id = task["id"]
    assert task.get("due") is not None

    # cleanup
    registry.call("tasks_fred", "delete_task", {"task_id": task_id})


@pytest.mark.integration
def test_get_connector_contract_has_expected_ops(registry):
    contract = registry.load_contract("tasks_fred")
    assert "queries" in contract
    assert "commands" in contract
    query_names = {q["name"] for q in contract["queries"]}
    command_names = {c["name"] for c in contract["commands"]}
    assert "list_tasks" in query_names
    assert "list_tasklists" in query_names
    assert "create_task" in command_names
    assert "complete_task" in command_names
    assert "update_task" in command_names
    assert "delete_task" in command_names
