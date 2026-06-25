# 🎯 agentiker-plan-follow — Hermes Plugin

> Hermes Plugin für strukturierte Plan-Erstellung, Execution-Enforcement, Peer-Review, Cross-Session-Koordination und automatisierte Git-Versionierung.
> 38 Tools — von `plan_create` bis `plan_git_sync`, von `plan_review` bis `plan_roadmap`.

## 📋 Table of Contents

- [✨ Why?](#-why)
- [🚀 Quick Start](#-quick-start)
- [🛠 Tools](#-tools)
- [🏗 Architecture](#-architecture)
- [🧪 Development](#-development)
- [📦 Installation](#-installation)

---

## ✨ Why?

Hermes kommt mit grundlegenden Planungs-Tools. Sobald du jedoch mehrere Tasks parallel verwalten, Cross-Session-Koordination betreiben oder formale Peer-Reviews durchführen willst, brauchst du eine strukturierte Grundlage.

**Plan-Follow bietet:**

| Feature | Nutzen |
|---------|--------|
| **Plan-Erstellung** | 12 Templates (fix, feature, refactoring, deploy, multi, docs, …) — Templates sind **Pflicht**, kein Ad-hoc |
| **Execution-Enforcement** | Tasks werden einzeln abgearbeitet. `plan_current` zeigt NUR den aktuellen Task |
| **Auto-Verify** | Jeder Task kann einen Verify-Command haben — automatische Prüfung vor `plan_complete` |
| **Peer Review** | 6 Review-Profile mit unabhängigem Subagenten-Check vor dem Abschluss |
| **Parallel Groups** | Tasks innerhalb einer Gruppe laufen parallel, Gruppen sequentiell |
| **Git-Integration** | Automatisches Branching, Committing, Tagging, Sync — vollständiger Git-Lifecycle |
| **Roadmaps** | Strategische Phasen-Übersicht mit `plan_roadmap` (11 Subcommands) |
| **HTN Decomposition** | Compound Tasks mit Sub-Tasks für hierarchische Zerlegung |
| **MCP Server** | Stdio + HTTP Server für externe Tool-Anbindung |
| **Dashboard** | Hermes Dashboard Plugin für visuelle Plan-Übersicht |
| **Locks** | Cross-Session Resource Locks für koordinierte Teamarbeit |

---

## 🚀 Quick Start

```bash
# 1. Plugin aktivieren (config.yaml)
plugins:
  enabled:
    - agentiker-plan-follow

# 2. Ersten Plan erstellen
plan_create goal="Mein erstes Feature" template="feature"
# → Erzeugt Plan mit p0 (Peer Review), f1 (Implementierung), f2 (Tests)

# 3. Arbeiten
plan_current        # → "f1: Feature implementieren"
# ... Code schreiben ...
plan_complete task_id="f1" auto_verify=true

# 4. Nächster Task
plan_current        # → "f2: Tests schreiben"
plan_complete task_id="f2" auto_verify=true auto_commit=true

# 5. Review
plan_review task_id="f1" profile="standard"
plan_complete task_id="p0"
```

Weitere Beispiele unter [`docs/examples/`](docs/examples/) (geplant).

---

## 🛠 Tools

<!-- README_AUTO -->

[![Version](https://img.shields.io/badge/version-0.5.12-blue.svg)]() [![Tests](https://img.shields.io/badge/tests-1061%20tests-green.svg)]() [![License](https://img.shields.io/badge/license-MIT-green.svg)]()

**Version:** 0.5.12

**Tests:** 1061 tests

**Tools (39):**


### Advanced (13 Tools)

| Tool | Description |
|------|-------------|
| `plan_decompose` | Manage hierarchical task decomposition (compound tasks with sub-tasks). |
| `plan_history` | Show git-based plan version history. |
| `plan_lock` | Manage resource locks for cross-session coordination. |
| `plan_migrate` | Migrate alte JSON-Pläne in Kanban-DB.  Scannt ~/.hermes/plans/*.json und erzeugt Kanban-Task-Graphen. |
| `plan_notify` | Send a notification to another session or check own notifications. |
| `plan_pr_create` | Create a Pull Request via Forgejo API for all configured repos. |
| `plan_roadmap` | Manage roadmaps — strategic phase overviews. |
| `plan_session` | Show active sessions with their plans, locks, and pending notifications. |
| `plan_simulate` | Simulate a plan to find critical path and parallelization opportunities. |
| `plan_suggest` | Suggest a plan decomposition for a goal by analyzing the project. |
| `plan_sync` | Sync plans with external systems. |
| `plan_time` | Track time spent on tasks. |
| `plan_todo` | Manage your task list for the active plan.  Replaces the built-in `todo` tool.\n Read mode (no parameters):\n - Returns ALL tasks of the active plan as a compact todo list.\n - Output: {todos: [...], summary: {total, pending, in_progress, completed, cancelled}}\n Write mode (todos + merge=true):\n - Set status to 'completed' → completes the task via plan_complete\n - Other status changes are ignored (plan manages status internally)\n |


### CRUD (15 Tools)

| Tool | Description |
|------|-------------|
| `plan_abort` | Abort the active plan or a specific task. |
| `plan_archive` | Move a plan to the archive directory (soft delete). |
| `plan_complete` | Complete the current task, verify it, advance to the next one. |
| `plan_create` | Create a new structured plan with enforceable tasks.  TEMPLATE IS REQUIRED — manual tasks are not allowed. |
| `plan_current` | Show the current task. ONLY ONE task is returned at a time —  you see only what needs to be done now.  Returns task details including allowed files, verification command, and progress. |
| `plan_delete` | Permanently delete a plan from disk. |
| `plan_duedate` | Set or view a due date for a task. |
| `plan_list` | List all plans (including completed and aborted ones |
| `plan_restore` | Restore a plan from the archive back to the plans directory. |
| `plan_select` | Switch to a different saved plan as the active one. |
| `plan_status` | Show all tasks with their current status (pending/in_progress/completed/blocked).  Returns a progress overview with counts and blocked-by reasons. |
| `plan_template` | Manage user-defined plan templates. |
| `plan_update` | Update a task's properties without aborting the plan. |
| `plan_validate` | Validate the integrity of a plan. |
| `plan_verify` | Check for drift: compare current git changes against the plan's task scope.  Returns list of unplanned files if drift detected.  Call this before plan_complete to catch scope creep. |


### Git (7 Tools)

| Tool | Description |
|------|-------------|
| `plan_git_branch` | Manage git branches in configured repos. |
| `plan_git_init` | Initialize a Git repository in ~/.hermes/plans/ for plan versioning. |
| `plan_git_push` | Push committed changes to remote for all configured repos. |
| `plan_git_stash` | Stash or unstash uncommitted changes in configured repos. |
| `plan_git_status` | Show comprehensive git status for all configured repos.  Returns branch name, dirty flag, ahead/behind count,  and last commit message for each repo. |
| `plan_git_sync` | Pull to add to commit to push in one step for all configured repos. |
| `plan_git_tag` | Create, list, or delete git tags in configured repos. |


### Review (4 Tools)

| Tool | Description |
|------|-------------|
| `plan_auto_review` | Prepare a complete review in one call — reads files, measures test coverage,  and builds the delegate_task prompt. |
| `plan_review` | Review a task's files using an independent reviewer subagent. |
| `plan_review_profiles` | Show all available review profiles with their names, descriptions, and checks.  Use this to see what each profile validates before selecting one for a task. |
| `plan_review_save_result` | Save a review result for a task. |

### Recent Changelog

## [0.5.12] — 2026-06-25
- **Kanban-DB Conn Fix:** `conn` als Erstparameter an alle `kdb.*()` Aufrufe übergeben (7 Dateien)
- **Kanban-DB Status Fix:** `initial_status` korrigiert (`in_progress`→`running`, `pending`→`blocked`)
- **Kanban-DB Parameter:** `workspace_kind='dir'`, `workspace_path`, `parents=[root_id]`, `session_id`, `max_runtime_seconds`, `max_retries` in allen `create_task()`-Aufrufen ergänzt
- **Skills/Toolsets getrennt:** Root-Tasks `skills=[]`, Child-Tasks korrekte Skill-Namen
- **sys.path Fix:** `_kanban_available()` mit sys.path Guard für hermes_cli Import in 3 Modulen
- **add_comment author:** `author="system"` in allen add_comment-Aufrufen ergänzt
- **Root-ID Tracking:** create_task Rückgabewert wird für parents-Referenz gespeichert

## [0.5.11] — 2026-06-25
- **VERSION Bump auf v0.5.11:** Kein CHANGELOG-Eintrag (Hotfix)
- Version wurde von 0.5.10 auf 0.5.11 erhöht

## [0.5.10] — 2026-06-25
- **VERSION Bump:** Kein CHANGELOG-Eintrag (Hotfix)

<!-- END README_AUTO -->



## Architektur

```
plan_follow/
├── __init__.py        — Plugin-Entry, TOOL_DESCRIPTIONS, PER_TOOL_SCHEMAS, 38 Tool-Registrierungen
├── plan_tools.py      — 38 Tool-Handler (Facade)
├── plan_core.py       — Re-Export Facade für tools/ Subpackage
├── plan_hooks.py      — pre_llm_call + post_tool_call + on_session_end Hooks
├── plan_roadmap.py    — Roadmap YAML-Management (11 Subcommands)
├── plan_templates.py  — Template-Engine (7 Built-in Templates)
├── plan_peer_review.py— Auto Peer Review (6 extrahierte Checks)
├── plan_review.py     — Review-Dispatch & Coverage-Check
├── plan_todo.py       — Todo-Liste aus Plan-Tasks
├── plan_coverage.py   — pytest-cov Wrapper
├── plan_suggest.py    — Projektanalyse → Task-Vorschlag
├── plan_sync.py       — GitHub/Markdown Sync
├── plan_decompose.py  — HTN-Style Compound Tasks
├── mcp_server.py      — MCP stdio+HTTP Server
├── coord_state.py     — Cross-Session Koordination
├── _fmt.py            — Rich-Formatierung
├── hooks/             — Hook-Subpackage (base.py, breaker.py)
└── tools/             — Plan-Core Subpackage (13 Module)

Weitere: tests/ (16 Test-Dateien, 1028+ Tests), dashboard/ (Hermes Dashboard Plugin)
```

## Tests

```bash
python3 -m pytest tests/ -q --no-header
# 1028+ tests, ~38s Laufzeit
```

## Installation

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - agentiker-plan-follow
```

