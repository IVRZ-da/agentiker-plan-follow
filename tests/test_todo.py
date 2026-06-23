"""Tests für plan_todo.py — Direkte Tests der internen Funktionen + Tool-Handler."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def test_get_todo_list_empty():
    from plan_follow.plan_todo import _get_todo_list
    result = _get_todo_list()
    assert isinstance(result, list)


def test_get_todo_list_with_plan():
    from plan_follow.plan_tools import plan_create_tool
    plan_create_tool({"goal": "Test", "tasks": [{"id":"p1","name":"T1"}]})
    from plan_follow.plan_todo import _get_todo_list
    result = _get_todo_list()
    assert len(result) >= 1


def test_apply_write():
    from plan_follow.plan_tools import plan_create_tool
    plan_create_tool({"goal": "Test", "tasks": [{"id":"p1","name":"T1"}]})
    from plan_follow.plan_todo import _apply_write, _get_todo_list
    _get_todo_list()
    result = _apply_write([{"id":"p1","status":"completed"}])
    assert result is not None


def test_build_summary():
    from plan_follow.plan_todo import _build_summary
    r = _build_summary([{"status":"completed"},{"status":"pending"}])
    assert r.get("total") == 2


def test_todo_tool_list():
    from plan_follow.plan_todo import plan_todo_tool
    r = plan_todo_tool({})
    assert r is not None


def test_todo_tool_unknown_action():
    from plan_follow.plan_todo import plan_todo_tool
    r = plan_todo_tool({"action": "xyz_invalid"})
    assert r is not None


def test_todo_tool_add():
    from plan_follow.plan_todo import plan_todo_tool
    r = plan_todo_tool({"action": "add", "content": "New todo"})
    assert r is not None


def test_todo_tool_add_no_content():
    from plan_follow.plan_todo import plan_todo_tool
    r = plan_todo_tool({"action": "add"})
    assert r is not None
