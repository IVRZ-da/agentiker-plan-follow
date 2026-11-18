"""Ownership-Guard am geteilten plans_index.json.

Der Index hat genau ein ``active_plan_id``. Vorher gewann der letzte Schreiber — eine
parallele Session verlor damit ihren aktiven Plan („Task X is not the current task" oder
„No active plan", obwohl der eigene Plan offen war). Jetzt gilt: hält eine andere *lebende*
Session den Anker, wird er nicht überschrieben; der eigene Plan lebt in sessions.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def base_mod():
    from plan_follow.tools import base

    base._INDEX_WARNED.clear()
    return base


@pytest.fixture
def coord():
    from plan_follow import coord_state

    return coord_state


@pytest.fixture
def me(monkeypatch, base_mod):
    """Diese Session heißt 'me' — unabhängig von der Env des Testprozesses."""
    monkeypatch.setattr(base_mod, "get_session_id", lambda: "me")
    return "me"


def _write_index(base_mod, plan_id: str) -> None:
    path = base_mod.resolve_plans_index()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"active_plan_id": plan_id, "active_goal": "fremd"}),
                    encoding="utf-8")


def _read_index(base_mod) -> dict:
    return json.loads(base_mod.resolve_plans_index().read_text(encoding="utf-8"))


def _plan(plan_id: str = "plan-a") -> dict:
    return {"plan_id": plan_id, "goal": "eigener Plan", "current_task": "t1",
            "created": "2026-11-18T10:00:00+00:00"}


class TestIndexOwnership:
    def test_fremde_lebende_session_behaelt_den_anker(self, base_mod, coord, me):
        coord.register_session("other", plan_id="plan-b")
        _write_index(base_mod, "plan-b")

        base_mod._update_plans_index(_plan("plan-a"))

        assert _read_index(base_mod)["active_plan_id"] == "plan-b"
        own = coord.get_session("me")
        assert own and own["plan_id"] == "plan-a"
        assert any("plan-b" in w for w in base_mod.STATE.drift_warnings)

    def test_eigene_session_darf_schreiben(self, base_mod, coord, me):
        coord.register_session("me", plan_id="plan-a")
        _write_index(base_mod, "plan-a")

        base_mod._update_plans_index(_plan("plan-a"))

        assert _read_index(base_mod)["active_plan_id"] == "plan-a"

    def test_stale_owner_blockiert_nicht(self, base_mod, coord, me, tmp_path):
        coord.register_session("dead", plan_id="plan-b")
        sessions = coord.get_sessions()
        sessions["dead"]["last_seen"] = (
            datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
        coord._atomic_write(coord.SESSIONS_FILE, sessions)
        _write_index(base_mod, "plan-b")

        base_mod._update_plans_index(_plan("plan-a"))

        assert _read_index(base_mod)["active_plan_id"] == "plan-a"

    def test_kein_konflikt_ohne_fremden_plan(self, base_mod, coord, me):
        _write_index(base_mod, "")
        base_mod._update_plans_index(_plan("plan-a"))
        assert _read_index(base_mod)["active_plan_id"] == "plan-a"

    def test_abgeschlossener_plan_leert_den_anker(self, base_mod, coord, me):
        _write_index(base_mod, "plan-a")
        done = _plan("plan-a")
        done["current_task"] = None
        base_mod._update_plans_index(done)
        assert not _read_index(base_mod).get("active_plan_id")


class TestIndexStatusHint:
    def test_hinweis_bei_fremdem_anker(self, base_mod, coord, me):
        coord.register_session("other", plan_id="plan-b")
        coord.register_session("me", plan_id="plan-a")
        _write_index(base_mod, "plan-b")
        base_mod.STATE.active_plan_id = "plan-a"

        hint = base_mod.index_status_hint()
        assert "plan-b" in hint and "plan-a" in hint

    def test_kein_hinweis_wenn_eigener_plan_ankert(self, base_mod, coord, me):
        coord.register_session("me", plan_id="plan-a")
        _write_index(base_mod, "plan-a")
        base_mod.STATE.active_plan_id = "plan-a"
        assert base_mod.index_status_hint() == ""

    def test_kein_hinweis_ohne_session_bindung(self, base_mod, coord, me):
        _write_index(base_mod, "plan-b")  # niemand hält plan-b
        base_mod.STATE.active_plan_id = "plan-a"
        assert base_mod.index_status_hint() == ""
