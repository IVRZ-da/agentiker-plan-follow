"""
plan_follow plugin — Hermes Plugin for plan creation, execution enforcement,
and cross-session plan persistence via Honcho.

Register via plugins.enabled: [agentiker_code_intel, plan_follow]
"""

import logging
from pathlib import Path
from hermes_cli.plugins import PluginContext

from . import plan_core
from . import plan_tools
from . import plan_todo

logger = logging.getLogger("plan_follow")

# Zentral definierte Review-Profile — nicht duplizieren!
VALID_REVIEW_PROFILES = ["none", "unit-test", "api-route", "ui-component", "security", "full"]
VALID_REVIEW_PROFILES_WITH_AUTO = ["auto"] + VALID_REVIEW_PROFILES

TOOL_DESCRIPTIONS = {
    "plan_create": (
        "Create a new structured plan with enforceable tasks. "
        "Parameters:\n"
        "- goal (str, required): The goal of the plan\n"
        "- tasks (array, required): List of task objects, each with:\n"
        "  - id (str): Task identifier (e.g. 'p1', 'phase-a')\n"
        "  - name (str): Human-readable task name\n"
        "  - files (array of str, optional): Files this task is allowed to change\n"
        "  - verify (str, optional): Shell command to verify task completion\n"
        "  - depends_on (array of str, optional): Task IDs that must be completed first\n"
        "- repo (str, optional): Git repo path for drift detection\n"
        "- template (str, optional): Template name (deploy|bugfix|feature|refactoring|research|analysis)\n"
        "- params (dict, optional): Template parameter substitution for {{placeholders}}\n"
        "- parallel_groups (dict, optional): Parallel task groups. "
        "Keys are group IDs, values are {'tasks': ['id1', 'id2', ...]}. "
        "Groups run sequentially — all tasks in a group run in parallel. "
        "Example: {'g1': {'tasks': ['p1','p2']}, 'g2': {'tasks': ['p3']}}\n"
        "Returns: plan_id and current_task."
    ),
    "plan_current": (
        "Show the current task. ONLY ONE task is returned at a time — "
        "you see only what needs to be done now. "
        "Returns task details including allowed files, verification command, and progress."
    ),
    "plan_complete": (
        "Complete the current task, verify it, advance to the next one. "
        "Parameters:\n"
        "- task_id (str, required): The task ID to complete\n"
        "- skip_review (bool, optional): Skip review gate (default: false)\n"
        "- auto_verify (bool, optional): Run the task's verify command automatically (default: false)\n"
        "- auto_commit (bool, optional): Git-commit task files after completion (default: false)\n"
        "Before completing, checks review gate, runs auto-verify (if enabled), and checks git diff for drift. "
        "Returns verification results and the next task to work on."
    ),
    "plan_verify": (
        "Check for drift: compare current git changes against the plan's task scope. "
        "Returns list of unplanned files if drift detected. "
        "Call this before plan_complete to catch scope creep."
    ),
    "plan_status": (
        "Show all tasks with their current status (pending/in_progress/completed/blocked). "
        "Returns a progress overview with counts and blocked-by reasons."
    ),
    "plan_todo": (
        "Manage your task list for the active plan. "
        "Replaces the built-in `todo` tool.\n"
        "Read mode (no parameters):\n"
        "- Returns ALL tasks of the active plan as a compact todo list.\n"
        "- Output: {todos: [...], summary: {total, pending, in_progress, completed, cancelled}}\n"
        "Write mode (todos + merge=true):\n"
        "- Set status to 'completed' → completes the task via plan_complete\n"
        "- Other status changes are ignored (plan manages status internally)\n"
    ),
    "plan_update": (
        "Update a task's properties without aborting the plan. "
        "Parameters:\n"
        "- task_id (str, required): The task ID to update\n"
        "- changes (dict, required): Fields to update (files, verify, depends_on, name, review_profile)\n"
        "Use this for 'living document' scenario when new information surfaces."
    ),
    "plan_auto_review": (
        "Prepare a complete review in one call — reads files, measures test coverage, "
        "and builds the delegate_task prompt. "
        "Parameters:\n"
        "- task_id (str, required): The task ID to review\n"
        "- profile (str, optional): Review profile (auto|none|unit-test|api-route|ui-component|security|full). Default: auto\n"
        "- depth (str, optional): Review depth (quick|normal|deep). Default: normal\n"
        "Returns:\n"
        "- status 'ready' → run delegate_task with the 'prompt' field\n"
        "- status 'coverage_failed' → coverage too low, write more tests first\n"
        "- status 'skipped' → no review needed"
    ),
    "plan_review": (
        "Review a task's files using an independent reviewer subagent. "
        "Parameters:\n"
        "- task_id (str, required): The task ID to review\n"
        "- profile (str, optional): Review profile (auto|none|unit-test|api-route|ui-component|security|full). Default: auto\n"
        "- depth (str, optional): Review depth (quick|normal|deep). Default: normal\n"
        "Returns JSON with review status, checks, and result. "
        "The actual review is performed via delegate_task — use build_review_prompt() for the prompt."
    ),
    "plan_review_profiles": (
        "Show all available review profiles with their names, descriptions, and checks. "
        "Use this to see what each profile validates before selecting one for a task."
    ),
    "plan_list": (
        "List all plans (including completed and aborted ones), newest first. "
        "Returns plan_id, goal, progress, and whether each plan is currently active. "
        "Use this to see what plans exist before calling plan_select()."
    ),
    "plan_abort": (
        "Abort the active plan or a specific task. "
        "Parameters:\n"
        "- task_id (str, optional): If provided, abort only this task. Otherwise abort the entire plan.\n"
        "Aborted tasks get status 'aborted' and are skipped in progress tracking. "
        "Use plan_create() to start a fresh plan after aborting."
    ),
    "plan_delete": (
        "Permanently delete a plan from disk. "
        "Parameters:\n"
        "- plan_id (str, required): The plan ID to delete.\n"
        "If the deleted plan was active, the active plan is cleared. "
        "This cannot be undone."
    ),
    "plan_select": (
        "Switch to a different saved plan as the active one. "
        "Parameters:\n"
        "- plan_id (str, required): The plan ID to activate.\n"
        "After selecting, call plan_current() to see the current task. "
        "Use plan_list() first to see available plans."
    ),
    "plan_validate": (
        "Validate the integrity of a plan. "
        "Parameters:\n"
        "- plan_id (str, optional): Plan ID to validate. If empty, validates the active plan.\n"
        "Checks: depends_on references exist, no circular dependencies, "
        "verify commands valid, parallel_groups tasks exist, review profiles valid, "
        "no orphan tasks."
    ),
    "plan_duedate": (
        "Set or view a due date for a task. "
        "Parameters:\n"
        "- task_id (str, optional): Task ID. If empty, shows current task's due date.\n"
        "- due (str, optional): ISO-8601 date (e.g. '2026-06-25'). "
        "Omit to view current due date. Pass empty string to clear.\n"
        "The pre_llm_call hook shows a 🟡 DEADLINE SOON or 🔴 DEADLINE OVERDUE warning."
    ),
    "plan_archive": (
        "Move a plan to the archive directory (soft delete). "
        "Parameters:\n"
        "- plan_id (str, required): The plan ID to archive.\n"
        "Archived plans can be listed with plan_list(include_archived=true) "
        "and restored with plan_restore()."
    ),
    "plan_restore": (
        "Restore a plan from the archive back to the plans directory. "
        "Parameters:\n"
        "- plan_id (str, required): The plan ID to restore.\n"
        "Use plan_list(include_archived=true) to find archived plans."
    ),
}

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
    ("plan_list", plan_tools.plan_list_tool),
    ("plan_abort", plan_tools.plan_abort_tool),
    ("plan_delete", plan_tools.plan_delete_tool),
    ("plan_select", plan_tools.plan_select_tool),
    ("plan_validate", plan_tools.plan_validate_tool),
    ("plan_duedate", plan_tools.plan_duedate_tool),
    ("plan_archive", plan_tools.plan_archive_tool),
    ("plan_restore", plan_tools.plan_restore_tool),
]

