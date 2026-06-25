"""health.py — Health check for plan_follow tools/ subpackage.

Checks availability of core systems (plan_follow, code_intel, scout plugins,
Firecrawl, Honcho) via importlib and HTTP — NO registry dependency.
Results are consumed by plan_hooks.py _build_health_banner() (non-blocking).
"""

from __future__ import annotations

import importlib.util
import logging

logger = logging.getLogger("plan_follow")


def _mod_available(mod_name: str) -> bool:
    """Check if a Python module can be imported (works with dynamic modules, unlike find_spec)."""
    try:
        importlib.import_module(mod_name)
        return True
    except (ModuleNotFoundError, ImportError, Exception):
        return False


def _http_ok(url: str, timeout: int = 3) -> bool:
    """Check if an HTTP endpoint returns 200."""
    import urllib.request

    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return resp.status == 200
    except Exception:
        return False


def health_check() -> dict:
    """Check all core systems. Returns {"status": "ok"} or {"status": "degraded", "issues": [...]}."""
    issues = []

    # 0. plan_follow plugin self-check
    if not _mod_available("plan_follow.plan_tools"):
        issues.append("plan_follow: plan_tools nicht importierbar")
    if not _mod_available("plan_follow.plan_hooks"):
        issues.append("plan_follow: plan_hooks nicht importierbar")

    # 1. agentiker_code_intel (code_* Tools)
    if not _mod_available("code_intel"):
        issues.append("code_intel Plugin nicht importierbar")
    elif not _mod_available("code_intel.code_tools"):
        issues.append("code_intel.code_tools nicht importierbar")

    # 2. Scout Plugin (analysis_*, bug_hunt_*, research_* Tools)
    if not _mod_available("scout"):
        issues.append("scout Plugin nicht importierbar")
    else:
        for sub in ("analysis.analysis_tools", "bughunt.bughunt_tools", "research.research_tools"):
            if not _mod_available(f"scout.{sub}"):
                issues.append(f"scout.{sub} nicht importierbar")

    # 3. Firecrawl (localhost MCP)
    if not _http_ok("http://localhost:8081/health"):
        issues.append("Firecrawl: localhost:8081/health nicht erreichbar")

    # 4. Honcho — HTTP check (registry dispatch removed, no registry available)
    try:
        from .resolver import resolve_honcho_url

        url = f"{resolve_honcho_url()}/health" if resolve_honcho_url() else ""
        if url and not _http_ok(url):
            issues.append("Honcho: Health check failed")
    except Exception as e:
        issues.append(f"Honcho: Check fehlgeschlagen ({e})")

    if issues:
        return {"status": "degraded", "issues": issues}
    return {"status": "ok"}
