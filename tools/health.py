"""health.py — Verfuegbarkeits-Check fuer plan_follow.

v0.5.33 — drei Korrekturen an einer Stelle, die am 11.11.2026 falschen Alarm
gemeldet hat ("SYSTEM HEALTH DEGRADED: plan_tools/plan_hooks/code_intel nicht
importierbar", waehrend die Tools im selben Prozess liefen):

1. **Kein ``find_spec``/``import_module`` mehr fuer Fremdmodule.** Beides haengt
   an ``sys.path``. Im Hermes-Prozess liegt das Plugin-Verzeichnis dort nicht
   (Hermes laedt Plugins unter eigenem Namen), der Check war also strukturell
   falsch-negativ. Geprueft wird jetzt der geladene Zustand (``sys.modules``)
   plus ein Selbst-Check der eigenen Attribute.
2. **Flap-Daempfung.** DEGRADED erst nach zwei aufeinanderfolgenden Fehlschlaegen.
   Ein transienter Fehler waehrend eines Edits war sonst 60 s "Systemstoerung".
3. **Zeitstempel + Opt-in fuer Fremdsysteme.** Das Ergebnis traegt ``checked_at``;
   HTTP-Checks (Firecrawl, Honcho) laufen nur mit
   ``PLAN_FOLLOW_VERBOSE_HEALTH=1`` — sie kosteten sonst bis zu 6 s pro Turn.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("plan_follow")

_FAIL_STREAK = 0
_CHECKED_AT: Optional[str] = None
_CHECKED_TS: float = 0.0

# Fremd-Plugins, deren Verfuegbarkeit im Banner interessant ist
_EXTERNAL_MODULES = ("code_intel", "scout")


def reset_health_state() -> None:
    """Streak/Zeitstempel zuruecksetzen (Tests, nach Konfigurationswechsel)."""
    global _FAIL_STREAK, _CHECKED_AT, _CHECKED_TS
    _FAIL_STREAK = 0
    _CHECKED_AT = None
    _CHECKED_TS = 0.0


def _loaded(name: str) -> bool:
    """Modul geladen? (Suffix-tolerant, kein sys.path-Zugriff)."""
    for key in list(sys.modules):
        if key == name or key.endswith("." + name):
            return True
    return False


def _mod_available(name: str) -> bool:
    """Geladen ODER importierbar — aber ohne Seiteneffekt auf sys.path.

    Nur fuer Tests/Rueckwaertskompatibilitaet: der Banner benutzt ausschliesslich
    ``loaded_plugins()``.
    """
    if _loaded(name):
        return True
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _self_check() -> list[str]:
    """Eigene Integritaet pruefen — der einzige harte Fehlerfall."""
    issues = []
    try:
        hooks = importlib.import_module("plan_follow.plan_hooks")
        for attr in ("on_pre_llm_call", "on_post_tool_call"):
            if not callable(getattr(hooks, attr, None)):
                issues.append(f"plan_follow.plan_hooks.{attr} fehlt")
    except Exception as exc:
        issues.append(f"plan_follow.plan_hooks nicht ladbar: {type(exc).__name__}")

    try:
        tools = importlib.import_module("plan_follow.plan_tools")
        if not hasattr(tools, "plan_create_tool"):
            issues.append("plan_follow.plan_tools ohne Handler")
    except Exception as exc:
        issues.append(f"plan_follow.plan_tools nicht ladbar: {type(exc).__name__}")
    return issues


def _verbose() -> bool:
    return os.environ.get("PLAN_FOLLOW_VERBOSE_HEALTH", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _http_ok(url: str, timeout: int = 3) -> bool:
    """Check if an HTTP endpoint returns 200."""
    import urllib.request

    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return resp.status == 200
    except Exception:
        return False


def _collect_issues() -> list[str]:
    issues = _self_check()

    # Fremd-Plugins: "nicht geladen" ist ein Hinweis, kein Defekt. Kein Import,
    # kein find_spec — beides wuerde nur sys.path messen.
    for module in _EXTERNAL_MODULES:
        if not _loaded(module):
            logger.debug("Plugin '%s' ist im aktuellen Prozess nicht geladen", module)

    if _verbose():
        if not _http_ok("http://localhost:8081/health"):
            issues.append("Firecrawl: localhost:8081/health nicht erreichbar")
        try:
            from .resolver import resolve_honcho_url

            url = f"{resolve_honcho_url()}/health" if resolve_honcho_url() else ""
            if url and not _http_ok(url):
                issues.append("Honcho: Health check failed")
        except Exception as exc:
            issues.append(f"Honcho: Check fehlgeschlagen ({type(exc).__name__})")

    return issues


def loaded_plugins() -> dict:
    """Welche Plugins sind im Prozess geladen? Fuer den Tool-Check-Banner."""
    state = {"plan_follow": _loaded("plan_follow")}
    for module in _EXTERNAL_MODULES:
        state[module] = _loaded(module)
    return state


def health_check() -> dict:
    """Systemzustand pruefen — mit Flap-Daempfung und Zeitstempel.

    Returns:
        {"status": "ok"|"degraded", "issues": [...], "pending": [...],
         "checked_at": iso, "fail_streak": int}
    """
    global _FAIL_STREAK, _CHECKED_AT, _CHECKED_TS

    issues = _collect_issues()
    if issues:
        _FAIL_STREAK += 1
    else:
        _FAIL_STREAK = 0

    _CHECKED_TS = time.time()
    _CHECKED_AT = datetime.now(timezone.utc).isoformat()

    degraded = _FAIL_STREAK >= 2
    return {
        "status": "degraded" if degraded else "ok",
        "issues": issues if degraded else [],
        "pending": issues if not degraded else [],
        "checked_at": _CHECKED_AT,
        "fail_streak": _FAIL_STREAK,
    }


def health_age_seconds() -> Optional[float]:
    """Sekunden seit dem letzten Check (None, wenn noch keiner lief)."""
    if not _CHECKED_TS:
        return None
    return max(0.0, time.time() - _CHECKED_TS)
