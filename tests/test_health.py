"""Tests fuer tools/health.py — Verfuegbarkeit ohne sys.path-Abhaengigkeit.

v0.5.33: Der Check prueft den geladenen Zustand (``sys.modules``) statt
``importlib.util.find_spec``. find_spec hängt an ``sys.path``; im Hermes-Prozess
liegt das Plugin-Verzeichnis dort nicht, weshalb der Banner "plan_follow nicht
importierbar" meldete, während die Tools liefen.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plan_follow.tools import health as health_mod
from plan_follow.tools.health import (
    _http_ok,
    _loaded,
    _mod_available,
    health_check,
    loaded_plugins,
    reset_health_state,
)

# resolve_honcho_url wird lazy in _collect_issues() importiert (from .resolver)
_HONCHO = "plan_follow.tools.resolver.resolve_honcho_url"


@pytest.fixture(autouse=True)
def _reset_health():
    reset_health_state()
    yield
    reset_health_state()


# ─── _loaded ─────────────────────────────────────────────────────────────────


class TestLoaded:
    """Geladener Zustand statt Dateisystem-Suche."""

    def test_loaded_module(self):
        assert _loaded("os") is True

    def test_unloaded_module(self):
        assert _loaded("_nonexistent_module_xyz_") is False

    def test_suffix_match_finds_submodule(self):
        """plan_follow.plan_hooks muss als 'plan_hooks' gefunden werden."""
        import plan_follow.plan_hooks  # noqa: F401

        assert _loaded("plan_hooks") is True


# ─── _mod_available (Rueckwaertskompatibilitaet) ─────────────────────────────


class TestModAvailable:
    def test_importable(self):
        assert _mod_available("os") is True

    def test_missing(self):
        assert _mod_available("_nonexistent_module_xyz_") is False

    def test_import_raises(self):
        with patch("importlib.import_module", side_effect=ValueError("mock")):
            assert _mod_available("_dessen_ist_nicht_geladen_") is False


# ─── _http_ok ────────────────────────────────────────────────────────────────


class TestHttpOk:
    def test_http_200(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _http_ok("http://ok") is True

    def test_http_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status = 404
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _http_ok("http://notfound") is False

    def test_urlopen_raises_exception(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionError("mock")):
            assert _http_ok("http://fail") is False


# ─── health_check ────────────────────────────────────────────────────────────


class TestHealthCheck:
    """health_check() — Flap-Daempfung, Zeitstempel, keine sys.path-Messung."""

    def test_all_ok(self):
        result = health_check()
        assert result["status"] == "ok"
        assert result["issues"] == []
        assert result["fail_streak"] == 0
        assert result["checked_at"]

    def test_single_failure_is_pending_not_degraded(self):
        with patch.object(
            health_mod, "_self_check", return_value=["plan_follow.plan_tools ohne Handler"]
        ):
            first = health_check()
        assert first["status"] == "ok"
        assert first["pending"] == ["plan_follow.plan_tools ohne Handler"]

    def test_two_failures_are_degraded(self):
        with patch.object(health_mod, "_self_check", return_value=["plan_tools ohne Handler"]):
            health_check()
            second = health_check()
        assert second["status"] == "degraded"
        assert second["issues"] == ["plan_tools ohne Handler"]

    def test_recovery_resets_streak(self):
        with patch.object(health_mod, "_self_check", return_value=["x"]):
            health_check()
        with patch.object(health_mod, "_self_check", return_value=[]):
            assert health_check()["status"] == "ok"
        with patch.object(health_mod, "_self_check", return_value=["x"]):
            assert health_check()["status"] == "ok", "Streak muss zurueckgesetzt sein"

    def test_external_plugins_are_not_an_error(self):
        """scout/code_intel nicht geladen ist ein Hinweis, kein Defekt."""
        result = health_check()
        assert not any("scout" in i or "code_intel" in i for i in result["pending"])

    def test_firecrawl_only_in_verbose_mode(self, monkeypatch):
        monkeypatch.setattr(
            health_mod, "_http_ok", lambda url, **kw: "localhost" not in url
        )
        assert health_check()["pending"] == [], "Ohne Flag kein HTTP-Check"

        monkeypatch.setenv("PLAN_FOLLOW_VERBOSE_HEALTH", "1")
        with patch.object(health_mod, "_self_check", return_value=[]):
            result = health_check()
        assert any("Firecrawl" in i for i in result["pending"])

    def test_honcho_only_in_verbose_mode(self, monkeypatch):
        monkeypatch.setenv("PLAN_FOLLOW_VERBOSE_HEALTH", "1")
        with patch.object(
            health_mod, "_http_ok", side_effect=lambda url, **k: "honcho" not in url
        ):
            with patch(_HONCHO, return_value="http://honcho:8001"):
                with patch.object(health_mod, "_self_check", return_value=[]):
                    result = health_check()
        assert "Honcho: Health check failed" in result["pending"]

    def test_honcho_resolver_exception(self, monkeypatch):
        monkeypatch.setenv("PLAN_FOLLOW_VERBOSE_HEALTH", "1")
        with patch(_HONCHO, side_effect=RuntimeError("resolver failed")):
            with patch.object(health_mod, "_self_check", return_value=[]):
                result = health_check()
        assert any("Honcho: Check fehlgeschlagen" in i for i in result["pending"])

    def test_self_check_failure_names_the_defect(self):
        """Der Selbst-Check ist der einzige harte Fehlerfall."""
        issues = health_mod._self_check()
        assert issues == [], f"plan_follow sollte sich selbst als gesund erkennen: {issues}"


class TestLoadedPlugins:
    def test_reports_plan_follow(self):
        assert loaded_plugins()["plan_follow"] is True

    def test_reports_booleans_for_external_plugins(self):
        state = loaded_plugins()
        assert set(state) == {"plan_follow", "code_intel", "scout"}
        assert all(isinstance(v, bool) for v in state.values())
