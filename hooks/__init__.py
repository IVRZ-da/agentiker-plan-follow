"""hooks/__init__.py — Hook-Subpackage für plan_follow.

Exportiert alle Hook-Komponenten für plan_hooks.py (Facade).
"""
__all__ = [
    "_banner_last_task_id", "_banner_turn_counter",
    "_HEALTH_CACHE_KEY", "_HEALTH_CACHE_TTL", "_hook_cache", "_HOOK_CACHE_TTL",
    "_last_task_id", "_PLAN_KEYWORDS",
    "_BANNER_COMPACT_EVERY_N_TURNS", "_BANNER_FULL_EVERY_N_TURNS",
    "_build_banner", "_build_compact_banner", "_cached_or_fresh",
    "_get_last_user_message", "_has_plan_keywords", "invalidate_hook_cache",
    "_BREAKER_CRITICAL_PREFIXES", "_BREAKER_TTL", "_breaker_state",
    "_build_breaker_banner", "_check_breaker", "_set_breaker",
    # Banner-Builder (ausgelagert aus plan_hooks.py)
    "_build_task_header", "_build_roadmap_banner", "_build_git_banner",
    "_build_drift_banner", "_build_due_banner", "_build_coordination_banner",
    "_build_tts_banner", "_build_review_banner", "_build_health_banner",
]

from .base import (
    _BANNER_COMPACT_EVERY_N_TURNS,
    _BANNER_FULL_EVERY_N_TURNS,
    _HEALTH_CACHE_KEY,
    _HEALTH_CACHE_TTL,
    _HOOK_CACHE_TTL,
    _PLAN_KEYWORDS,
    _banner_last_task_id,
    _banner_turn_counter,
    _build_banner,
    _build_compact_banner,
    _build_coordination_banner,
    _build_drift_banner,
    _build_due_banner,
    _build_git_banner,
    _build_health_banner,
    _build_review_banner,
    _build_roadmap_banner,
    _build_task_header,
    _build_tts_banner,
    _cached_or_fresh,
    _get_last_user_message,
    _has_plan_keywords,
    _hook_cache,
    _last_task_id,
    invalidate_hook_cache,
)
from .breaker import (
    _BREAKER_CRITICAL_PREFIXES,
    _BREAKER_TTL,
    _breaker_state,
    _build_breaker_banner,
    _check_breaker,
    _set_breaker,
)
