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
    plan_core,  # noqa: F401
    plan_todo,
    plan_tools,
)
from .tools.descriptions import TOOL_DESCRIPTIONS

logger = logging.getLogger("plan_follow")

# Zentral definierte Review-Profile — nicht duplizieren!
VALID_REVIEW_PROFILES = ["none", "unit-test", "api-route", "ui-component", "security", "full"]
VALID_REVIEW_PROFILES_WITH_AUTO = ["auto"] + VALID_REVIEW_PROFILES


# Muss nach den VALID_REVIEW_PROFILES stehen: tools/schemas.py importiert sie aus
# diesem Modul (Zirkularitaet), daher E402.
from .tools.schemas import PER_TOOL_SCHEMAS  # noqa: E402

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
    ("plan_coord_cleanup", plan_tools.plan_coord_cleanup_tool),
]



def _register_tools(ctx: PluginContext) -> None:
    """Register all plan tools.

    Schema-Fix: PER_TOOL_SCHEMAS hat ``type/properties/required`` auf
    Top-Level (JSON-Schema-Stil), aber das OpenAI-Format braucht diese
    Felder unter ``parameters``.  Ohne den Wrapper ersetzt
    ``sanitize_tool_schemas()`` die Parameters durch ``{}`` — das Model
    sieht dann keine Parameter und sendet leere/toolche Arguments.
    """
    for name, handler in PLAN_TOOLS:
        raw = PER_TOOL_SCHEMAS.get(name, {})
        # Wrap into OpenAI function-call format if needed
        if "parameters" not in raw and "properties" in raw:
            schema = {
                "name": name,
                "description": TOOL_DESCRIPTIONS.get(name, ""),
                "parameters": {
                    "type": raw.get("type", "object"),
                    "properties": raw.get("properties", {}),
                    **({"required": raw["required"]} if "required" in raw else {}),
                },
            }
        else:
            schema = raw
        ctx.register_tool(
            name=name,
            toolset="plan_follow",
            schema=schema,
            handler=handler,
            description=TOOL_DESCRIPTIONS.get(name, ""),
        )
    logger.info("plan_follow: %d tools registered", len(PLAN_TOOLS))


def _valid_hook_names() -> set:
    """Namen der in dieser Hermes-Installation gueltigen Hooks (leer = unbekannt).

    Liest das ``VALID_HOOKS``-Literal per AST aus ``hermes_cli/plugins.py`` statt
    es zu importieren: ein Import privater Hermes-Interna bricht bei jedem
    Release (und der Plugin-Validator warnt dafuer). Faellt die Analyse aus, ist
    das Ergebnis leer — dann wird nicht validiert (fail-open, wie vorher).
    """
    try:
        import ast
        import os as _os

        hermes_home = Path(_os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
        candidates = [
            Path(__file__).resolve().parents[2] / "hermes-agent" / "hermes_cli" / "plugins.py",
            hermes_home / "hermes-agent" / "hermes_cli" / "plugins.py",
        ]

        for candidate in candidates:
            if not candidate.is_file():
                continue
            tree = ast.parse(candidate.read_text(encoding="utf-8", errors="replace"))
            for node in tree.body:
                targets: list = []
                value = None
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, ast.AnnAssign):
                    targets, value = [node.target], node.value
                if not any(isinstance(t, ast.Name) and t.id == "VALID_HOOKS" for t in targets):
                    continue
                if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
                    return {
                        elt.value for elt in value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }
        return set()
    except Exception:
        return set()


# Wird bei jedem Plugin-Load gefuellt; Health-Check und Tests pruefen darauf.
HOOK_REGISTRATION_ERRORS: list[str] = []


def _register_hooks(ctx: PluginContext) -> None:
    """Register hooks for task injection, logging, and session lifecycle.

    Hook-Namen werden gegen die Hermes-VALID_HOOKS-Liste geprueft. Vor v0.5.32
    verschluckte ein ``except Exception`` den falschen Namen ``session_end`` —
    der Hook wurde bei jeder Session stillschweigend nicht ausgefuehrt und bei
    jedem Load nur mit einer WARNING quittiert.
    """
    from .plan_hooks import on_post_tool_call, on_pre_llm_call, on_session_end

    hook_pairs = [
        ("pre_llm_call", on_pre_llm_call),
        ("post_tool_call", on_post_tool_call),
        ("on_session_end", on_session_end),
    ]
    valid = _valid_hook_names()
    HOOK_REGISTRATION_ERRORS.clear()

    for name, callback in hook_pairs:
        if valid and name not in valid:
            msg = (
                f"Hook '{name}' ist in dieser Hermes-Version unbekannt "
                f"({len(valid)} gueltige Hooks) — Hook wird nicht registriert."
            )
            HOOK_REGISTRATION_ERRORS.append(msg)
            logger.error("plan_follow: %s", msg)
            continue
        ctx.register_hook(name, callback)

    registered = len(hook_pairs) - len(HOOK_REGISTRATION_ERRORS)
    if HOOK_REGISTRATION_ERRORS:
        logger.error(
            "plan_follow: %d/%d hooks registriert (%d ungueltig)",
            registered, len(hook_pairs), len(HOOK_REGISTRATION_ERRORS),
        )
    else:
        logger.info("plan_follow: %d hooks registriert (pre_llm_call, post_tool_call, on_session_end)", registered)


def _register_skill(ctx: PluginContext) -> None:
    """Register the companion skill.

    Vor v0.5.32 wurde hier ausschliesslich ``skills/plan-follow.md`` geprueft —
    die Datei heisst real ``skills/SKILL.md``. Folge: der Companion-Skill wurde
    bei jedem Load stillschweigend NICHT registriert (kein Warning, kein Fehler).
    """
    skill_dir = Path(__file__).parent / "skills"
    skill_path = next(
        (p for p in (skill_dir / "SKILL.md", skill_dir / "plan-follow.md") if p.exists()),
        None,
    )
    if skill_path is None:
        logger.error(
            "plan_follow: Companion-Skill nicht gefunden in %s (erwartet SKILL.md)", skill_dir
        )
        return

    ctx.register_skill(
        name="plan-follow",
        path=skill_path,
        description="Plan-Follow: task enforcement via plan_create/current/complete/verify/status/todo/update tools",
    )
    logger.info("plan_follow: Companion-Skill registriert (%s)", skill_path.name)


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
    _register_tools(ctx)
    _register_hooks(ctx)
    _register_skill(ctx)
    _inject_steering_hints()
    logger.info("plan_follow plugin registered successfully")
