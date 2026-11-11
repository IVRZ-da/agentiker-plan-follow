"""Der Banner muss sagen, woher er seinen Stand hat — und darf nicht wiederholen.

Ohne Provenienz war nicht erkennbar, dass 'CURRENT TASK t1, 1/15' aus einem
1,5 Stunden alten Prozess-Cache kam. Zusaetzlich wurde dieselbe Drift-Warnung in
jedem Turn erneut gerendert.
"""

import json

import pytest
from plan_follow import coord_state, plan_core, plan_hooks
from plan_follow.tools.base import _plan_path
from plan_follow.tools.state import STATE


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import plan_follow.tools.health as health

    monkeypatch.setattr(health, "_http_ok", lambda *a, **k: True)
    monkeypatch.setattr(health, "_mod_available", lambda *a, **k: True)


def _active_plan():
    tasks = {
        "t1": {
            "id": "t1",
            "status": "in_progress",
            "name": "Erster Task mit einem ziemlich langen Namen fuer den Banner",
            "files": ["some/very/long/path/to/a/file.py", "another/long/path.py"],
            "verify": "true",
            "depends_on": [],
            "review_profile": "none",
            "review_result": None,
        }
    }
    plan = {
        "plan_id": "p-prov",
        "goal": "Provenienz",
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": "t1",
        "tasks": tasks,
    }
    path = _plan_path(plan["plan_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    STATE.active_plan = plan
    STATE.active_plan_id = plan["plan_id"]
    coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")
    return plan


class TestProvenance:
    def test_banner_states_source_and_time(self):
        _active_plan()

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert out is not None
        assert "Stand:" in out, "Banner muss den Stand nennen"
        assert "Quelle:" in out, "Banner muss die Quelle nennen (Disk vs. Cache)"

    def test_banner_mentions_disk_mtime(self):
        _active_plan()

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert "Disk" in out


class TestDriftNoise:
    def test_drift_warning_rendered_once_per_change(self):
        _active_plan()
        plan_core.record_drift_warning("patch ausserhalb task.files")

        first = plan_hooks._build_drift_banner()
        second = plan_hooks._build_drift_banner()

        assert first, "Erste Anzeige muss die Drift zeigen"
        assert second == [], "Gleiche Drift darf nicht erneut gerendert werden"


class TestLayout:
    def test_banner_lines_have_uniform_width(self):
        _active_plan()

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)
        assert out is not None

        box = [ln.replace("[PLAN] ", "", 1) for ln in out.splitlines() if "║" in ln]
        assert box, "Banner muss eine Box enthalten"
        widths = {len(ln) for ln in box}
        assert len(widths) == 1, f"Zeilen sind unterschiedlich breit: {sorted(widths)}"

    def test_banner_stays_compact(self):
        _active_plan()

        out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

        assert len(out) < 1500, f"Banner zu gross: {len(out)} Zeichen"
