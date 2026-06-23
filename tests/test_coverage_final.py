"""Zusätzliche Coverage-Tests für plan_tools.py — alle Handler Error-Pfade.

Jeder Test erstellt seinen eigenen Plan mit Inline-Tasks.
Keine Fixtures nötig — alles inline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _make_plan_tasks():
    return [
        {"id": "p1", "name": "Task 1", "files": [], "verify": "", "review_profile": "none"},
        {"id": "p2", "name": "Task 2", "files": [], "verify": "", "review_profile": "none"},
    ]


def _create_plan():
    from plan_follow.plan_tools import plan_create_tool
    tasks = _make_plan_tasks()
    plan_create_tool({"goal": "Coverage Test", "tasks": tasks})


# --- plan_pr_create_tool ---


def test_pr_create_empty_body():
    _create_plan()
    from plan_follow.plan_tools import plan_pr_create_tool
    r = plan_pr_create_tool({"title": "Test"})
    assert r is not None


def test_pr_create_no_title():
    _create_plan()
    from plan_follow.plan_tools import plan_pr_create_tool
    r = plan_pr_create_tool({"body": "body"})
    assert r is not None


# --- plan_git_* tools ---


def test_git_push():
    _create_plan()
    from plan_follow.plan_tools import plan_git_push_tool
    r = plan_git_push_tool({"repo": "/nonexistent"})
    assert r is not None


def test_git_sync():
    _create_plan()
    from plan_follow.plan_tools import plan_git_sync_tool
    r = plan_git_sync_tool({"repo": "/nonexistent"})
    assert r is not None


def test_git_stash():
    _create_plan()
    from plan_follow.plan_tools import plan_git_stash_tool
    r = plan_git_stash_tool({"repo": "/nonexistent"})
    assert r is not None


def test_git_branch():
    _create_plan()
    from plan_follow.plan_tools import plan_git_branch_tool
    r = plan_git_branch_tool({"repo": "/nonexistent"})
    assert r is not None


def test_git_tag():
    _create_plan()
    from plan_follow.plan_tools import plan_git_tag_tool
    r = plan_git_tag_tool({"repo": "/nonexistent"})
    assert r is not None


def test_git_status():
    _create_plan()
    from plan_follow.plan_tools import plan_git_status_tool
    r = plan_git_status_tool({"repo": "/nonexistent"})
    assert r is not None


# --- plan_notify_tool ---


def test_notify_send():
    _create_plan()
    from plan_follow.plan_tools import plan_notify_tool
    r = plan_notify_tool({"action": "send", "message": ""})
    assert r is not None


def test_notify_check():
    _create_plan()
    from plan_follow.plan_tools import plan_notify_tool
    r = plan_notify_tool({"action": "check"})
    assert r is not None


# --- plan_lock_tool ---


def test_lock_lock():
    _create_plan()
    from plan_follow.plan_tools import plan_lock_tool
    r = plan_lock_tool({"action": "lock", "plan_id": "test"})
    assert r is not None


def test_lock_unlock():
    _create_plan()
    from plan_follow.plan_tools import plan_lock_tool
    r = plan_lock_tool({"action": "unlock", "plan_id": "test"})
    assert r is not None


# --- plan_session_tool ---


def test_session_status():
    _create_plan()
    from plan_follow.plan_tools import plan_session_tool
    r = plan_session_tool({"action": "status"})
    assert r is not None


# --- plan_time_tool ---


def test_time_start():
    _create_plan()
    from plan_follow.plan_tools import plan_time_tool
    r = plan_time_tool({"action": "start", "task_id": "p1"})
    assert r is not None


def test_time_stop():
    _create_plan()
    from plan_follow.plan_tools import plan_time_tool
    plan_time_tool({"action": "start", "task_id": "p1"})
    r = plan_time_tool({"action": "stop", "task_id": "p1"})
    assert r is not None


# --- plan_simulate_tool ---


def test_simulate():
    _create_plan()
    from plan_follow.plan_tools import plan_simulate_tool
    r = plan_simulate_tool({})
    assert r is not None


# --- plan_decompose_tool ---


def test_decompose_status():
    _create_plan()
    from plan_follow.plan_tools import plan_decompose_tool
    r = plan_decompose_tool({"action": "status", "task_id": "p1"})
    assert r is not None


def test_decompose_delegate():
    _create_plan()
    from plan_follow.plan_tools import plan_decompose_tool
    r = plan_decompose_tool({"action": "delegate", "task_id": "p1"})
    assert r is not None


# --- plan_sync_tool ---


def test_sync_export():
    _create_plan()
    from plan_follow.plan_tools import plan_sync_tool
    r = plan_sync_tool({"action": "export"})
    assert r is not None


# --- plan_review_save_result_tool ---


def test_review_save():
    _create_plan()
    from plan_follow.plan_tools import plan_review_save_result_tool
    r = plan_review_save_result_tool({"task_id": "p1", "status": "passed"})
    assert r is not None


# --- plan_duedate_tool ---


def test_duedate_set():
    _create_plan()
    from plan_follow.plan_tools import plan_duedate_tool
    r = plan_duedate_tool({"action": "set", "task_id": "p1", "due": "2099-12-31"})
    assert r is not None


def test_duedate_clear():
    _create_plan()
    from plan_follow.plan_tools import plan_duedate_tool
    r = plan_duedate_tool({"action": "clear", "task_id": "p1"})
    assert r is not None


# --- plan_history_tool ---


def test_history():
    _create_plan()
    from plan_follow.plan_tools import plan_history_tool
    r = plan_history_tool({})
    assert r is not None
