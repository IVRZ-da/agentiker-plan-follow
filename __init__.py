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

logger = logging.getLogger("plan_follow")

# Zentral definierte Review-Profile — nicht duplizieren!
VALID_REVIEW_PROFILES = ["none", "unit-test", "api-route", "ui-component", "security", "full"]
VALID_REVIEW_PROFILES_WITH_AUTO = ["auto"] + VALID_REVIEW_PROFILES

TOOL_DESCRIPTIONS = {
    "plan_create": (
        "Create a new structured plan with enforceable tasks. "
        "TEMPLATE IS REQUIRED — manual tasks are not allowed. "
        "Parameters:\n"
        "- goal (str, required): The goal of the plan. Used for plan_id if plan_id not provided.\n"
        "- template (str, required): Template name (deploy|bugfix|feature|refactoring|research|analysis|docs|infrastructure|go-setup|security|multi)\n"
        "- params (dict, optional): Template parameter substitution for {{placeholders}}. "
        "Use params={'tasks': [...]} for the 'multi' template to define custom tasks.\n"
        "- plan_id (str, optional): Custom plan ID. If provided, used instead of auto-generated ID from goal.\n"
        "- repo (str, optional): Git repo path for drift detection\n"
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
        "- auto_retry (int, optional): Auto-retry verify up to N times on failure (default: 0)\n"
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
        "- changes (dict, required): Fields to update (files, verify, depends_on, name, review_profile, parallel_groups)\n"
        "parallel_groups is a plan-level change — updates the parallel group structure. "
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
    "plan_review_save_result": (
        "Save a review result for a task. "
        "Parameters:\n"
        "- task_id (str, required): The task ID\n"
        "- status (str, optional): 'passed' (default) or 'failed'\n"
        "- issues (list, optional): List of issue dicts\n"
        "- summary (str, optional): Review summary text\n"
        "Persists the result so plan_complete() can pass the review gate. "
        "Call this AFTER running a review via delegate_task."
    ),
    "plan_template": (
        "Manage user-defined plan templates. "
        "Parameters:\n"
        "- action (str, required): 'list', 'detail', 'save', or 'delete'\n"
        "- name (str, optional): Template name (required for detail/save/delete)\n"
        "- tasks (list, optional): List of task dicts (required for save)\n"
        "- description (str, optional): Template description (for save)\n"
        "- review_profile (str, optional): Review profile (for save, default: none)\n"
        "User templates are stored as YAML in ~/.hermes/plans/templates/."
    ),
    "plan_suggest": (
        "Suggest a plan decomposition for a goal by analyzing the project. "
        "Parameters:\n"
        "- goal (str, required): The goal to generate suggestions for.\n"
        "- project_root (str, optional): Project root path.\n"
        "Scans project type, frameworks, and matching patterns to suggest "
        "an appropriate template and task list. Use the output with plan_create()."
    ),
    "plan_time": (
        "Track time spent on tasks. "
        "Parameters:\n"
        "- action (str, required): 'start', 'stop', 'status', or 'history'\n"
        "- task_id (str, optional): Task ID\n"
        "- plan_id (str, optional): Plan ID\n"
        "Use start when beginning a task, stop when completing. "
        "History shows all tracked time entries."
    ),
    "plan_simulate": (
        "Simulate a plan to find critical path and parallelization opportunities. "
        "Parameters:\n"
        "- plan_id (str, optional): Plan ID to simulate (defaults to active plan).\n"
        "Analyzes the dependency graph, finds the critical path (longest chain), "
        "and suggests optimal parallelization. "
        "Use this BEFORE plan_create to optimize task ordering."
    ),
    "plan_sync": (
        "Sync plans with external systems. "
        "Parameters:\n"
        "- action (str, required): 'github', 'export', or 'import'\n"
        "- plan_id (str, optional): Plan ID (defaults to active plan)\n"
        "- repo (str, optional): GitHub repo (owner/repo, for github action)\n"
        "- markdown (str, optional): Markdown content (for import action)\n"
        "Sync creates GitHub Issues from plan tasks. "
        "Export produces Markdown. Import parses Markdown back to a plan."
    ),
    "plan_decompose": (
        "Manage hierarchical task decomposition (compound tasks with sub-tasks). "
        "Parameters:\n"
        "- action (str, required): 'expand', 'collapse', 'status', 'create', or 'delegate'\n"
        "- task_id (str, optional): Task ID for expand/collapse/status/delegate\n"
        "- name (str, optional): Compound task name for create\n"
        "- subtasks (list, optional): Sub-task definitions for create\n"
        "- delegate: Prepares a task for execution by a subagent via delegate_task.\n"
        "Compound tasks aggregate sub-task status. "
        "Expanded sub-tasks become top-level tasks with '_parent_task' marker."
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
    "plan_roadmap": (
        "Manage roadmaps — strategic phase overviews. "
        "Parameters:\n"
        "- action (str, required): One of: status, show, to_plan, set, list, create, update, edit-phase, add-phase, remove-phase, delete\n"
        "- name (str, optional): Roadmap name (without .yaml). Auto-selects most recent if omitted.\n"
        "- phase (str, optional): Phase ID for show/to_plan/set/edit-phase/remove-phase commands.\n"
        "- status (str, optional): New status for 'set'/'edit-phase' command (pending|in_progress|completed|blocked).\n"
        "- goal (str, optional): Roadmap-Ziel für 'create'/'update'.\n"
        "- phases (array, optional): Phase list for 'create'.\n"
        "- phase_data (dict, optional): Phase JSON-Objekt für 'add-phase'.\n"
        "- priority (str, optional): Neue Priorität für 'edit-phase' (high|medium|low).\n"
        "- effort (str, optional): Neuer Aufwand für 'edit-phase'.\n"
        "- impact (str, optional): Neuer Impact für 'edit-phase'.\n"
        "- tasks (array, optional): Tasks-Liste für 'edit-phase'.\n"
        "Also accepts cmd= as alias for action= (deprecated).\n"
        "Subcommands:\n"
        "  status      → Show roadmap overview with all phases\n"
        "  show        → Show detail of a single phase (requires phase=)\n"
        "  to_plan     → Convert phase to plan_create tasks (requires phase=)\n"
        "  set         → Update phase status (requires phase= + status=)\n"
        "  list        → List all available roadmaps\n"
        "  create      → Create a new roadmap (requires name= + phases=)\n"
        "  update      → Update roadmap metadata (name=, goal=)\n"
        "  edit-phase  → Update phase properties (phase= + name/priority/effort/impact/tasks/status)\n"
        "  add-phase   → Add a new phase (phase_data= as JSON dict, name= as roadmap name)\n"
        "  remove-phase → Remove a phase (phase=, name= as roadmap name)\n"
        "  delete      → Delete entire roadmap (name=)\n"
        "Example: plan_roadmap(action='status') → zeigt Phasen-Übersicht"
    ),
    "plan_session": (
        "Show active sessions with their plans, locks, and pending notifications. "
        "Parameters:\n"
        "- include_history (bool, optional): Show git-based plan history (default: false)\n"
        "Returns session IDs, plan IDs, goals, lock counts, and notification count. "
        "No Git required for basic session overview."
    ),
    "plan_lock": (
        "Manage resource locks for cross-session coordination. "
        "Parameters:\n"
        "- action (str, required): 'lock', 'unlock', or 'status'\n"
        "- path (str, required): File or directory path to lock/unlock\n"
        "- session_id (str, optional): Session ID (default: auto-detected)\n"
        "Prevents two sessions from editing the same file simultaneously. "
        "File-based, no Git required."
    ),
    "plan_notify": (
        "Send a notification to another session or check own notifications. "
        "Parameters:\n"
        "- action (str, required): 'send' or 'check'\n"
        "- to (str, optional): Target session ID (required for 'send')\n"
        "- message (str, optional): Message text (required for 'send')\n"
        "- kind (str, optional): 'info', 'warning', 'alert' (default: 'info')\n"
        "- session_id (str, optional): Session ID (optional)\n"
        "Notifications appear in the target session's Hook-Banner. "
        "No Git required."
    ),
    "plan_history": (
        "Show git-based plan version history. "
        "Parameters:\n"
        "- plan_id (str, optional): Plan ID. Defaults to current plan.\n"
        "- lines (int, optional): Number of log entries (default: 10)\n"
        "If Git is not active, shows a hint how to enable it. "
        "This is optional — plans work fine without Git."
    ),
    "plan_git_init": (
        "Initialize a Git repository in ~/.hermes/plans/ for plan versioning. "
        "Parameters:\n"
        "- commit_message (str, optional): Initial commit message\n"
        "Creates .gitignore, adds all existing plans, and makes an initial commit. "
        "Only needs to be called once. Plans work fine without Git."
        ),
        "plan_git_push": (
        "Push committed changes to remote for all configured repos. "
        "Parameters:\n"
        "- remote (str, optional): Remote name (default: origin)\n"
        "- branch (str, optional): Branch to push (default: current branch)\n"
        "Iterates over all repos configured in the current plan and runs git push. "
        "Returns per-repo results."
        ),
        "plan_git_status": (
        "Show comprehensive git status for all configured repos. "
        "Returns branch name, dirty flag, ahead/behind count, "
        "and last commit message for each repo."
        ),
        "plan_git_sync": (
        "Pull to add to commit to push in one step for all configured repos. "
        "Parameters:\n"
        "- remote (str, optional): Remote name (default: origin)\n"
        "- branch (str, optional): Branch to push (default: current branch)\n"
        "- push (bool, optional): Whether to push after commit (default: true)\n"
        "Handles the full sync cycle automatically. "
        "Skips commit if no changes detected."
        ),
        "plan_git_stash": (
        "Stash or unstash uncommitted changes in configured repos. "
        "Parameters:\n"
        "- action (str, required): 'push' (stash changes), 'pop' (restore latest), 'list' (show stashes)\n"
        "- message (str, optional): Stash description (push only)\n"
        "Useful before switching branches or pulling changes."
        ),
        "plan_git_branch": (
        "Manage git branches in configured repos. "
        "Parameters:\n"
        "- action (str, required): 'current', 'list', 'create', 'switch', 'delete'\n"
        "- name (str, optional): Branch name (for create/switch/delete)\n"
        "- start_point (str, optional): Start point for branch creation\n"
        "When switching branches, dirty changes are auto-stashed first."
        ),
        "plan_git_tag": (
        "Create, list, or delete git tags in configured repos. "
        "Parameters:\n"
        "- action (str, required): 'create', 'list', 'delete'\n"
        "- tag_name (str, optional): Tag name (required for create/delete)\n"
        "- message (str, optional): Tag annotation message (create only, creates annotated tag)\n"
        "Useful for marking releases or completed milestones."
        ),
        "plan_pr_create": (
        "Create a Pull Request via Forgejo API for all configured repos. "
        "Parameters:\n"
        "- title (str, required): PR title\n"
        "- body (str, optional): PR description\n"
        "- head (str, optional): Source branch (default: current branch)\n"
        "- base (str, optional): Target branch (default: main)\n"
        "- owner (str, optional): Repo owner (default: from git remote)\n"
        "- repo_name (str, optional): Repo name (default: from git remote)\n"
        "Uses BOT_FORGEJO_TOKEN or FORGEJO_TOKEN env var for auth. "
        "Auto-detects repo owner/name from git remote URL."
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
                "enum": ["deploy", "bugfix", "feature", "refactoring", "research", "analysis", "docs", "go-setup", "infrastructure", "security"],
                "description": "Template-Name (required — kein Template = kein Plan). Erzeugt automatisch Tasks aus der Vorlage.",
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
        "required": ["goal", "template"],
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
                "additionalProperties": False,
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
    "plan_review_save_result": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID"},
            "status": {"type": "string", "description": "'passed' or 'failed'", "default": "passed"},
            "issues": {"type": "array", "items": {"type": "object"}, "description": "List of issue dicts"},
            "summary": {"type": "string", "description": "Review summary text"},
        },
        "required": ["task_id"],
    },
    "plan_template": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "list, detail, save, or delete"},
            "name": {"type": "string", "description": "Template name (required for detail/save/delete)"},
            "tasks": {"type": "array", "description": "Task dicts for save action"},
            "description": {"type": "string", "description": "Template description"},
            "review_profile": {"type": "string", "description": "Review profile for template"},
        },
        "required": ["action"],
    },
    "plan_suggest": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "The goal to generate suggestions for"},
            "project_root": {"type": "string", "description": "Optional project root path"},
        },
        "required": ["goal"],
    },
    "plan_time": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "start, stop, status, or history"},
            "task_id": {"type": "string", "description": "Task ID"},
            "plan_id": {"type": "string", "description": "Plan ID"},
        },
        "required": ["action"],
    },
    "plan_simulate": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Plan ID (optional — defaults to active plan)"},
        },
    },
    "plan_sync": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "github, export, or import"},
            "plan_id": {"type": "string", "description": "Plan ID"},
            "repo": {"type": "string", "description": "GitHub repo (owner/repo)"},
            "markdown": {"type": "string", "description": "Markdown content for import"},
        },
        "required": ["action"],
    },
    "plan_decompose": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "expand, collapse, status, create, or delegate"},
            "task_id": {"type": "string", "description": "Task ID"},
            "name": {"type": "string", "description": "Compound task name for create"},
            "subtasks": {"type": "array", "description": "Sub-task definitions for create"},
        },
        "required": ["action"],
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
    "plan_roadmap": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "show", "to_plan", "set", "list", "create", "update", "edit-phase", "add-phase", "remove-phase", "delete"],
                "description": "Aktion: status, show, to_plan, set, list, create, update, edit-phase, add-phase, remove-phase, delete",
            },
            "cmd": {
                "type": "string",
                "enum": ["status", "show", "to_plan", "set", "list", "create", "update", "edit-phase", "add-phase", "remove-phase", "delete"],
                "description": "Alias für 'action' (deprecated, nutze action= für Konsistenz mit plan_lock/plan_notify)",
            },
            "name": {"type": "string", "description": "Roadmap-Name (ohne .yaml). Auto-select bei Weglassung."},
            "phase": {"type": "string", "description": "Phase-ID für show/to_plan/set/edit-phase/remove-phase"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "blocked"],
                "description": "Neuer Status für 'set'/'edit-phase'",
            },
            "goal": {"type": "string", "description": "Roadmap-Ziel für 'create'/'update'"},
            "phases": {
                "type": "array",
                "description": "Phasen-Liste für 'create'",
                "items": {"type": "object"},
            },
            "phase_data": {
                "type": "object",
                "description": "Phase als JSON-Objekt für 'add-phase'",
            },
            "priority": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Neue Priorität für 'edit-phase'",
            },
            "effort": {"type": "string", "description": "Neuer Aufwand für 'edit-phase'"},
            "impact": {"type": "string", "description": "Neuer Impact für 'edit-phase'"},
            "tasks": {
                "type": "array",
                "description": "Tasks-Liste für 'edit-phase'",
                "items": {"type": "string"},
            },
        },
        "required": [],
    },
    "plan_session": {
        "type": "object",
        "properties": {
            "include_history": {
                "type": "boolean",
                "description": "Git-basierte Plan-History anzeigen (default: false)",
                "default": False,
            },
        },
    },
    "plan_lock": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["lock", "unlock", "status"],
                "description": "Aktion: lock (sperren), unlock (freigeben), status (prüfen)",
            },
            "path": {"type": "string", "description": "Datei- oder Verzeichnispfad"},
            "session_id": {"type": "string", "description": "Session-ID (optional, auto-detect)"},
        },
        "required": ["action", "path"],
    },
    "plan_notify": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "check"],
                "description": "Aktion: send (Nachricht senden), check (eigene Nachrichten prüfen)",
            },
            "to": {"type": "string", "description": "Ziel-Session-ID (erforderlich für send)"},
            "message": {"type": "string", "description": "Nachrichtentext (erforderlich für send)"},
            "kind": {
                "type": "string",
                "enum": ["info", "warning", "alert"],
                "description": "Nachrichtentyp (default: info)",
                "default": "info",
            },
            "session_id": {"type": "string", "description": "Session-ID (optional)"},
        },
        "required": ["action"],
    },
    "plan_history": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Plan-ID (optional — default: aktueller Plan)"},
            "lines": {"type": "integer", "description": "Anzahl Log-Einträge (default: 10)", "default": 10},
        },
    },
    "plan_git_init": {
        "type": "object",
        "properties": {
            "commit_message": {"type": "string", "description": "Initiale Commit-Nachricht (optional)"},
        },
    },
    "plan_git_push": {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote-Name (default: origin)"},
            "branch": {"type": "string", "description": "Branch zum Pushen (default: aktueller Branch)"},
        },
    },
    "plan_git_status": {
        "type": "object",
        "properties": {},
    },
    "plan_git_sync": {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote-Name (default: origin)"},
            "branch": {"type": "string", "description": "Branch (default: aktueller)"},
            "push": {"type": "boolean", "description": "Nach Commit pushen (default: true)"},
        },
    },
    "plan_git_stash": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["push", "pop", "list"],
                "description": "Aktion: push (stashen), pop (wiederherstellen), list (anzeigen)",
            },
            "message": {"type": "string", "description": "Stash-Beschreibung (push only)"},
        },
        "required": ["action"],
    },
    "plan_git_branch": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["current", "list", "create", "switch", "delete"],
                "description": "Aktion: current, list, create, switch, delete",
            },
            "name": {"type": "string", "description": "Branch-Name (create/switch/delete)"},
            "start_point": {"type": "string", "description": "Start-Punkt (create only)"},
        },
        "required": ["action"],
    },
    "plan_git_tag": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "delete"],
                "description": "Aktion: create, list, delete",
            },
            "tag_name": {"type": "string", "description": "Tag-Name (create/delete)"},
            "message": {"type": "string", "description": "Tag-Beschreibung (create only, annotierter Tag)"},
        },
        "required": ["action"],
    },
    "plan_pr_create": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR-Titel (erforderlich)"},
            "body": {"type": "string", "description": "PR-Beschreibung"},
            "head": {"type": "string", "description": "Quell-Branch (default: aktueller Branch)"},
            "base": {"type": "string", "description": "Ziel-Branch (default: main)"},
            "owner": {"type": "string", "description": "Repo-Owner (default: aus Git-Remote)"},
            "repo_name": {"type": "string", "description": "Repo-Name (default: aus Git-Remote)"},
        },
        "required": ["title"],
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
    logger.info("plan_follow: %d tools registered", len(PLAN_TOOLS))


def _register_hooks(ctx: PluginContext) -> None:
    """Register pre_llm_call hook for task injection and post_tool_call for logging."""
    from .plan_hooks import on_post_tool_call, on_pre_llm_call
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