# Per-tool schemas for each individual tool
PER_TOOL_SCHEMAS = {
    "plan_create": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Das Ziel des Plans"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "files": {"type": "array", "items": {"type": "string"}},
                        "verify": {"type": "string"},
                        "review_profile": {
                            "type": "string",
                            "enum": VALID_REVIEW_PROFILES,
                            "description": "Review-Profil (optional, default: none)",
                        },
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "name"],
                },
                "description": "Liste der Tasks",
            },
            "template": {
                "type": "string",
                "enum": ["deploy", "bugfix", "feature", "refactoring", "research", "analysis"],
                "description": "Template-Name (optional). Erzeugt automatisch Tasks aus der Vorlage.",
            },
            "repo": {"type": "string", "description": "Pfad zum Git-Repo (optional)"},
            "parallel_groups": {
                "type": "object",
                "description": "Optionale parallele Gruppen. Jeder Key ist eine Gruppen-ID, Value ist {\"tasks\": [task_id, ...]}. Gruppen werden sequentiell verarbeitet — alle Tasks einer Gruppe laufen parallel.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "tasks": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tasks"],
                },
            },
            "params": {
                "type": "object",
                "description": "Optionale Parameter fuer Template-Placeholders {{var}}. Bsp: {\"env\": \"staging\"}",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["goal", "tasks"],
    },
    "plan_current": {
        "type": "object",
        "properties": {},
    },
    "plan_complete": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID des abzuschliessenden Tasks"},
            "skip_review": {"type": "boolean", "description": "Review-Gate überspringen (default: false)"},
            "auto_verify": {"type": "boolean", "description": "verify-Command automatisch ausführen (default: false)"},
            "auto_commit": {"type": "boolean", "description": "Git-Commit nach Abschluss (default: false)"},
        },
        "required": ["task_id"],
    },
    "plan_verify": {
        "type": "object",
        "properties": {},
    },
    "plan_status": {
        "type": "object",
        "properties": {},
    },
    "plan_todo": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Task items to write. Omit to read current list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Task identifier"},
                        "content": {"type": "string", "description": "Task description"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "New status (completed → plan_complete)",
                        },
                    },
                },
            },
            "merge": {
                "type": "boolean",
                "description": "true: update existing items. false: read mode (default).",
                "default": False,
            },
        },
    },
    "plan_update": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID des zu aktualisierenden Tasks"},
            "changes": {
                "type": "object",
                "description": "Zu ändernde Felder (files, verify, depends_on, name, review_profile)",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}},
                    "verify": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "name": {"type": "string"},
                    "review_profile": {
                        "type": "string",
                        "enum": VALID_REVIEW_PROFILES,
                    },
                },
            },
        },
        "required": ["task_id", "changes"],
    },
    "plan_auto_review": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID zum Reviewen"},
            "profile": {
                "type": "string",
                "enum": VALID_REVIEW_PROFILES_WITH_AUTO,
                "description": "Review-Profil (auto = aus Task, sonst override)",
                "default": "auto",
            },
            "depth": {
                "type": "string",
                "enum": ["quick", "normal", "deep"],
                "description": "Review-Tiefe (default: normal)",
                "default": "normal",
            },
        },
        "required": ["task_id"],
    },
    "plan_review": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID zum Reviewen"},
            "profile": {
                "type": "string",
                "enum": VALID_REVIEW_PROFILES_WITH_AUTO,
                "description": "Review-Profil (auto = aus Task, sonst override)",
                "default": "auto",
            },
            "depth": {
                "type": "string",
                "enum": ["quick", "normal", "deep"],
                "description": "Review-Tiefe (default: normal)",
                "default": "normal",
            },
        },
        "required": ["task_id"],
    },
    "plan_review_profiles": {
        "type": "object",
        "properties": {},
    },
    "plan_list": {
        "type": "object",
        "properties": {},
    },
    "plan_abort": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID to abort (optional — aborts whole plan if omitted)"},
        },
    },
    "plan_delete": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des zu löschenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_select": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des zu aktivierenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_validate": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Plan-ID zum Validieren (optional — ohne wird der aktive Plan validiert)"},
        },
    },
    "plan_duedate": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task-ID (optional — ohne wird der aktuelle Task verwendet)"},
            "due": {"type": "string", "description": "ISO-8601 Datum (z.B. '2026-06-25') zum Setzen. Ohne: View-Mode. Leerstring: Löschen."},
        },
    },
    "plan_archive": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des zu archivierenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_restore": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des wiederherzustellenden Plans"},
        },
        "required": ["plan_id"],
    },
}


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
    logger.info("plan_follow: 18 tools registered (plan_create/current/complete/verify/status/todo/update/review/auto_review/review_profiles/list/abort/delete/select/validate/duedate/archive/restore)")


