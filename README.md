# 📋 plan_follow — Hermes Plugin

> **Structured plan creation, task enforcement, review gates, parallel groups, auto-verify/commit, plan validation, due dates, archive/restore, and session isolation.**

> 39 tools · 3 hooks · 13 templates · 1556 tests · 0.5.33

[![Version](https://img.shields.io/badge/version-0.5.33-blue.svg)]() [![Tests](https://img.shields.io/badge/tests-1556%20tests-green.svg)]() [![License](https://img.shields.io/badge/license-MIT-green.svg)]()

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

[![Version](https://img.shields.io/badge/version-0.5.35-blue.svg)]() [![Tests](https://img.shields.io/badge/tests-1641%20tests-green.svg)]() [![License](https://img.shields.io/badge/license-MIT-green.svg)]()

**Version:** 0.5.35

**Tests:** 1641 tests

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
| `plan_coord_cleanup` | Clean the shared coordination state: removes stale sessions and file locks. Run it before touching files that a crashed session still holds. |
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
| `plan_create` | Create the tracked plan for any task >~2 minutes. Default planner — never write an ad-hoc markdown plan.
Supply the tasks either as template=<name>... |
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

## [0.5.35] — 2026-11-18

### ⚡ Tool-Fläche: −1.063 Tokens pro Turn (2.737 → 1.674)

Nach dem Vorbild des code_intel-Umbaus (v0.6.25) erst gemessen, dann gekürzt:

- **`plan_create`-Schema 6.713 → 2.383 Zeichen (−64 %)** — die `items`-Struktur und die
  Parameter-Wiederholung in der Tool-Beschreibung sind raus; die Feldnamen (inkl.
  `title`-Alias) und die `review_profile`-Werte stehen jetzt kompakt in der
  `tasks`-Beschreibung. Details im Companion-Skill statt im Schema.
- **Eager-Set 5 → 3** (`plan_create`, `plan_current`, `plan_complete`). `plan_update` und
  `plan_status` sind nicht im Loop und kommen über die Bridge. Gemessen:
  10.947 → 6.698 Zeichen eager (−39 %).
- **`scripts/tool_schema_audit.py`** — registriert das Plugin gegen einen Stub-Context und
  weist chars/Tokens pro Tool sowie die Eager-Summe aus; CI-taugliche Budgets via
  `--max-chars TOOL=N` / `--max-eager-chars N` (Exit 1 bei Verletzung).
  Baseline dokumentiert in `references/tool-surface-baseline.md`.

### 🐛 Health-Selbst-Check meldete faelschlich DEGRADED


## [0.5.34] — 2026-11-11

Anlass: Am 11.11. scheiterte `plan_create` in einer Session mit „Tool 'plan_create' does not
exist", dann mit „template is required", und drei Pläne blockierten sich selbst. Eine
Auswertung von 479 Sessions (state.db, nur echte Tool-Ausgaben) ergab ~56 % Fehlschläge beim
ersten Versuch: 65× `Each task needs 'id' and 'name'`, 49× `template is required`, 29×
`Plan could not be created — critical issues remain`, 25× `multi-Template erfordert
params.tasks`, 11× `Tool 'plan_create' does not exist`.

### 🔴 Root-Cause — Auto-Fixes wurden nie angewandt
- **`apply_findings()` verwarf jeden Fix, dessen Schlüssel im Task noch nicht existierte**
  (`if key in task`). Ein Task ohne `verify` bekam den vorgeschlagenen Testbefehl deshalb nie,
  die Nachprüfung fand das Finding erneut und der Plan blockierte sich selbst — genau die
  29 dokumentierten Blockaden. Jetzt Whitelist `APPLYABLE_FIX_KEYS` (verify, files,
  review_profile, depends_on) statt Existenzprüfung.

### 🔴 Der Plan blockiert sich nicht mehr selbst
- **Review-Tasks sind von der Prüfung ausgenommen** (`is_review_task()`): `kind: review`,
  Namensmuster für die Review-Handlung, oder `id: p0` ohne Dateien und ohne echten verify.
  Der vom Template erzeugte p0-Task (`verify: echo '✅ …'`) erzeugte vorher ein CRITICAL-Finding

## [0.5.33] — 2026-11-11

### 🔴 Critical — der Banner behauptete Zustände, die nicht auf der Platte standen
- **Disk-Freshness statt Prozess-Cache.** `STATE.active_plan` gilt nur noch, solange die Signatur der Plan-Datei (mtime_ns, Größe, sha256) unverändert ist. Andernfalls wird neu geladen; ist die Datei weg, wird der Cache geleert. Ohne Signatur (Altbestand/Restart) ist die Datei autoritativ. Vorher meldete der Banner am 11.11. „CURRENT TASK: t1 — 1/15“, während die Datei 14/14 completed war.
- **`get_current_task_fresh(session_id)`** ist der einzige Banner-Einstieg: Disk-Stand plus Besitzprüfung (`coord_state` session → plan_id). Ein Gateway-Prozess zeigt damit nicht mehr den Plan einer fremden Session. Lesezugriffe adoptieren keinen Plan mehr (`_get_active_plan(recover=False)`).
- **Der Renderer schreibt nicht mehr.** `_build_tts_banner()` rief `_save_plan()` auf und konnte so einen veralteten In-Memory-Stand über den neueren Disk-Stand schreiben (inkl. `.bak`, `plans_index.json`, Git-Commit). TTS-Events liegen jetzt in `~/.hermes/shared/tts_queue.json`; der Renderpfad liest nur, den Water mark setzt `post_tool_call`.
- **Keine Subprozesse im Renderpfad.** `check_drift` und `get_git_status` (je 10 s Timeout pro Repo) laufen im Observer-Hook und füllen Snapshots; der Banner liest sie nur.
- **Abschluss-Epilog statt Dauer-Banner.** Bei erledigtem Plan ist der Banner stumm, bis auf zwei Zeilen („✅ Plan abgeschlossen …“ + berechnete Offen-Liste), genau einmal pro (plan_id, session_id). Abschluss wird aus den Tasks berechnet — plan-level `status` schreibt keine Codezeile; `current_task is None` allein trifft auch Abbrüche.
- **Provenienz-Zeile** in jedem Banner: `Stand | Quelle (Disk, mtime) | Tasks n/m | Cache`. Falschmeldungen sind damit von echten Fortschritten unterscheidbar.

### 🟠 Schreibpfad — Lost Updates verhindert
- **`PlanConflictError`**: `_save_plan` vergleicht vor dem Schreiben die Disk-Signatur mit der geladenen. Hat ein anderer Prozess geschrieben, wird nicht überschrieben; der eigene Stand landet als `<plan_id>.conflict-<ts>.json`.
- **Atomares Schreiben**: `tempfile.mkstemp` + `fsync` + `os.replace`, `.bak` aus dem alten Inhalt, Signatur wird NACH dem Write gesetzt (sonst Konflikt mit sich selbst).
- **`PlanGoneError`**: ein archivierter Plan wird nicht wiederbelebt.
- **`plan_for_write()`**: mutierende Tools (complete/update) laden frisch von der Platte statt auf einem beliebig alten Objekt zu arbeiten.
- **`_load_plan` tolerant**: kaputtes JSON/OSError liefert `None` + Warnung statt einer Exception im Hook.
- **`plans_index.active_plan_id`** wird nur noch bei gesetztem `current_task` geschrieben; ein erledigter Plan gilt nicht mehr als aktiv.

### 🟡 Locks
- **`PLAN_FOLLOW_LOCKS` (Default aus)**: kein Auto-Lock, kein Lock-Block im Banner. Die Fehlerklasse „Lock-Leiche auf abgeschlossenem Plan“ entfällt im Normalfall.

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

Currently: **1556 tests**, coverage enforced via pre-commit hook.

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
