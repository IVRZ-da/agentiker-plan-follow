"""Tests für plan_list / list_plans (v0.5.32).

Befund vor dem Fix: 82 Einträge, davon 80 leere 2-Byte-Dateien ``{}``, und ALLE
80 wurden als ``is_active: true`` gemeldet — weil ``data.get("plan_id")`` (None)
und ``STATE.active_plan_id`` (None) verglichen wurden (``None == None``).
Das Tool-Result war ~22k Zeichen ohne Erkenntniswert.
"""
import json

import pytest
from plan_follow import plan_core
from plan_follow.tools import status as status_mod
from plan_follow.tools.state import STATE


def _write(plan_id: str, tasks: int = 1, created: str = "2026-01-01T00:00:00+00:00",
           raw: str | None = None) -> None:
    path = plan_core.PLANS_DIR / f"{plan_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return
    payload = {
        "plan_id": plan_id,
        "goal": f"Goal {plan_id}",
        "created": created,
        "current_task": None,
        "tasks": {f"t{i}": {"id": f"t{i}", "status": "pending"} for i in range(tasks)},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def clean_state():
    STATE.active_plan_id = None
    STATE.active_plan = None
    yield
    STATE.active_plan_id = None
    STATE.active_plan = None


def test_empty_files_are_skipped():
    _write("leer", raw="{}")
    _write("ohne-plan-id", raw=json.dumps({"goal": "x"}))
    _write("ohne-tasks", raw=json.dumps({"plan_id": "ohne-tasks", "tasks": {}}))
    _write("echt", tasks=2)

    plans = status_mod.list_plans()
    assert [p["plan_id"] for p in plans] == ["echt"]


def test_no_is_active_without_active_plan():
    """Der historische Bug: leere Dateien wurden is_active=True gemeldet."""
    _write("leer-a", raw="{}")
    _write("leer-b", raw="{}")
    _write("echt", tasks=1)

    plans = status_mod.list_plans()
    assert all(p["is_active"] is False for p in plans)


def test_is_active_only_for_real_active_plan():
    _write("plan-a", tasks=1)
    _write("plan-b", tasks=1)
    STATE.active_plan_id = "plan-b"

    plans = status_mod.list_plans()
    active = [p for p in plans if p["is_active"]]
    assert [p["plan_id"] for p in active] == ["plan-b"]


def test_sorted_by_created_desc():
    _write("alt", created="2026-01-01T00:00:00+00:00")
    _write("neu", created="2026-11-10T00:00:00+00:00")
    _write("mitte", created="2026-06-01T00:00:00+00:00")

    ids = [p["plan_id"] for p in status_mod.list_plans()]
    assert ids == ["neu", "mitte", "alt"]


def test_plan_list_tool_limits_and_reports_has_more():
    for i in range(30):
        _write(f"plan-{i:02d}", created=f"2026-08-{i + 1:02d}T00:00:00+00:00")

    result = json.loads(status_mod.plan_list_tool({"limit": 5}))
    assert result["count"] == 5
    assert result["total"] == 30
    assert result["has_more"] is True
    assert len(result["plans"]) == 5


def test_plan_list_tool_output_stays_small_with_many_plans():
    """100 Pläne dürfen das Tool-Result nicht aufblähen."""
    for i in range(100):
        _write(f"bulk-{i:03d}", created=f"2026-07-{(i % 28) + 1:02d}T00:00:00+00:00")

    raw = status_mod.plan_list_tool({})
    result = json.loads(raw)
    assert result["total"] == 100
    assert result["count"] == 20
    assert len(raw) < 4000, f"Tool-Result zu gross: {len(raw)} Zeichen"


def test_plan_list_tool_default_limit_is_20():
    for i in range(25):
        _write(f"d-{i:02d}")
    result = json.loads(status_mod.plan_list_tool({}))
    assert result["count"] == 20
    assert result["has_more"] is True


def test_invalid_limit_falls_back_to_default():
    for i in range(3):
        _write(f"x-{i}")
    result = json.loads(status_mod.plan_list_tool({"limit": "kaputt"}))
    assert result["count"] == 3
    assert result["has_more"] is False
