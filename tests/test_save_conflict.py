"""Der Schreibpfad muss Konflikte erkennen und atomar schreiben.

tools/base.py:213 _save_plan prueft nichts gegen die Platte: es macht .bak und
schreibt. Zwei Prozesse (Gateway-Session + CLI/Subagent) ueberschreiben sich
gegenseitig — der neueste Stand geht verloren. Zusaetzlich kann ein Handler mit
altem Dict einen archivierten Plan wiederbeleben.
"""

import json
import os

import pytest
from plan_follow import plan_core
from plan_follow.tools import base as tools_base
from plan_follow.tools.base import _plan_path


def make_plan(plan_id="p-save", goal="Original"):
    return {
        "plan_id": plan_id,
        "goal": goal,
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": "t1",
        "tasks": {
            "t1": {
                "id": "t1",
                "status": "in_progress",
                "name": "Task 1",
                "files": [],
                "verify": "true",
                "depends_on": [],
                "review_profile": "none",
                "review_result": None,
            }
        },
    }


class TestConflictDetection:
    def test_foreign_change_is_not_overwritten(self):
        plan = make_plan()
        path = _plan_path(plan["plan_id"])
        tools_base._save_plan(plan)

        # Fremder Prozess schreibt dazwischen
        foreign = make_plan(goal="Fremder Stand")
        foreign["current_task"] = "t1"
        foreign["tasks"]["t1"]["status"] = "completed"
        path.write_text(json.dumps(foreign, indent=2), encoding="utf-8")

        with pytest.raises(tools_base.PlanConflictError):
            tools_base._save_plan(plan)

        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["goal"] == "Fremder Stand", "Fremder Stand darf nicht ueberschrieben werden"

    def test_conflict_leaves_a_copy(self):
        plan = make_plan()
        tools_base._save_plan(plan)
        path = _plan_path(plan["plan_id"])
        path.write_text(json.dumps(make_plan(goal="Fremd"), indent=2), encoding="utf-8")

        with pytest.raises(tools_base.PlanConflictError):
            tools_base._save_plan(plan)

        copies = list(path.parent.glob(f"{plan['plan_id']}.conflict-*.json"))
        assert copies, "Konflikt muss nachvollziehbar gesichert werden"

    def test_same_state_can_be_saved_twice(self):
        """Nach dem Write muss die Signatur stimmen, sonst Konflikt mit sich selbst."""
        plan = make_plan()
        tools_base._save_plan(plan)
        tools_base._save_plan(plan)  # darf nicht werfen


class TestAtomicWrite:
    def test_write_uses_atomic_replace(self, monkeypatch):
        calls = []
        real = os.replace

        def spy(src, dst, *a, **k):
            calls.append((str(src), str(dst)))
            return real(src, dst, *a, **k)

        monkeypatch.setattr(os, "replace", spy)

        tools_base._save_plan(make_plan())

        assert calls, "Plan muss atomar (temp + os.replace) geschrieben werden"

    def test_failed_write_leaves_old_content(self, monkeypatch):
        plan = make_plan()
        tools_base._save_plan(plan)
        path = _plan_path(plan["plan_id"])
        before = path.read_text(encoding="utf-8")

        def boom(*a, **k):
            raise OSError("Platte voll")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            tools_base._save_plan(make_plan(goal="Neu"))

        assert path.read_text(encoding="utf-8") == before


class TestArchivedPlanIsGone:
    def test_save_refuses_archived_plan(self):
        plan = make_plan(plan_id="gone")
        archive = plan_core.ARCHIVE_DIR / "gone.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps(plan), encoding="utf-8")

        with pytest.raises(tools_base.PlanGoneError):
            tools_base._save_plan(plan)

        assert not _plan_path("gone").exists(), "Archivierter Plan darf nicht auferstehen"
