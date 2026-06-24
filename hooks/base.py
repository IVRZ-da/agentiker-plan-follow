"""hooks/base.py — Shared base for plan_follow hooks.

TTL Cache, banner builder, smart banner state, keyword detection.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("plan_follow")

# ─── TTL Cache ─────────────────────────────────────────────────────────────────
_hook_cache: dict = {}
_HOOK_CACHE_TTL = 300  # seconds (5 min)
_HEALTH_CACHE_TTL = 600  # seconds (10 min)
_HEALTH_CACHE_KEY = "health_v2"

# ─── Smart Banner State ────────────────────────────────────────────────────────
_banner_turn_counter: int = 0
_BANNER_FULL_EVERY_N_TURNS = 5
_BANNER_COMPACT_EVERY_N_TURNS = 2
_last_task_id: str = ""
_banner_last_task_id: str = ""

_PLAN_KEYWORDS = {
    "plan", "task", "phase", "hook", "banner", "status", "progress",
    "complete", "completed", "abschliessen", "fertig", "done",
    "weiter", "next", "offen", "was gibt", "was steht",
    "a0", "a1", "a2", "a3", "a4", "a5", "f1", "f2", "p0",
    "roadmap", "hook-verbesserung",
}


def _cached_or_fresh(key: str, fetcher, ttl: int = _HOOK_CACHE_TTL):
    """Generic TTL cache: returns cached value or calls fetcher()."""
    cached = _hook_cache.get(key)
    if cached:
        val, ts = cached
        if time.monotonic() - ts < ttl:
            return val
        del _hook_cache[key]
    try:
        val = fetcher()
        if val is not None:
            _hook_cache[key] = (val, time.monotonic())
        return val
    except Exception:
        return None


def invalidate_hook_cache() -> None:
    """Invalidate all cached hook data (health, drift, git status, etc.).
    Call this when the plan changes (task completed, plan switched, etc.)
    so the next banner shows fresh data."""
    _hook_cache.clear()
    # Reset smart banner counter so next turn shows full banner
    global _banner_turn_counter
    _banner_turn_counter = 0


def _build_banner(lines: list) -> Optional[str]:
    """Wrap lines in PLAN banner or return None if empty."""
    if not lines:
        return None
    full = [
        "╔═══════════════════════════════════════════╗",
    ]
    full.extend(lines)
    full.append("╚═══════════════════════════════════════════╝")
    return "[PLAN] " + "\n[PLAN] ".join(full)


def _has_plan_keywords(text: str) -> bool:
    """Check if user message contains plan-relevant keywords."""
    if not text:
        return False
    lower = text.lower()
    for kw in _PLAN_KEYWORDS:
        if kw in lower:
            return True
    return False


def _get_last_user_message(kwargs: dict) -> str:
    """Extract the last user message from Hermes kwargs."""
    messages = kwargs.get("messages", [])
    if not messages:
        return ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content
    return ""


def _build_compact_banner(current: dict) -> str:
    """1-line compact banner for rapid turns (no changes)."""
    task_id = current.get("task_id", "?")
    task_name = current.get("name", "?")[:40]
    progress = current.get("progress", "?")
    return _build_banner([
        f"║  📋 [{task_id}] {task_name}  {progress:>20}  ║",
    ]) or ""
