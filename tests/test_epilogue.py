"""Abschluss-Epilog: genau einmal, aus echten Fakten, nie fuer Abbrueche.

K1-Entscheidung: kein Dauer-Banner bei abgeschlossenem Plan, aber ein einmaliger
Epilog mit dem, was noch offen ist. Wichtig: plan-level 'status' wird von keiner
Codezeile geschrieben — der Abschluss wird aus den Tasks berechnet.
"""

import json

import pytest
from plan_follow import coord_state, plan_hooks
from plan_follow.tools.base import _plan_path
from plan_follow.tools.state import STATE


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import plan_follow.tools.health as health

    monkeypatch.setattr(health, "_http_ok", lambda *a, **k: True)
    monkeypatch.setattr(health, "_mod_available", lambda *a, **k: True)


def make_plan(plan_id="p-epi", statuses=("completed", "completed", "completed")):
    tasks = {}
    for i, status in enumerate(statuses, start=1):
        tid = f"t{i}"
        tasks[tid] = {
            "id": tid,
            "status": status,
            "name": f"Task {i}",
            "files": [],
            "verify": "true",
            "depends_on": [],
            "review_profile": "none",
            "review_result": None,
        }
    plan = {
        "plan_id": plan_id,
        "goal": "Epilog-Ziel",
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": None,
        "tasks": tasks,
    }
    path = _plan_path(plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    STATE.active_plan = plan
    STATE.active_plan_id = plan_id
    return plan


class TestEpilogue:
    def test_completed_plan_announces_itself_once(self):
        make_plan()
        coord_state.register_session("s-1", plan_id="p-epi", goal="x")

        first = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)
        second = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert first is not None, "Abschluss muss einmal gemeldet werden"
        assert "abgeschlossen" in first.lower()
        assert "3/3" in first
        assert second is None, "Epilog darf sich nicht wiederholen"

    def test_epilogue_lists_open_items(self):
        make_plan()
        coord_state.register_session("s-1", plan_id="p-epi", goal="x")
        coord_state.acquire_lock("held.py", "s-1")

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is not None
        assert "offen" in out.lower()

    def test_aborted_plan_is_not_reported_completed(self):
        make_plan(statuses=("completed", "aborted", "aborted"))
        coord_state.register_session("s-1", plan_id="p-epi", goal="x")

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is not None
        assert "abgebrochen" in out.lower()
        assert "abgeschlossen" not in out.lower()

    def test_partial_plan_without_current_task_is_silent(self):
        make_plan(statuses=("completed", "pending", "pending"))
        coord_state.register_session("s-1", plan_id="p-epi", goal="x")

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is None, "1/3 ist kein Abschluss"
