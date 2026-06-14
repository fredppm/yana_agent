"""
Tests for pulse/config_loader.py — pure logic, no file system side effects outside tmp.
"""
from __future__ import annotations

import pytest
import yaml

from pulse.config_loader import (
    DeliverConfig,
    ObserveConfig,
    PulseTask,
    ScheduleConfig,
    TaskConfigError,
    load_tasks,
    remove_task,
    save_tasks,
    upsert_task,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_task(name: str = "test-task") -> PulseTask:
    return PulseTask(
        name=name,
        observe=ObserveConfig(source="gmail_fred", operation="search", params={"query": "is:unread"}),
        schedule=ScheduleConfig(mode="fixed", time="10:00", days="daily"),
        deliver=DeliverConfig(action="summarize", prompt="Summarize in PT-BR"),
    )


def _write_yaml(tmp_path, data: dict):
    f = tmp_path / "pulse-tasks.yaml"
    f.write_text(yaml.dump(data), encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# load_tasks
# ---------------------------------------------------------------------------


def test_load_tasks_missing_file_returns_empty(tmp_path):
    result = load_tasks(tmp_path / "nonexistent.yaml")
    assert result == []


def test_load_tasks_empty_file_returns_empty(tmp_path):
    f = tmp_path / "pulse-tasks.yaml"
    f.write_text("", encoding="utf-8")
    assert load_tasks(f) == []


def test_load_tasks_valid(tmp_path):
    data = {
        "tasks": [
            {
                "name": "newsletters",
                "observe": {"source": "gmail_fred", "operation": "search", "params": {"query": "newsletters"}},
                "schedule": {"mode": "fixed", "time": "10:00", "days": "daily"},
                "deliver": {"action": "summarize", "prompt": "Summarize"},
            }
        ]
    }
    f = _write_yaml(tmp_path, data)
    tasks = load_tasks(f)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.name == "newsletters"
    assert t.observe.source == "gmail_fred"
    assert t.observe.operation == "search"
    assert t.observe.params == {"query": "newsletters"}
    assert t.schedule.mode == "fixed"
    assert t.schedule.time == "10:00"
    assert t.schedule.days == "daily"
    assert t.deliver.action == "summarize"
    assert t.deliver.prompt == "Summarize"


def test_load_tasks_missing_name_raises(tmp_path):
    data = {"tasks": [{"observe": {"source": "x", "operation": "y"}, "schedule": {"mode": "fixed", "time": "10:00"}, "deliver": {"action": "notify"}}]}
    f = _write_yaml(tmp_path, data)
    with pytest.raises(TaskConfigError, match="missing required field: 'name'"):
        load_tasks(f)


def test_load_tasks_invalid_mode_raises(tmp_path):
    data = {
        "tasks": [
            {
                "name": "bad",
                "observe": {"source": "x", "operation": "y"},
                "schedule": {"mode": "adaptive", "time": "10:00"},
                "deliver": {"action": "notify"},
            }
        ]
    }
    f = _write_yaml(tmp_path, data)
    with pytest.raises(TaskConfigError, match="schedule.mode must be 'fixed'"):
        load_tasks(f)


def test_load_tasks_invalid_action_raises(tmp_path):
    data = {
        "tasks": [
            {
                "name": "bad",
                "observe": {"source": "x", "operation": "y"},
                "schedule": {"mode": "fixed", "time": "10:00"},
                "deliver": {"action": "teleport"},
            }
        ]
    }
    f = _write_yaml(tmp_path, data)
    with pytest.raises(TaskConfigError, match="deliver.action must be one of"):
        load_tasks(f)


def test_load_tasks_params_defaults_to_empty(tmp_path):
    data = {
        "tasks": [
            {
                "name": "no-params",
                "observe": {"source": "garmin", "operation": "activities"},
                "schedule": {"mode": "fixed", "time": "08:00"},
                "deliver": {"action": "notify"},
            }
        ]
    }
    f = _write_yaml(tmp_path, data)
    tasks = load_tasks(f)
    assert tasks[0].observe.params == {}


# ---------------------------------------------------------------------------
# save_tasks / round-trip
# ---------------------------------------------------------------------------


def test_save_and_reload_round_trip(tmp_path):
    task = _make_task()
    f = tmp_path / "pulse-tasks.yaml"
    save_tasks(f, [task])
    reloaded = load_tasks(f)
    assert len(reloaded) == 1
    assert reloaded[0].name == task.name
    assert reloaded[0].observe.source == task.observe.source
    assert reloaded[0].schedule.time == task.schedule.time
    assert reloaded[0].deliver.prompt == task.deliver.prompt


def test_save_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "nested" / "pulse-tasks.yaml"
    save_tasks(nested, [_make_task()])
    assert nested.exists()


# ---------------------------------------------------------------------------
# upsert_task
# ---------------------------------------------------------------------------


def test_upsert_inserts_new_task(tmp_path):
    f = tmp_path / "pulse-tasks.yaml"
    upsert_task(f, _make_task("a"))
    upsert_task(f, _make_task("b"))
    tasks = load_tasks(f)
    assert {t.name for t in tasks} == {"a", "b"}


def test_upsert_replaces_existing_task(tmp_path):
    f = tmp_path / "pulse-tasks.yaml"
    upsert_task(f, _make_task("x"))
    updated = PulseTask(
        name="x",
        observe=ObserveConfig(source="garmin", operation="activities", params={}),
        schedule=ScheduleConfig(mode="fixed", time="09:00", days="weekdays"),
        deliver=DeliverConfig(action="notify"),
    )
    upsert_task(f, updated)
    tasks = load_tasks(f)
    assert len(tasks) == 1
    assert tasks[0].observe.source == "garmin"
    assert tasks[0].schedule.time == "09:00"


# ---------------------------------------------------------------------------
# remove_task
# ---------------------------------------------------------------------------


def test_remove_existing_task(tmp_path):
    f = tmp_path / "pulse-tasks.yaml"
    upsert_task(f, _make_task("keep"))
    upsert_task(f, _make_task("remove-me"))
    removed = remove_task(f, "remove-me")
    assert removed is True
    tasks = load_tasks(f)
    assert [t.name for t in tasks] == ["keep"]


def test_remove_nonexistent_task_returns_false(tmp_path):
    f = tmp_path / "pulse-tasks.yaml"
    upsert_task(f, _make_task("only"))
    removed = remove_task(f, "ghost")
    assert removed is False
    assert len(load_tasks(f)) == 1
