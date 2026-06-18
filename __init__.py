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

logger = logging.getLogger("plan_follow")

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
        "Before completing, checks git diff for drift. "
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
    "plan_update": (
        "Update a task's properties without aborting the plan. "
        "Parameters:\n"
        "- task_id (str, required): The task ID to update\n"
        "- changes (dict, required): Fields to update (files, verify, depends_on, name)\n"
        "Use this for 'living document' scenario when new information surfaces."
    ),
}

PLAN_TOOLS = [
    ("plan_create", plan_tools.plan_create_tool),
    ("plan_current", plan_tools.plan_current_tool),
    ("plan_complete", plan_tools.plan_complete_tool),
    ("plan_verify", plan_tools.plan_verify_tool),
    ("plan_status", plan_tools.plan_status_tool),
    ("plan_update", plan_tools.plan_update_tool),
]

PLAN_FOLLOW_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "description": "The plan goal"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "verify": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "task_id": {"type": "string", "description": "Task identifier"},
        "changes": {"type": "object", "description": "Fields to update on a task"},
        "repo": {"type": "string", "description": "Git repo path"},
    },
}

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
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "name"],
                },
                "description": "Liste der Tasks",
            },
            "repo": {"type": "string", "description": "Pfad zum Git-Repo (optional)"},
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
    "plan_update": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID des zu aktualisierenden Tasks"},
            "changes": {
                "type": "object",
                "description": "Zu ändernde Felder (files, verify, depends_on, name)",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}},
                    "verify": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "name": {"type": "string"},
                },
            },
        },
        "required": ["task_id", "changes"],
    },
}


def _register_tools(ctx: PluginContext) -> None:
    """Register all 6 plan tools."""
    for name, handler in PLAN_TOOLS:
        schema = PER_TOOL_SCHEMAS.get(name, PLAN_FOLLOW_TOOL_SCHEMA)
        ctx.register_tool(
            name=name,
            toolset="plan_follow",
            schema=schema,
            handler=handler,
            description=TOOL_DESCRIPTIONS.get(name, ""),
        )
    logger.info("plan_follow: 6 tools registered (plan_create/current/complete/verify/status/update)")


def _register_hooks(ctx: PluginContext) -> None:
    """Register pre_llm_call hook for task injection and health check."""
    from .plan_hooks import on_pre_llm_call
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    logger.info("plan_follow: pre_llm_call hook registered")


def _register_skill(ctx: PluginContext) -> None:
    """Register the companion skill."""
    skill_dir = Path(__file__).parent / "skills"
    skill_path = skill_dir / "plan-follow.md"
    if skill_path.exists():
        ctx.register_skill(
            name="plan-follow",
            path=skill_path,
            description="Plan-Follow: task enforcement via plan_create/current/complete/verify/status/update tools",
        )


def _inject_steering_hints() -> None:
    """Add usage hints to existing tool descriptions (like code_intel does)."""
    from tools.registry import registry
    hints = [
        ("todo", "\n\nFor plan-aware task tracking with dependency enforcement, use plan_create + plan_current instead of todo alone. todo is for simple lists, plan_follow tools enforce task order and scope."),
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
