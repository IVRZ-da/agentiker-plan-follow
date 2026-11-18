"""Session-Scope: echte Session-ID und State pro Session.

Hintergrund: ``tools/base.get_session_id()`` las die ID aus ``os.environ``. Im Gateway laufen
mehrere Sessions im selben Prozess — die erste gesetzte ID galt dann fuer alle, und der
prozessweite ``STATE`` mischte ihre Plaene. Diese Tests halten die neue Reihenfolge fest:
ContextVar vor Env vor UUID, und State getrennt pro Session.
"""
from __future__ import annotations

import sys
import types

import pytest


def _fake_gateway(monkeypatch, value: str | None):
    """Baut ein Minimal-``gateway.session_context`` (oder entfernt es)."""
    if value is None:
        monkeypatch.delitem(sys.modules, "gateway.session_context", raising=False)
        monkeypatch.delitem(sys.modules, "gateway", raising=False)
        return

    class _Ctx:
        def get_session_env(self, name, default=""):
            if name == "HERMES_SESSION_ID":
                return value
            return default

    pkg = types.ModuleType("gateway")
    pkg.session_context = _Ctx()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gateway", pkg)
    monkeypatch.setitem(sys.modules, "gateway.session_context", pkg.session_context)


@pytest.fixture
def base_mod():
    from plan_follow.tools import base

    return base


class TestRuntimeSessionId:
    def test_contextvar_gewinnt_gegen_env(self, base_mod, monkeypatch):
        monkeypatch.setenv("HERMES_SESSION_ID", "env-session")
        _fake_gateway(monkeypatch, "ctx-session")
        assert base_mod.get_session_id() == "ctx-session"

    def test_env_fallback_ohne_gateway(self, base_mod, monkeypatch):
        monkeypatch.setenv("HERMES_SESSION_ID", "env-session")
        _fake_gateway(monkeypatch, None)
        assert base_mod.get_session_id() == "env-session"

    def test_session_id_env_zweite_wahl(self, base_mod, monkeypatch):
        monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
        monkeypatch.setenv("SESSION_ID", "legacy-session")
        _fake_gateway(monkeypatch, None)
        assert base_mod.get_session_id() == "legacy-session"

    def test_uuid_ohne_jede_quelle(self, base_mod, monkeypatch):
        monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)
        _fake_gateway(monkeypatch, None)
        base_mod.STATE.session_id = None
        sid = base_mod.get_session_id()
        assert len(sid) == 36 and sid == base_mod.get_session_id()

    def test_cache_vererbt_keine_alte_session(self, base_mod, monkeypatch):
        """Der prozessweite Cache darf eine neue Runtime-ID nicht ueberstimmen."""
        monkeypatch.setenv("HERMES_SESSION_ID", "env-session")
        _fake_gateway(monkeypatch, "erste-session")
        assert base_mod.get_session_id() == "erste-session"
        _fake_gateway(monkeypatch, "zweite-session")
        assert base_mod.get_session_id() == "zweite-session"
        assert base_mod.STATE.session_id == "zweite-session"

    def test_leere_ctx_wert_faellt_auf_env(self, base_mod, monkeypatch):
        monkeypatch.setenv("HERMES_SESSION_ID", "env-session")
        _fake_gateway(monkeypatch, "   ")
        assert base_mod.get_session_id() == "env-session"


class TestSessionScopedState:
    """Der aktive Plan darf nicht zwischen Sessions im selben Prozess wandern."""

    def _state(self):
        from plan_follow.tools.state import STATE

        return STATE

    def test_plan_ist_pro_session_getrennt(self, monkeypatch):
        state = self._state()
        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _fake_gateway(monkeypatch, "session-a")
        state.active_plan = {"plan_id": "plan-a", "current_task": "t1"}
        state.active_plan_id = "plan-a"

        _fake_gateway(monkeypatch, "session-b")
        assert state.active_plan is None
        assert state.active_plan_id is None

        state.active_plan = {"plan_id": "plan-b", "current_task": "t9"}
        assert state.active_plan["plan_id"] == "plan-b"

        _fake_gateway(monkeypatch, "session-a")
        assert state.active_plan["plan_id"] == "plan-a"
        assert state.active_plan_id == "plan-a"

    def test_fallback_ohne_session_ist_gemeinsam(self, monkeypatch):
        state = self._state()
        monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)
        _fake_gateway(monkeypatch, None)
        state.active_plan = {"plan_id": "cli-plan"}
        assert state.active_plan["plan_id"] == "cli-plan"

    def test_leerer_slot_wird_nicht_gesammelt(self, monkeypatch):
        state = self._state()
        monkeypatch.setenv("HERMES_SESSION_ID", "session-c")
        _fake_gateway(monkeypatch, "session-c")
        state.active_plan = {"plan_id": "x"}
        assert "session-c" in state._slots
        state.active_plan = None
        assert "session-c" not in state._slots


class TestOhneGateway:
    def test_kaputter_gateway_import_faellt_auf_env(self, monkeypatch):
        """Kein importierbares ``gateway.session_context`` (None in sys.modules) → Env gilt."""
        monkeypatch.setitem(sys.modules, "gateway", None)
        monkeypatch.setitem(sys.modules, "gateway.session_context", None)
        monkeypatch.setenv("HERMES_SESSION_ID", "env-99")

        from plan_follow.tools.session_scope import _read_contextvar, runtime_session_id

        assert _read_contextvar() == ""
        assert runtime_session_id() == "env-99"

    def test_weder_gateway_noch_env_gibt_leeren_schluessel(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "gateway", None)
        monkeypatch.setitem(sys.modules, "gateway.session_context", None)
        monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)

        from plan_follow.tools.session_scope import scope_key

        assert scope_key() == ""
