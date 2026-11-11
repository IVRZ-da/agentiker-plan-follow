"""Der Renderpfad darf keine Seiteneffekte haben — keinerlei.

Getestet mit einem globalen Spy auf alle Schreib- und Prozess-Primitiven.
Bisher schrieb der TTS-Builder die Plan-Datei (+ .bak + Index + git-Commit) und
der Drift-Banner startete 'git diff' mit 10 s Timeout pro Repo.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from plan_follow import coord_state, plan_hooks
from plan_follow.tools.base import _plan_path
from plan_follow.tools.state import STATE


@pytest.fixture
def side_effects(monkeypatch):
    """Sammelt jeden Schreib-/Prozess-Aufruf im Renderpfad."""
    calls = []

    real_write_text = Path.write_text
    real_write_bytes = Path.write_bytes
    real_replace = os.replace
    real_move = shutil.move
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def spy_write_text(self, *a, **k):
        calls.append(("Path.write_text", str(self)))
        return real_write_text(self, *a, **k)

    def spy_write_bytes(self, *a, **k):
        calls.append(("Path.write_bytes", str(self)))
        return real_write_bytes(self, *a, **k)

    def spy_replace(src, dst, *a, **k):
        calls.append(("os.replace", f"{src}->{dst}"))
        return real_replace(src, dst, *a, **k)

    def spy_move(src, dst, *a, **k):
        calls.append(("shutil.move", f"{src}->{dst}"))
        return real_move(src, dst, *a, **k)

    def spy_run(*a, **k):
        calls.append(("subprocess.run", str(a)[:80]))
        return real_run(*a, **k)

    def spy_popen(*a, **k):
        calls.append(("subprocess.Popen", str(a)[:80]))
        return real_popen(*a, **k)

    monkeypatch.setattr(Path, "write_text", spy_write_text)
    monkeypatch.setattr(Path, "write_bytes", spy_write_bytes)
    monkeypatch.setattr(os, "replace", spy_replace)
    monkeypatch.setattr(shutil, "move", spy_move)
    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(subprocess, "Popen", spy_popen)

    yield calls


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import plan_follow.tools.health as health

    monkeypatch.setattr(health, "_http_ok", lambda *a, **k: True)
    monkeypatch.setattr(health, "_mod_available", lambda *a, **k: True)


def _plan():
    tasks = {
        "t1": {
            "id": "t1",
            "status": "in_progress",
            "name": "Task 1",
            "files": ["a.py"],
            "verify": "true",
            "depends_on": [],
            "review_profile": "none",
            "review_result": None,
        }
    }
    return {
        "plan_id": "p-side",
        "goal": "Seiteneffekte",
        "created": "2026-11-11T09:00:00+00:00",
        "current_task": "t1",
        "tasks": tasks,
        "tts_flags": {"plan_created": True},
    }


def test_hook_render_has_no_side_effects(side_effects, monkeypatch):
    """Kein Schreiben in Plan-Artefakte, kein subprocess — Koordination erlaubt.

    Der Datenverlustpfad war ``_save_plan`` im Renderer (Plan-Datei, .bak,
    plans_index.json, git-Commit). Schreibzugriffe auf den Koordinations-State
    (sessions/locks/notifications/tts_queue) sind Heartbeat, kein Planinhalt.
    """
    monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")

    plan = _plan()
    path = _plan_path(plan["plan_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    STATE.active_plan = plan
    STATE.active_plan_id = plan["plan_id"]
    coord_state.register_session("s-1", plan_id=plan["plan_id"], goal="x")

    side_effects.clear()
    out = plan_hooks.on_pre_llm_call(session_id="s-1", is_first_turn=False)

    assert out is not None

    def _allowed(entry) -> bool:
        kind, detail = entry
        if kind.startswith("subprocess"):
            return False
        return "/shared/" in str(detail)

    forbidden = [e for e in side_effects if not _allowed(e)]
    assert forbidden == [], f"Renderpfad hat Seiteneffekte: {forbidden}"
    assert not any(e[0].startswith("subprocess") for e in side_effects), (
        f"Renderpfad startet Prozesse: {side_effects}"
    )
