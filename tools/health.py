"""health.py — Health check for plan_follow tools/ subpackage."""

from __future__ import annotations

from typing import Any

from .base import (
    logger,
)
from plan_follow.tools.resolver import resolve_honcho_url
from .coordination import _dispatch_honcho_tool


# ─── Health Check ─────────────────────────────────────────────────────────────


def health_check() -> dict:
    """Check all core systems including this plugin. Returns {"status": "ok"} or {"status": "degraded", "issues": [...]}."""
    issues = []

    # 0. plan_follow plugin self-check
    from tools.registry import registry
    plan_tools = ["plan_create", "plan_current", "plan_complete", "plan_verify", "plan_status", "plan_update"]
    for t in plan_tools:
        if not registry.get_entry(t):
            issues.append(f"plan_follow: Eigenes Tool '{t}' nicht im Registry — Plugin defekt!")
            break

    # 1. agentiker_code_intel (code_* Tools)
    code_tools = ["code_search", "code_refactor", "code_definition"]
    for t in code_tools:
        if not registry.get_entry(t):
            issues.append(f"agentiker_code_intel: Tool '{t}' nicht im Registry")
            break

    # 2. Honcho — try registry dispatch first, fallback to HTTP
    honcho_ok = _dispatch_honcho_tool("honcho_search", {"query": "health"})
    if honcho_ok is None:
        import urllib.request
        try:
            resp = urllib.request.urlopen(f"{resolve_honcho_url()}/health", timeout=3)
            if resp.status != 200:
                issues.append("Honcho: Health check failed")
        except Exception as e:
            issues.append(f"Honcho: Nicht erreichbar ({e})")
    elif not isinstance(honcho_ok, dict):
        issues.append("Honcho: Registry dispatch returned unexpected format")

    if issues:
        return {"status": "degraded", "issues": issues}
    return {"status": "ok"}
