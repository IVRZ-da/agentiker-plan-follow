"""Der Banner muss den Zustand DER SESSION zeigen, nicht den Prozess-Cache.

Beobachtet am 11.11.2026: der Banner meldete 'CURRENT TASK: t1 — 1/15', waehrend
die Plan-Datei 14/14 completed und current_task=None war. Ursache: STATE ist
prozessglobal und wird nie gegen die Platte geprueft (tools/task.py:163 ->
tools/base.py:262).

Diese Tests sind absichtlich rot, bis get_current_task_fresh(session_id) den
Disk-Stand liest UND die Besitzpruefung respektiert.
"""

import json

import pytest
from plan_follow import coord_state, plan_hooks
from plan_follow.tools.base import _plan_path
from plan_follow.tools.state import STATE


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Renderpfad darf keine echten HTTP-Checks ausloesen."""
    import plan_follow.tools.health as health

    monkeypatch.setattr(health, "_http_ok", lambda *a, **k: True)
    monkeypatch.setattr(health, "_mod_available", lambda *a, **k: True)


def make_plan(plan_id="p-fresh", n=3, completed=0, current="t1", aborted=0):
    tasks = {}
    for i in range(1, n + 1):
        tid = f"t{i}"
        if i <= aborted:
            status = "aborted"
        elif i <= completed:
            status = "completed"
        else:
            status = "pending"
        tasks[tid] = {
            "id": tid,
            "status": status,
            "name": f"Task {i}",
            "files": [f"file{i}.py"],
            "verify": "true",
            "depends_on": [],
            "review_profile": "none",
            "review_result": None,
        }
    return {
        "plan_id": plan_id,
        "goal": "Testziel",
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": current,
        "tasks": tasks,
    }


def write_plan(plan):
    path = _plan_path(plan["plan_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def activate(plan):
    STATE.active_plan = plan
    STATE.active_plan_id = plan["plan_id"]


class TestSessionIsolation:
    def test_foreign_session_sees_no_banner(self):
        """Gateway-Prozess: Session B darf den Plan von Session A nicht sehen."""
        plan = make_plan()
        write_plan(plan)
        activate(plan)
        coord_state.register_session("s-owner", plan_id=plan["plan_id"], goal="owner")
        coord_state.register_session("s-other", plan_id="", goal="other")

        out = plan_hooks.on_pre_llm_call(session_id="s-other", is_first_turn=False)

        assert out is None, "Fremde Session darf keinen fremden Plan im Banner sehen"

    def test_owning_session_sees_banner(self):
        """Gegenprobe: die besitzende Session bekommt ihren Banner."""
        plan = make_plan()
        write_plan(plan)
        activate(plan)
        coord_state.register_session("s-owner", plan_id=plan["plan_id"], goal="owner")

        out = plan_hooks.on_pre_llm_call(session_id="s-owner", is_first_turn=False)

        assert out is not None
        assert "t1" in out


class TestDiskWins:
    def test_completed_on_disk_suppresses_task_banner(self):
        """Datei sagt 3/3 fertig -> kein 'CURRENT TASK t1' mehr aus dem Cache."""
        plan = make_plan(completed=0, current="t1")
        write_plan(plan)
        activate(plan)
        coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")

        # Externer Abschluss (execute_code, zweiter Prozess, Handedit)
        write_plan(make_plan(completed=3, current=None))

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert "CURRENT TASK" not in (out or ""), f"Banner zeigt veralteten Task: {out!r}"

    def test_progress_comes_from_disk(self):
        """Datei ist weiter fortgeschritten -> Banner zeigt t3, nicht t1."""
        plan = make_plan(completed=0, current="t1")
        write_plan(plan)
        activate(plan)
        coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")

        write_plan(make_plan(completed=2, current="t3"))

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is not None
        assert "CURRENT TASK: t3" in out, f"Banner zeigt nicht den Disk-Stand: {out!r}"

    def test_missing_plan_file_drops_cache(self):
        """Geloeschter Plan darf nicht aus dem Cache weiterleben."""
        plan = make_plan()
        path = write_plan(plan)
        activate(plan)
        coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")

        path.unlink()

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is None
        assert STATE.active_plan is None
