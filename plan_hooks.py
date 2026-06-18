"""
plan_hooks.py — pre_llm_call hook for plan-follow plugin.

Injects into EVERY user message before the LLM processes it:
1. Current task banner (if a plan is active)
2. Drift warnings (if unplanned changes detected)
3. Health check (if systems are degraded)
"""

import logging
from typing import Any, Optional

from . import plan_core

logger = logging.getLogger("plan_follow")


def on_pre_llm_call(**kwargs: Any) -> Optional[str]:
    """Pre-LLM-call hook: inject plan context into user message.

    Registered via PluginContext.register_hook("pre_llm_call", ...).
    The return value is appended to the user message before it reaches the LLM.
    """

    # ─── 1. Health Check ───────────────────────────────────────────────────
    try:
        health = plan_core.health_check()
        if health["status"] == "degraded":
            lines = [
                "╔═══════════════════════════════════════════╗",
                "║  SYSTEM HEALTH CHECK FAILED              ║",
            ]
            for issue in health["issues"]:
                lines.append(f"║  🔴 {issue}")
            lines.append("║                                       ║")
            lines.append("║  Arbeiten nicht möglich. Admin        ║")
            lines.append("║  informieren.                         ║")
            lines.append("╚═══════════════════════════════════════════╝")
            return "[PLAN] " + "\n[PLAN] ".join(lines)
    except Exception as e:
        logger.warning(f"Health check in hook failed: {e}")

    # ─── 2. Active Plan → Task Banner ──────────────────────────────────────
    try:
        current = plan_core.get_current_task()
        if current:
            lines = [
                "╔═══════════════════════════════════════════╗",
                f"║  CURRENT TASK: {current['task_id']} — {current['name'][:50]}",
                f"║  Files: {', '.join(current['files'][:3])}" +
                (" ..." if len(current['files']) > 3 else ""),
                f"║  Progress: {current['progress']}",
            ]

            # ─── 3. Drift Check (fast, non-blocking) ──────────────────────
            try:
                drift = plan_core.check_drift()
                if drift:
                    lines.append("║                                       ║")
                    lines.append("║  ⚠️  DRIFT DETECTED                   ║")
                    for f in drift[:3]:
                        lines.append(f"║    {f[:60]}")
                    if len(drift) > 3:
                        lines.append(f"║    ... und {len(drift)-3} weitere")
                    lines.append("║                                       ║")
                    lines.append("║  → plan_update() oder revert          ║")
            except Exception:
                pass  # Drift check is best-effort

            lines.append("╚═══════════════════════════════════════════╝")
            return "[PLAN] " + "\n[PLAN] ".join(lines)
    except Exception as e:
        logger.warning(f"Task banner injection failed: {e}")

    # ─── 4. No Active Plan → try Honcho recovery ──────────────────────────
    try:
        # Check if there's a plan in Honcho that we haven't loaded
        if not plan_core._get_active_plan():
            plan_id = plan_core._load_plan_state_from_honcho()
            if plan_id and plan_core.set_active_plan(plan_id):
                # Plan successfully restored, show recovery banner
                current = plan_core.get_current_task()
                if current:
                    lines = [
                        "╔═══════════════════════════════════════════╗",
                        "║  VORHERIGE SESSION UNTERBROCHEN          ║",
                        f"║  Plan: {plan_id[:50]}",
                        f"║  Aufgabe: {current['name'][:50]}",
                        f"║  Status: {current['status']}",
                        "║                                       ║",
                        "║  → Mit plan_current() fortfahren       ║",
                        "╚═══════════════════════════════════════════╝",
                    ]
                    return "[PLAN] " + "\n[PLAN] ".join(lines)
    except Exception as e:
        logger.warning(f"Honcho plan recovery failed: {e}")

    return None  # Nothing to inject
