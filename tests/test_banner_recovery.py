"""Banner-Recovery im pre_llm_call-Hook.

Zwei Fehler, die dieser Test verhindert:
1. Nach einem Hermes-Restart war der In-Memory-Cache leer -> der Task-Banner
   erschien erst, wenn irgendein plan_-Tool aufgerufen wurde (der Skill behauptete
   "Banner in JEDEM Turn" + "Disk-Recovery nach /new").
2. Die naive Loesung "einfach von Disk laden" leakt im Gateway-Prozess Plaene
   zwischen Sessions (STATE ist prozessglobal, ein Prozess bedient viele Sessions)
   und lockt fremde Task-Dateien mit.
"""
import json

import pytest
from plan_follow import coord_state, plan_core, plan_hooks
from plan_follow.tools.state import STATE


@pytest.fixture
def plan_on_disk():
    """Ein aktiver Plan mit current_task im (isolierten) PLANS_DIR."""
    plan = {
        "plan_id": "recovery-test-plan",
        "goal": "Banner-Recovery-Test",
        "created": "2026-11-10T20:00:00+00:00",
        "current_task": "t1",
        "tasks": {
            "t1": {"id": "t1", "name": "T1", "status": "in_progress", "files": [], "depends_on": []},
        },
    }
    path = plan_core.PLANS_DIR / f"{plan['plan_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (plan_core.PLANS_DIR / "plans_index.json").write_text(
        json.dumps({"active_plan_id": plan["plan_id"], "active_goal": plan["goal"]}),
        encoding="utf-8",
    )
    STATE.active_plan = None
    STATE.active_plan_id = None
    plan_hooks._recovered_sessions.clear()
    return plan


def test_no_recovery_mid_turn(plan_on_disk):
    """is_first_turn=False -> keine Recovery, keine Datei-Zugriffe."""
    plan_hooks._try_session_recovery({"session_id": "s1", "is_first_turn": False})
    assert STATE.active_plan is None


def test_recovery_on_first_turn(plan_on_disk):
    plan_hooks._try_session_recovery({"session_id": "s1", "is_first_turn": True})
    assert STATE.active_plan is not None
    assert STATE.active_plan["plan_id"] == "recovery-test-plan"


def test_recovery_blocked_for_foreign_session(plan_on_disk):
    """Session gehoert zu einem anderen Plan -> nicht adoptieren (kein Leak)."""
    coord_state.register_session("s-foreign", plan_id="ein-anderer-plan", goal="x")
    plan_hooks._try_session_recovery({"session_id": "s-foreign", "is_first_turn": True})
    assert STATE.active_plan is None, "Fremder Plan darf nicht uebernommen werden"


def test_recovery_allowed_for_own_session(plan_on_disk):
    coord_state.register_session("s-own", plan_id="recovery-test-plan", goal="x")
    plan_hooks._try_session_recovery({"session_id": "s-own", "is_first_turn": True})
    assert STATE.active_plan is not None
    assert STATE.active_plan["plan_id"] == "recovery-test-plan"


def test_recovery_runs_only_once_per_session(plan_on_disk, monkeypatch):
    calls = {"n": 0}
    real = plan_hooks._try_session_recovery

    def counting(kwargs):
        calls["n"] += 1
        return real(kwargs)

    monkeypatch.setattr(plan_hooks, "_try_session_recovery", counting)

    plan_hooks.on_pre_llm_call(session_id="s-once", is_first_turn=True)
    first = STATE.active_plan
    assert first is not None
    assert calls["n"] == 1

    # STATE leeren: ohne "einmal pro Session" wuerde erneut von Disk geladen
    STATE.active_plan = None
    STATE.active_plan_id = None
    plan_hooks.on_pre_llm_call(session_id="s-once", is_first_turn=True)
    assert STATE.active_plan is None, "Recovery darf pro Session nur einmal laufen"


def test_session_end_clears_recovery_marker(plan_on_disk):
    plan_hooks._recovered_sessions.add("s-clear")
    plan_hooks.on_session_end(session_id="s-clear")
    assert "s-clear" not in plan_hooks._recovered_sessions


def test_banner_still_uses_cache_and_skips_foreign_plan(plan_on_disk):
    """Kernaussage: der Hook zeigt nie einen Plan, den die Session nicht besitzt."""
    coord_state.register_session("s-intruder", plan_id="anderer-plan", goal="y")
    banner = plan_hooks.on_pre_llm_call(session_id="s-intruder", is_first_turn=True)
    assert banner is None or "recovery-test-plan" not in banner
