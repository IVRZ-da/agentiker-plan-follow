"""Tool descriptions for plan_follow plugin — ausgelagert aus __init__.py."""

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
        "plan_migrate": (
        "Migrate alte JSON-Pläne in Kanban-DB. "
        "Scannt ~/.hermes/plans/*.json und erzeugt Kanban-Task-Graphen. "
        "Parameters:\n"
        "- dry_run (bool, optional): True = nur scannen (default). False = echte Migration.\n"
        "Returns Report mit gefundenen/migrierten/übersprungenen Plänen."
        ),
        }