def _register_hooks(ctx: PluginContext) -> None:
    """Register pre_llm_call hook for task injection and post_tool_call for logging."""
    from .plan_hooks import on_pre_llm_call, on_post_tool_call
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    logger.info("plan_follow: pre_llm_call + post_tool_call hooks registered")


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


def _inject_steering_hints() -> None:
    """Add usage hints to existing tool descriptions (like code_intel does).
    Also deregisters the built-in `todo` tool since plan_todo replaces it.
    """
    from tools.registry import registry

    # Deregister built-in todo tool — plan_todo ersetzt es
    try:
        registry.deregister("todo")
        logger.info("plan_follow: built-in 'todo' tool deregistered (replaced by plan_todo)")
    except Exception as e:
        logger.warning("plan_follow: could not deregister 'todo': %s", e)

    hints = [
        ("plan_create", "\n\nAfter creating a plan, call plan_current() to see the first task. Complete tasks in order: plan_complete(task_id) when done, then plan_current() shows the next one."),
    ]
    for tool_name, hint_text in hints:
        entry = registry.get_entry(tool_name)
        if entry and "description" in entry.schema and hint_text not in entry.schema.get("description", ""):
            entry.schema["description"] = entry.schema.get("description", "") + hint_text


def register(ctx: PluginContext) -> None:
    """Plugin entry point."""
    _register_tools(ctx)
    _register_hooks(ctx)
    _register_skill(ctx)
    _inject_steering_hints()
    logger.info("plan_follow plugin registered successfully")
