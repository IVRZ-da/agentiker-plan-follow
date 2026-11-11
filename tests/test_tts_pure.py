"""Der Renderpfad darf NIEMALS schreiben.

plan_hooks.py:543 ruft aus _build_tts_banner() plan_core._save_plan(active_plan).
Damit schreibt ein Anzeige-Builder die Plan-Datei (plus .bak, plans_index.json)
und kann im Plans-Repo committen. Ein veralteter In-Memory-Stand ueberschreibt
so den neueren Disk-Stand — der Datenverlustpfad, den v0.5.33 schliesst.
"""

import hashlib
import json

import pytest
from plan_follow import plan_core, plan_hooks
from plan_follow.tools.base import _plan_path
from plan_follow.tools.state import STATE


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import plan_follow.tools.health as health

    monkeypatch.setattr(health, "_http_ok", lambda *a, **k: True)
    monkeypatch.setattr(health, "_mod_available", lambda *a, **k: True)


def _plan_with_tts():
    tasks = {
        f"t{i}": {
            "id": f"t{i}",
            "status": "completed" if i == 1 else "pending",
            "name": f"Task {i}",
            "files": [],
            "verify": "true",
            "depends_on": [],
            "review_profile": "none",
            "review_result": None,
        }
        for i in (1, 2)
    }
    return {
        "plan_id": "p-tts",
        "goal": "TTS-Ziel",
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": "t2",
        "tasks": tasks,
        "tts_flags": {"plan_created": True, "task_completed": ["t1"]},
    }


class TestTTSBannerIsPure:
    def test_banner_does_not_touch_plan_file(self):
        plan = _plan_with_tts()
        path = _plan_path(plan["plan_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        STATE.active_plan = plan
        STATE.active_plan_id = plan["plan_id"]

        digest_before = hashlib.sha256(path.read_bytes()).hexdigest()
        mtime_before = path.stat().st_mtime_ns

        lines = plan_hooks._build_tts_banner()

        assert lines, "TTS-Events muessen angesagt werden"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before
        assert path.stat().st_mtime_ns == mtime_before

    def test_banner_creates_no_backup_file(self):
        plan = _plan_with_tts()
        path = _plan_path(plan["plan_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        STATE.active_plan = plan
        STATE.active_plan_id = plan["plan_id"]

        plan_hooks._build_tts_banner()

        assert not path.with_suffix(".json.bak").exists()

    def test_banner_does_not_write_plans_index(self):
        plan = _plan_with_tts()
        path = _plan_path(plan["plan_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        STATE.active_plan = plan
        STATE.active_plan_id = plan["plan_id"]

        index = plan_core.PLANS_INDEX
        before = index.read_bytes() if index.exists() else None

        plan_hooks._build_tts_banner()

        after = index.read_bytes() if index.exists() else None
        assert after == before, "Renderer darf plans_index.json nicht anfassen"

    def test_event_is_announced_exactly_once(self):
        """Das Event muss genau einmal erscheinen, danach nicht wieder."""
        plan = _plan_with_tts()
        path = _plan_path(plan["plan_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        STATE.active_plan = plan
        STATE.active_plan_id = plan["plan_id"]

        first = plan_hooks._build_tts_banner()
        second = plan_hooks._build_tts_banner()

        assert first, "Erster Aufruf muss das Event ansagen"
        assert second == [], "Zweiter Aufruf darf dasselbe Event nicht wiederholen"
