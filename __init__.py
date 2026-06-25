"""
plan_follow plugin — Hermes Plugin for plan creation, execution enforcement,
and cross-session plan persistence via Honcho.

Register via plugins.enabled: [agentiker_code_intel, plan_follow]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.plugins import PluginContext

from . import (
    hooks,  # noqa: F401 — subpackage, geladen für plan_hooks.py Imports
    plan_core,  # noqa: F401
    plan_todo,
    plan_tools,
)

logger = logging.getLogger("plan_follow")

# Zentral definierte Review-Profile — nicht duplizieren!
VALID_REVIEW_PROFILES = ["none", "unit-test", "api-route", "ui-component", "security", "full"]
VALID_REVIEW_PROFILES_WITH_AUTO = ["auto"] + VALID_REVIEW_PROFILES
# TOOL_DESCRIPTIONS ausgelagert in tools/descriptions.py
from .tools.descriptions import TOOL_DESCRIPTIONS  # noqa: E402, F811

# PER_TOOL_SCHEMAS ausgelagert in tools/schemas.py
from .tools.schemas import PER_TOOL_SCHEMAS  # noqa: E402, F811

PLAN_TOOLS = [
    ("plan_create", plan_tools.plan_create_tool),
    ("plan_current", plan_tools.plan_current_tool),
    ("plan_complete", plan_tools.plan_complete_tool),
    ("plan_verify", plan_tools.plan_verify_tool),
    ("plan_status", plan_tools.plan_status_tool),
    ("plan_todo", plan_todo.plan_todo_tool),
    ("plan_update", plan_tools.plan_update_tool),
    ("plan_review", plan_tools.plan_review_tool),
    ("plan_auto_review", plan_tools.plan_auto_review_tool),
    ("plan_review_profiles", plan_tools.plan_review_profiles_tool),
    ("plan_review_save_result", plan_tools.plan_review_save_result_tool),
    ("plan_template", plan_tools.plan_template_tool),
    ("plan_suggest", plan_tools.plan_suggest_tool),
    ("plan_time", plan_tools.plan_time_tool),
    ("plan_simulate", plan_tools.plan_simulate_tool),
    ("plan_sync", plan_tools.plan_sync_tool),
    ("plan_decompose", plan_tools.plan_decompose_tool),
    ("plan_list", plan_tools.plan_list_tool),
    ("plan_abort", plan_tools.plan_abort_tool),
    ("plan_delete", plan_tools.plan_delete_tool),
    ("plan_select", plan_tools.plan_select_tool),
    ("plan_validate", plan_tools.plan_validate_tool),
    ("plan_duedate", plan_tools.plan_duedate_tool),
    ("plan_archive", plan_tools.plan_archive_tool),
    ("plan_restore", plan_tools.plan_restore_tool),
    ("plan_roadmap", plan_tools.plan_roadmap_handler),
    ("plan_session", plan_tools.plan_session_tool),
    ("plan_lock", plan_tools.plan_lock_tool),
    ("plan_notify", plan_tools.plan_notify_tool),
    ("plan_history", plan_tools.plan_history_tool),
    ("plan_git_init", plan_tools.plan_git_init_tool),
    ("plan_git_push", plan_tools.plan_git_push_tool),
    ("plan_git_status", plan_tools.plan_git_status_tool),
    ("plan_git_sync", plan_tools.plan_git_sync_tool),
    ("plan_git_stash", plan_tools.plan_git_stash_tool),
    ("plan_git_branch", plan_tools.plan_git_branch_tool),
    ("plan_git_tag", plan_tools.plan_git_tag_tool),
    ("plan_pr_create", plan_tools.plan_pr_create_tool),
]

# Per-tool schemas for each individual tool


def _register_tools(ctx: PluginContext) -> None:
    """Register all 6 plan tools."""
    for name, handler in PLAN_TOOLS:
        schema = PER_TOOL_SCHEMAS.get(name, {})
        ctx.register_tool(
            name=name,
            toolset="plan_follow",
            schema=schema,
            handler=handler,
            description=TOOL_DESCRIPTIONS.get(name, ""),
        )
    logger.info("plan_follow: %d tools registered", len(PLAN_TOOLS))


def _register_hooks(ctx: PluginContext) -> None:
    """Register pre_llm_call, post_tool_call, and on_session_end hooks."""
    from .plan_hooks import on_post_tool_call, on_pre_llm_call, on_session_end
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("on_session_end", on_session_end)
    logger.info("plan_follow: pre_llm_call + post_tool_call + on_session_end hooks registered")


def _register_skill(ctx: PluginContext) -> None:
    """Register the companion skill."""
    skill_dir = Path(__file__).parent / "skills"
    skill_path = skill_dir / "plan-follow.md"
    if skill_path.exists():
        ctx.register_skill(
            name="plan-follow",
            path=skill_path,
            description="Plan-Follow: task enforcement via plan_create/current/complete/verify/status/todo/update tools",
        )


def _ensure_deps() -> None:
    """Auto-install fehlender Dependencies beim ersten Plugin-Start."""
    import importlib
    import logging
    import subprocess
    import sys

    logger = logging.getLogger(__name__)

    missing: list[str] = []
    for pkg_name, import_name in [
        ("PyYAML", "yaml"),
        ("rich", "rich"),
    ]:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pkg_name)

    if not missing:
        return

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install"] + missing,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("✅ Dependencies auto-installiert: %s", missing)
        return
    except Exception:
        pass

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--user"] + missing,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("✅ Dependencies via --user installiert: %s", missing)
        return
    except Exception as e:
        logger.error(
            "❌ Auto-Install fehlgeschlagen: %s. Manuell: %s -m pip install %s",
            e,
            sys.executable,
            " ".join(missing),
        )


def _inject_steering_hints() -> None:
    """Add usage hints to existing tool descriptions (like code_intel does).
    Also deregisters the built-in `todo` tool since plan_todo replaces it.
    """
    try:
        from tools.registry import registry

        registry.deregister("todo")
        logger.info("plan_follow: built-in 'todo' tool deregistered (replaced by plan_todo)")

        hints = [
            ("plan_create", "\n\nAfter creating a plan, call plan_current() to see the first task. Complete tasks in order: plan_complete(task_id) when done, then plan_current() shows the next one."),
        ]
        for tool_name, hint_text in hints:
            entry = registry.get_entry(tool_name)
            if entry and "description" in entry.schema and hint_text not in entry.schema.get("description", ""):
                entry.schema["description"] = entry.schema.get("description", "") + hint_text
    except ImportError:
        logger.warning("plan_follow: could not import tools.registry — todo deregistration + hints skipped")
    except Exception as e:
        logger.warning("plan_follow: could not deregister 'todo': %s", e)


def register(ctx: PluginContext) -> None:
    """Plugin entry point."""
    _ensure_deps()
    _register_tools(ctx)
    _register_hooks(ctx)
    _register_skill(ctx)
    _inject_steering_hints()
    logger.info("plan_follow plugin registered successfully")
