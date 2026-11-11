"""Locks muessen im Lifecycle freigegeben werden — und standardmaessig aus sein.

Beobachtet: nach '14/14 completed' blieben Locks stehen, weil on_pre_llm_call bei
current_task=None frueh returnt (plan_hooks.py:735-737) und Lock-Release nur bei
Task-Wechsel laeuft (plan_hooks.py:63-66). Der Banner zeigte danach 'Eigene Locks'
auf einem abgeschlossenen Plan.
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


def make_plan(plan_id="p-lock", n=3, completed=0, current="t1"):
    tasks = {}
    for i in range(1, n + 1):
        tid = f"t{i}"
        tasks[tid] = {
            "id": tid,
            "status": "completed" if i <= completed else "pending",
            "name": f"Task {i}",
            "files": [f"file{i}.py"],
            "verify": "true",
            "depends_on": [],
            "review_profile": "none",
            "review_result": None,
        }
    return {
        "plan_id": plan_id,
        "goal": "Lock-Ziel",
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": current,
        "tasks": tasks,
    }


def activate(plan):
    path = _plan_path(plan["plan_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    STATE.active_plan = plan
    STATE.active_plan_id = plan["plan_id"]


class TestLocksOffByDefault:
    def test_no_auto_lock_without_flag(self, monkeypatch):
        monkeypatch.delenv("PLAN_FOLLOW_LOCKS", raising=False)
        plan = make_plan()
        activate(plan)
        coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is not None
        assert coord_state.get_locks() == {}, "Ohne Flag darf nichts gelockt werden"
        assert "🔒" not in out, "Ohne Flag kein Lock-Block im Banner"


class TestReleaseOnLifecycle:
    def test_completed_plan_releases_all_locks(self, monkeypatch):
        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        plan = make_plan(completed=3, current=None)
        activate(plan)
        coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")
        for i in (1, 2, 3):
            coord_state.acquire_lock(f"file{i}.py", "s-1")
        assert len(coord_state.get_locks()) == 3

        plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert coord_state.get_locks() == {}, "Abschluss muss die Locks freigeben"

    def test_completed_plan_clears_plan_id_from_session(self, monkeypatch):
        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        plan = make_plan(completed=3, current=None)
        activate(plan)
        coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")

        plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        session = coord_state.get_session("s-1")
        assert session is not None, "Session-Eintrag bleibt bestehen"
        assert not session.get("plan_id"), "Abgeschlossener Plan darf nicht als aktiv gelten"


class TestStaleRelease:
    def test_young_owner_session_is_not_released(self, monkeypatch):
        """Ein 45-Minuten-Lock einer aktiven Session darf NICHT freigegeben werden."""
        import datetime as _dt

        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        from plan_follow import coord_state as cs

        cs.register_session("s-owner", plan_id="p-other", goal="y")
        cs.acquire_lock("held.py", "s-owner")

        # Lock 45 Minuten alt machen
        locks = cs.get_locks()
        old = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=45)).isoformat()
        locks["held.py"]["since"] = old
        locks["held.py"]["heartbeat"] = old
        cs._atomic_write(cs.LOCKS_FILE, locks)

        cs.cleanup_stale_locks(30)

        assert "held.py" in cs.get_locks(), "Aktive Owner-Session schuetzt ihren Lock"


class TestConcurrency:
    """Zwei Prozesse duerfen sich keine Locks wegnehmen (State-Lock, T4b)."""

    def test_parallel_acquires_do_not_lose_locks(self):
        import multiprocessing as mp

        def worker(prefix: str, count: int) -> None:
            from plan_follow import coord_state

            for i in range(count):
                coord_state.acquire_lock(f"{prefix}-{i}.py", f"{prefix}-session")

        procs = [
            mp.Process(target=worker, args=(f"p{n}", 40)) for n in range(2)
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=60)

        from plan_follow import coord_state

        locks = coord_state.get_locks()
        missing = [
            f"p{n}-{i}.py"
            for n in range(2)
            for i in range(40)
            if f"p{n}-{i}.py" not in locks
        ]
        assert missing == [], f"Locks verloren: {missing[:5]} ({len(missing)} fehlen)"
