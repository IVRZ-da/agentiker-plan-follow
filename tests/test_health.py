"""Tests for tools/health.py — Health-Check für plan_follow Core-Systeme."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plan_follow.tools.health import _http_ok, _mod_available, health_check

# resolve_honcho_url wird lazy in health_check() importiert (from .resolver)
# Daher muss der Patch auf plan_follow.tools.resolver zielen, nicht auf health
_HONCHO = "plan_follow.tools.resolver.resolve_honcho_url"


# ─── _mod_available ──────────────────────────────────────────────────────────


class TestModAvailable:
    """importlib.util.find_spec wrapper."""

    def test_module_exists(self):
        """Findbare Module -> True."""
        assert _mod_available("os") is True

    def test_module_not_found(self):
        """Nicht findbare Module -> False."""
        assert _mod_available("_nonexistent_module_xyz_") is False

    def test_find_spec_raises_exception(self):
        """find_spec wirft Exception -> False (Coverage: Zeile 20-21)."""
        with patch("importlib.util.find_spec", side_effect=ValueError("mock")):
            assert _mod_available("anything") is False


# ─── _http_ok ────────────────────────────────────────────────────────────────


class TestHttpOk:
    """HTTP-Endpoint-Check."""

    def test_http_200(self):
        """200 -> True."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _http_ok("http://ok") is True

    def test_http_non_200(self):
        """Nicht-200 -> False."""
        mock_resp = MagicMock()
        mock_resp.status = 404
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _http_ok("http://notfound") is False

    def test_urlopen_raises_exception(self):
        """urlopen wirft Exception -> False (Coverage: Zeile 31-32)."""
        with patch("urllib.request.urlopen", side_effect=ConnectionError("mock")):
            assert _http_ok("http://fail") is False


# ─── health_check ─────────────────────────────────────────────────────────────


class TestHealthCheck:
    """health_check() — vollstaendige Systempruefung."""

    def _ok(self, mod_name: str) -> bool:
        """Alle Module verfuegbar -> True."""
        return True

    def test_all_ok(self):
        """Alle Systeme verfuegbar -> status: ok."""
        with patch("plan_follow.tools.health._mod_available", return_value=True):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result == {"status": "ok"}

    def test_plan_tools_not_available(self):
        """plan_follow.plan_tools nicht importierbar -> degraded."""

        def fake_mod(mod_name: str) -> bool:
            if mod_name == "plan_follow.plan_tools":
                return False
            return True

        with patch("plan_follow.tools.health._mod_available", side_effect=fake_mod):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "plan_follow: plan_tools nicht importierbar" in result["issues"]

    def test_plan_hooks_not_available(self):
        """plan_follow.plan_hooks nicht importierbar -> degraded."""

        def fake_mod(mod_name: str) -> bool:
            if mod_name == "plan_follow.plan_hooks":
                return False
            return True

        with patch("plan_follow.tools.health._mod_available", side_effect=fake_mod):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "plan_follow: plan_hooks nicht importierbar" in result["issues"]

    def test_code_intel_not_available(self):
        """code_intel Plugin nicht importierbar -> degraded."""

        def fake_mod(mod_name: str) -> bool:
            if mod_name == "code_intel":
                return False
            return True

        with patch("plan_follow.tools.health._mod_available", side_effect=fake_mod):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "code_intel Plugin nicht importierbar" in result["issues"]

    def test_code_intel_code_tools_not_available(self):
        """code_intel verfuegbar, code_tools nicht -> degraded (Coverage Zeile 49)."""

        def fake_mod(mod_name: str) -> bool:
            if mod_name == "code_intel":
                return True
            if mod_name == "code_intel.code_tools":
                return False
            return True

        with patch("plan_follow.tools.health._mod_available", side_effect=fake_mod):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "code_intel.code_tools nicht importierbar" in result["issues"]

    def test_scout_not_available(self):
        """scout Plugin nicht importierbar -> degraded."""

        def fake_mod(mod_name: str) -> bool:
            if mod_name == "scout":
                return False
            return True

        with patch("plan_follow.tools.health._mod_available", side_effect=fake_mod):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "scout Plugin nicht importierbar" in result["issues"]

    def test_scout_submodules_not_available(self):
        """scout verfuegbar, Sub-Module fehlen -> degraded (Coverage Zeile 57)."""

        def fake_mod(mod_name: str) -> bool:
            if mod_name == "scout":
                return True
            if mod_name.startswith("scout."):
                return False
            return True

        with patch("plan_follow.tools.health._mod_available", side_effect=fake_mod):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        scout_issues = [i for i in result["issues"] if i.startswith("scout.")]
        assert len(scout_issues) >= 1

    def test_firecrawl_not_reachable(self):
        """Firecrawl nicht erreichbar -> degraded."""

        def fake_http(url: str, **kw) -> bool:
            return "localhost" not in url

        with patch("plan_follow.tools.health._mod_available", return_value=True):
            with patch("plan_follow.tools.health._http_ok", side_effect=fake_http):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "Firecrawl" in " ".join(result["issues"])

    def test_honcho_check_fails(self):
        """Honcho-URL gesetzt, nicht erreichbar -> degraded."""

        def fake_http(url: str, **kw) -> bool:
            return "honcho" not in url

        with patch("plan_follow.tools.health._mod_available", return_value=True):
            with patch("plan_follow.tools.health._http_ok", side_effect=fake_http):
                with patch(_HONCHO, return_value="http://honcho:8001"):
                    result = health_check()
        assert result["status"] == "degraded"
        assert "Honcho: Health check failed" in result["issues"]

    def test_honcho_resolver_exception(self):
        """resolve_honcho_url wirft Exception -> degraded (Coverage Zeile 70-71)."""
        with patch("plan_follow.tools.health._mod_available", return_value=True):
            with patch("plan_follow.tools.health._http_ok", return_value=True):
                with patch(_HONCHO, side_effect=RuntimeError("resolver failed")):
                    result = health_check()
        assert result["status"] == "degraded"
        assert any("Honcho: Check fehlgeschlagen" in i for i in result["issues"])
