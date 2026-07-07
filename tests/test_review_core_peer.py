"""Tests für plan_review.py + plan_peer_review.py + plan_core.py fehlende Pfade."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ─── plan_core.py ─────────────────────────────────────────────


def test_core_delete_plan_nonexistent():
    from plan_follow.plan_core import delete_plan
    r = delete_plan("nonexistent-plan-xyz")
    assert r is not None


def test_core_delete_created_plan():
    from plan_follow.plan_core import delete_plan
    from plan_follow.plan_tools import plan_create_tool
    plan_create_tool({"goal": "DeleteMe", "tasks": [{"id":"d1","name":"D1"}]})
    r = delete_plan("deleteme")
    assert r is not None


# ─── plan_review.py ───────────────────────────────────────────


def test_review_dispatch_quick():
    from plan_follow.plan_review import dispatch_review
    task = {"id": "p1", "name": "T1", "files": ["test.py"]}
    r = dispatch_review("unit-test", task, depth="quick")
    assert r is not None
    assert r.get("depth") == "quick"


def test_review_dispatch_deep():
    from plan_follow.plan_review import dispatch_review
    task = {"id": "p1", "name": "T1", "files": ["test.py"]}
    r = dispatch_review("unit-test", task, depth="deep")
    assert r is not None
    assert r.get("depth") == "deep"


def test_review_dispatch_unknown_profile():
    from plan_follow.plan_review import dispatch_review
    task = {"id": "p1", "name": "T1", "files": ["test.py"]}
    r = dispatch_review("nonexistent-profile-xyz", task)
    assert r is not None


# ─── plan_peer_review.py ──────────────────────────────────────


def test_peer_apply_findings_empty():
    from plan_follow.plan_peer_review import apply_findings
    plan = {"tasks": {"p1": {"id":"p1","name":"T1","verify":"echo ok"}}}
    r = apply_findings(plan, [])
    assert r is not None


def test_peer_apply_findings_meaningless_verify():
    from plan_follow.plan_peer_review import apply_findings
    plan = {"tasks": {"p1": {"id":"p1","name":"T1","verify":"echo 'ok'"}}}
    r = apply_findings(plan, [{"task_id":"p1","check":"verify","severity":"critical","fix":{"verify":"pytest"}}])
    assert r is not None


def test_peer_run_review_basic():
    from plan_follow.plan_peer_review import run_peer_review
    plan = {"plan_id":"test","goal":"Test","tasks":{"p1":{"id":"p1","name":"T1","verify":"echo ok"}}}
    r = run_peer_review(plan)
    assert r is not None
    assert isinstance(r, list)
