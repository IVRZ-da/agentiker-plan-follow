"""hooks/breaker.py — Circuit Breaker for plan_follow hooks.

Tracks critical tool failures and displays warnings in the banner.
"""

import logging
import time

logger = logging.getLogger("plan_follow")

# ─── Circuit Breaker ──────────────────────────────────────────────────────────────
_breaker_state: dict[str, dict] = {}
_BREAKER_TTL = 300  # 5 min auto-clear
_BREAKER_CRITICAL_PREFIXES = (
    "honcho_", "mcp_firecrawl_", "analysis_", "bug_hunt_",
    "research_", "code_", "plan_",
)


def _check_breaker() -> dict[str, dict]:
    """Return active breaker entries (auto-expired ones removed)."""
    now = time.monotonic()
    expired = [t for t, info in list(_breaker_state.items()) if now - info["ts"] > _BREAKER_TTL]
    for t in expired:
        _breaker_state.pop(t, None)
    return dict(_breaker_state)


def _set_breaker(tool_name: str, error_msg: str) -> None:
    """Record a circuit-breaker hit for a critical tool."""
    _breaker_state[tool_name] = {"error": error_msg[:80], "ts": time.monotonic()}


def _build_breaker_banner() -> list[str]:
    """Build circuit-breaker warning lines (shown BEFORE health banner)."""
    active = _check_breaker()
    if not active:
        return []
    lines = [
        "║  🚫 CIRCUIT BREAKER ACTIVE                ║",
    ]
    for tool, info in list(active.items())[:3]:
        lines.append(f"║    • {tool}: {info['error'][:50]}")
    if len(active) > 3:
        lines.append(f"║    ... und {len(active) - 3} weitere")
    lines.append("║  → Nur lesende Analyse                 ║")
    lines.append("║  → Johannes entscheiden lassen          ║")
    return lines
