"""Health-Banner darf keinen transienten Fehler als Dauerzustand behaupten.

Beobachtet: 'SYSTEM HEALTH DEGRADED: plan_tools/plan_hooks nicht importierbar',
waehrend die Module live funktionierten. Ursache: find_spec im eigenen, gerade
halb kaputten Prozess (tools/health.py:16-21), gecacht 60 s, ohne Zeitstempel
und ohne Flap-Daempfung.
"""

import pytest
from plan_follow import plan_hooks


@pytest.fixture(autouse=True)
def _clear_hook_cache(monkeypatch):
    plan_hooks._hook_cache.clear()
    yield
    plan_hooks._hook_cache.clear()


@pytest.fixture
def broken_modules(monkeypatch):
    """Simuliert einen echten Selbst-Check-Fehler (der einzige harte Defekt)."""
    import plan_follow.tools.health as health

    monkeypatch.setattr(
        health, "_self_check", lambda: ["plan_follow.plan_tools ohne Handler"]
    )
    monkeypatch.setattr(health, "_http_ok", lambda *a, **k: True)
    return health


class TestFlapDamping:
    def test_single_failure_is_not_degraded(self, broken_modules):
        broken_modules.reset_health_state()

        result = broken_modules.health_check()

        assert result["status"] == "ok", "Ein einzelner Fehlschlag ist kein DEGRADED"

    def test_two_consecutive_failures_are_degraded(self, broken_modules):
        broken_modules.reset_health_state()

        broken_modules.health_check()
        result = broken_modules.health_check()

        assert result["status"] == "degraded"
        assert result["issues"]

    def test_recovery_resets_streak(self, broken_modules, monkeypatch):
        broken_modules.reset_health_state()
        broken_modules.health_check()  # 1. Fehlschlag

        monkeypatch.setattr(broken_modules, "_self_check", lambda: [])
        assert broken_modules.health_check()["status"] == "ok"

        monkeypatch.setattr(
            broken_modules, "_self_check", lambda: ["plan_follow.plan_tools ohne Handler"]
        )
        assert broken_modules.health_check()["status"] == "ok", "Streak muss zurueckgesetzt sein"


class TestHealthBannerHonesty:
    def test_banner_shows_check_timestamp(self, broken_modules, monkeypatch):
        broken_modules.reset_health_state()
        monkeypatch.setattr(broken_modules, "health_check", lambda: {
            "status": "degraded",
            "issues": ["plan_follow: plan_tools nicht importierbar"],
            "checked_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        })
        plan_hooks._hook_cache.clear()

        lines = plan_hooks._build_health_banner()
        text = "\n".join(lines)

        assert "DEGRADED" in text
        assert "geprüft" in text.lower(), "Ohne Zeitstempel ist die Meldung nicht pruefbar"

    def test_unknown_availability_is_not_an_error_marker(self, monkeypatch):
        """Unbekannt ist nicht kaputt: kein ❌ ohne echten Beweis."""
        lines = plan_hooks._build_tool_check_banner()
        text = "\n".join(lines)

        assert "❌" not in text, f"Tool-Check behauptet einen Defekt: {text!r}"
