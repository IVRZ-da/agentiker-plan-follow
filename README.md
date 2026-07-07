# 📋 plan_follow — Hermes Plugin

> **Structured plan creation, task enforcement, review gates, parallel groups, auto-verify/commit, plan validation, due dates, archive/restore, and session isolation.**

> 24 tools · 2 hooks · 7 templates · 1480 tests · 0.5.29

[![Version](https://img.shields.io/badge/version-0.5.29-blue.svg)]() [![Tests](https://img.shields.io/badge/tests-1480%20tests-green.svg)]() [![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## 📋 Table of Contents

- [✨ Why?](#-why)
- [🚀 Quick Start](#-quick-start)
- [🛠 Tools](#-tools)
- [📦 Installation](#-installation)
- [🏗 Architecture](#-architecture)
- [📝 Templates & Review Profiles](#-templates--review-profiles)
- [🧪 Development](#-development)
- [📄 Changelog](#-changelog)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

---

## ✨ Why?

Hermes ships with `todo` and basic task tracking. When you need structured multi-step plans — with dependencies, parallel execution, review gates, auto-verification, and git integration — you'd normally juggle manual checklists and external tools.

**plan_follow turns plan management into enforceable agent workflows:**

| Feature | What it does |
|---------|-------------|
| **Task Dependencies** | `depends_on` array for ordered execution |
| **Parallel Groups** | Multiple tasks run in parallel within a group, groups run sequentially |
| **Review Gates** | 6 review profiles with independent reviewer subagent pattern |
| **Auto-Verify** | Automatic verify command execution on `plan_complete` |
| **Auto-Commit** | Git commit on task completion |
| **Drift Detection** | Git diff against task scope on every verify |
| **Archiving** | Soft delete via `plan_archive` / `plan_restore` |
| **Due Dates** | Per-task deadlines with automatic banner warnings (🟡 SOON / 🔴 OVERDUE) |
| **Git Integration** | 9 tools for branch, commit, stash, PR creation |
| **Cross-Session** | Locks, notifications, session overview for parallel workers |
| **12 Templates** | deploy, bugfix, feature, refactoring, research, analysis, fix, and more |

The result: **editor-grade plan management** in the terminal — your plans are always up-to-date, verified, and versioned.

---

## 🚀 Quick Start

### Installation
```bash
cd ~/.hermes/plugins
git clone https://github.com/IVRZ-da/agentiker-plan-follow.git
cd agentiker-plan-follow
pip install -e .
```

### Create and run a plan
```python
# 1. Create a plan (template-based)
plan_create(goal="Fix login validation", template="bugfix",
    params={ "files": ["lib/validation.ts"] })

# 2. Show the current task
plan_current()       # "p1: Write a failing test for validation"

# 3. Complete a task — auto-verify + auto-commit
plan_complete("p1", auto_verify=True, auto_commit=True)

# 4. Review a task before completion
plan_review("p2", profile="unit-test")

# 5. Management — archive, git, PR
plan_list()                          # List all plans
plan_validate()                      # Check plan integrity
plan_archive("2026-06-18-fix-validation")  # Archive completed plan
plan_git_branch(action="create", name="feature/validation")  # Git branch
plan_pr_create(title="Fix validation", body="...")           # Create PR
```

---

<!-- README_AUTO -->

[![Version](https://img.shields.io/badge/version-0.5.30-blue.svg)]() [![Tests](https://img.shields.io/badge/tests-1480%20tests-green.svg)]() [![License](https://img.shields.io/badge/license-MIT-green.svg)]()

**Version:** 0.5.30

**Tests:** 1480 tests

**Tools (39):**

**Profiles:**

| Profile | Tools | Description |
|---------|-------|-------------|
| `none` | — | Kein Review (Default) |
| `unit-test` | — | Tests + Coverage + Edge-Cases |
| `api-route` | — | API-Routen: Validierung + Error-Handling + Security |
| `ui-component` | — | React/UI: A11y + SSR + State + Forms + Mobile |
| `security` | — | Secrets + Injection + XSS + Auth |
| `full` | — | Alle Checks kombiniert |


### Cross-Session — Locks, Notifications (4 Tools)

| Tool | Description |
|------|-------------|
| `plan_coord_cleanup` | —. |
| `plan_lock` | Manage resource locks for cross-session coordination. |
| `plan_notify` | Send a notification to another session or check own notifications. |
| `plan_session` | Show active sessions with their plans, locks, and pending notifications. |


### Git Integration — Branch, Commit, PR (9 Tools)

| Tool | Description |
|------|-------------|
| `plan_git_branch` | Manage git branches in configured repos. |
| `plan_git_init` | Initialize a Git repository in ~/.hermes/plans/ for plan versioning. |
| `plan_git_push` | Push committed changes to remote for all configured repos. |
| `plan_git_stash` | Stash or unstash uncommitted changes in configured repos. |
| `plan_git_status` | Show comprehensive git status for all configured repos. Returns branch name, dirty flag, ahead/behind count, and last commit message for each repo. |
| `plan_git_sync` | Pull to add to commit to push in one step for all configured repos. |
| `plan_git_tag` | Create, list, or delete git tags in configured repos. |
| `plan_history` | Show git-based plan version history. |
| `plan_pr_create` | Create a Pull Request via Forgejo API for all configured repos. |


### Plan Lifecycle — Create & Complete (5 Tools)

| Tool | Description |
|------|-------------|
| `plan_abort` | Abort the active plan or a specific task. |
| `plan_complete` | Complete the current task, verify it, advance to the next one. |
| `plan_create` | Create a new structured plan with enforceable tasks. TEMPLATE IS REQUIRED — manual tasks are not allowed. |
| `plan_current` | Show the current task. ONLY ONE task is returned at a time — you see only what needs to be done now. Returns task details including allowed files, ... |
| `plan_todo` | Manage your task list for the active plan. |


### Plan Management — List, Select, Archive (7 Tools)

| Tool | Description |
|------|-------------|
| `plan_archive` | Move a plan to the archive directory (soft delete). |
| `plan_delete` | Permanently delete a plan from disk. |
| `plan_list` | List all plans (including completed and aborted ones), newest first. Returns plan_id, goal, progress, and whether each plan is currently active. Us... |
| `plan_restore` | Restore a plan from the archive back to the plans directory. |
| `plan_select` | Switch to a different saved plan as the active one. |
| `plan_suggest` | Suggest a plan decomposition for a goal by analyzing the project. |
| `plan_template` | Manage user-defined plan templates. |


### Roadmap & Decomposition (3 Tools)

| Tool | Description |
|------|-------------|
| `plan_decompose` | Manage hierarchical task decomposition (compound tasks with sub-tasks). |
| `plan_roadmap` | Manage roadmaps — strategic phase overviews. |
| `plan_sync` | Sync plans with external systems. |


### Status & Review — Track & Verify (7 Tools)

| Tool | Description |
|------|-------------|
| `plan_auto_review` | Prepare a complete review in one call — reads files, measures test coverage, and builds the delegate_task prompt. |
| `plan_review` | Review a task's files using an independent reviewer subagent. |
| `plan_review_profiles` | Show all available review profiles with their names, descriptions, and checks. Use this to see what each profile validates before selecting one for... |
| `plan_review_save_result` | Save a review result for a task. |
| `plan_status` | Show all tasks with their current status (pending/in_progress/completed/blocked). Returns a progress overview with counts and blocked-by reasons. |
| `plan_update` | Update a task's properties without aborting the plan. |
| `plan_verify` | Check for drift: compare current git changes against the plan's task scope. Returns list of unplanned files if drift detected. Call this before pla... |


### Time Tracking & Simulation (2 Tools)

| Tool | Description |
|------|-------------|
| `plan_simulate` | Simulate a plan to find critical path and parallelization opportunities. |
| `plan_time` | Track time spent on tasks. |


### Validation & Deadlines (2 Tools)

| Tool | Description |
|------|-------------|
| `plan_duedate` | Set or view a due date for a task. |
| `plan_validate` | Validate the integrity of a plan. |

### Recent Changelog

## [0.5.30] — 2026-07-07

### Fixed
- **plan_update Schema um plan_id ergänzt** — `plan_id` jetzt als optionales Property im JSON-Schema deklariert (Handler hatte es schon seit v0.5.29)
- **test_coord_state.py: JSON-Parse-Tests gefixt** — Tests erwarteten JSON-Output, Handler gibt Rich-formatierten Text zurück

## [0.5.29] — 2026-07-04

### Fixed
- **plan_create akzeptiert jetzt top-level `tasks` auch mit template** — `tasks` werden automatisch in `params.tasks` gemerged (bisher nur via `params={"tasks": [...]}`)
- **Error-Message zeigt alle 12 Templates** — dynamisch aus `get_template_names()` statt hardcodierter 7er-Liste

### Added
- **Neues `free` Template** — ohne TDD-Zwang, review_profile=none, Tasks direkt via `tasks` oder `params.tasks`

[0.5.28] — 2026-06-30

### Fixed
- **Doppelter README_AUTO-Block entfernt** — zweiter Block zwischen Architecture und Limitations war stale

[0.5.27] — 2026-06-29

### 📝 README-Verbesserungen

- **README_AUTO Marker hinzugefügt** — Generator erkennt jetzt 39 Tools in 4 Kategorien (CRUD, Advanced, Git, Review)
- **Limitations-Sektion** — Neu: Session Isolation, Review Profiles, Git Branching

## [0.5.26] (2026-06-29)

### Removed
- **Hardcodierte Frameworks:** `_detect_project_type()` entfernt medusa, nextjs, react dependency-scan
- **Dead Code:** Duplicate Tool-Handler aus plan_suggest.py (Relikt aus Monolith-Split v0.5.7)

### Changed
- **Framework Detection:** _detect_project_type() ist jetzt rein marker-basiert (package.json, go.mod, pyproject.toml, Cargo.toml, composer.json, Gemfile)

### Tests
- 5 Framework-spezifische Tests entfernt, 60 Tests passed

<!-- END README_AUTO -->

---

## 📦 Installation

### 1. Plugin aktivieren

Enable in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - plan_follow
```

Requires Hermes restart (`/new` or daemon restart).

### 2. Dependencies installieren

```bash
# Ins Hermes-Venv installieren
cd ~/.hermes/plugins/plan_follow
~/.hermes/hermes-agent/venv/bin/pip install -e .
```

**Dependencies:** `rich>=13.0`, `PyYAML>=6.0`, `packaging>=24.0`

---

## 🏗 Architecture

```
plugin.yaml          — v0.5.17 manifest
__init__.py          — register() entry point, tool registration, schemas
plan_core.py         — Data model, JSON persistence, plan CRUD, validation
plan_tools.py        — Tool handler implementations (17 tools)
plan_hooks.py        — pre_llm_call + post_tool_call hooks
plan_templates.py    — 6 built-in templates + YAML user template support
plan_review.py       — Review dispatch, prompt building, result validation
review_profiles.py   — 6 review profile definitions
skills/              — Companion skill for LLM awareness
tests/               — 217 tests
CHANGELOG.md         — Release history
```

<!-- END README_AUTO -->

---

## ⚠️ Limitations

| Area | Limitation | Workaround |
|------|-----------|------------|
| **Session Isolation** | Plans not automatically shared across Hermes sessions | Use `plan_select()` to load a plan from disk in a new session |
| **Review Profiles** | Only 6 built-in profiles available | Custom profiles require plugin modification |
| **Git Branching** | Auto-commit only supports `plan_complete` context | Manual git operations for complex workflows |
| **Due Dates** | Soft enforcement (banner warnings only) | Agent must self-enforce via `plan_verify` |
| **Drift Detection** | Only compares git state against task scope | Not a full audit trail |
| **Templates** | Free-form plans not supported | Task structure must match template format (by design) |

## 🤖 Subagent-Integration

| Feature | Description |
|---------|-------------|
| **Review Subagent** | `plan_review` spawns an independent reviewer subagent via `delegate_task`, passing files, review profile, and scope |
| **Auto-Review** | `plan_auto_review` prepares a complete review prompt — reads files, measures test coverage, and builds the `delegate_task` payload |
| **Review Profiles** | 6 profile templates (none, unit-test, api-route, ui-component, security, full) that configure the reviewer's focus and depth |
| **auto_peer_review** | Optional post-create review: `plan_create` auto-launches a peer review subagent when enabled |
| **Session Isolation** | `pre_llm_call` hook uses in-memory cache only — no plan leakage across subagent task delegations |
| **Plugin Hooks** | `pre_llm_call` + `post_tool_call` hooks integrate with the Hermes agent lifecycle for drift tracking, health checks, and coordination |
| **Plan Validation** | `plan_validate` checks consistency across dependencies, cycles, profiles, and orphan tasks — useful for subagent workflow validation |
| **Auto-Verify/Commit** | `plan_complete(task_id, auto_verify=True, auto_commit=True)` chains verification and git commit as a single subagent action |

## Test Suite

```bash
cd ~/.hermes/plugins/plan_follow

# Run tests
python3 -m pytest tests/ -q --tb=short

# With coverage
python3 -m pytest tests/ --cov=. -q --tb=short

# Ruff Lint
python3 -m ruff check . --select F,E,T,W,I

# README auto-generieren
python3 scripts/generate_readme.py          # Update
python3 scripts/generate_readme.py --check  # Verify (exit 1 if stale)

# Pre-Commit Hook aktivieren
git config core.hooksPath .githooks
```

Currently: **1480 tests**, coverage enforced via pre-commit hook.

---

## 📄 Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for full release history.

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch
3. Add tests for your changes (Coverage ≥ 90%)
4. Run `python3 -m pytest tests/ -q` — all tests must pass
5. Open a PR

See `CONTRIBUTING.md` for details.

---

## 📄 License

[MIT](LICENSE)
