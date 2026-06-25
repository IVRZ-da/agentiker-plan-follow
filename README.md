# plan_follow — Hermes Plugin

Structured plan creation, task enforcement, review gates, parallel groups, auto-verify/commit, plan validation, due dates, archive/restore, and session isolation for Hermes Agent.

## Features

| Category | Tools |
|----------|-------|
| **Plan Lifecycle** | `plan_create`, `plan_current`, `plan_complete`, `plan_abort` |
| **Status & Review** | `plan_status`, `plan_update`, `plan_verify`, `plan_review`, `plan_review_profiles` |
| **Management** | `plan_list`, `plan_select`, `plan_delete`, `plan_archive`, `plan_restore` |
| **Validation** | `plan_validate`, `plan_duedate` |

### Core Capabilities

- **Task Dependencies** — `depends_on` array for ordered execution
- **Parallel Groups** — Multiple tasks run in parallel within a group, groups run sequentially
- **Review Gates** — 6 review profiles (none, unit-test, api-route, ui-component, security, full) with independent reviewer subagent pattern
- **Auto-Verify** — Automatic verify command execution on `plan_complete(task_id, auto_verify=True)`
- **Auto-Commit** — Git commit on task completion: `plan_complete(task_id, auto_commit=True)`
- **Drift Detection** — Git diff against task scope on every verify; proactive drift tracking via `post_tool_call` hook
- **Archiving** — Soft delete via `plan_archive` / `plan_restore` instead of permanent `plan_delete`
- **Due Dates** — Per-task deadlines with automatic banner warnings (🟡 SOON / 🔴 OVERDUE)
- **Plan Validation** — Consistency check: deps, cycles, profiles, orphan tasks
- **Templates** — 6 built-in: deploy, bugfix, feature, refactoring, research, analysis
- **Multi-Repo** — `repos` array for drift detection across multiple git repos
- **Session Isolation** — `pre_llm_call` hook uses in-memory cache only (no disk recovery), preventing plan leaks across sessions
- **TTL Cache** — Health check and drift results cached for 60s to reduce API calls per turn
- **Tool Metrics** — Per-task tool call tracking (count, duration, category)
- **Honcho Integration** — Registry-dispatch with HTTP fallback for cross-session recovery

## Installation

Enable in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - plan_follow
```

Requires Hermes restart (`/new` in session or restart the daemon).

## Quick Start

```python
# Create a plan
plan_create(goal="Fix login validation", tasks=[
    {"id": "p1", "name": "Add email format check", "files": ["lib/validation.ts"], "verify": "npm test"},
    {"id": "p2", "name": "Add password strength check", "files": ["lib/validation.ts"], "depends_on": ["p1"]},
])

# Work through tasks
plan_current()                    # See current task
plan_complete("p1")               # Complete task, advance to next
plan_complete("p2", auto_verify=True, auto_commit=True)  # Verify + commit

# Management
plan_list()                       # List all plans
plan_list(include_archived=True)  # Include archived plans
plan_validate()                   # Check plan integrity
plan_duedate("p1", "2026-06-25")  # Set deadline
plan_archive("2026-06-18-fix-validation")  # Archive completed plan
plan_restore("2026-06-18-fix-validation")  # Restore from archive
```

## Architecture

```
plugin.yaml          — v1.1.0 manifest
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

## Test Suite

```bash
cd ~/.hermes/plugins/plan_follow
python3 -m pytest tests/ -v
```

217 tests covering plan creation, task progression, dependencies, parallel groups, persistence, disk recovery, drift detection, health check, templates, review gates, auto-verify/commit, plan management, archive/restore, due dates, plan validation, tool metrics, drift tracking, session isolation, and tool handler dispatch patterns.

## Version History

- **1.1.0** (2026-06-18) — plan_archive/restore, plan_validate, plan_duedate, deadline warnings, error messages English, tool metrics, 217 tests
- **1.0.1** (2026-06-17) — Minor bugfixes, template parametrization
- **1.0.0** (2026-06-16) — Initial release with 12 tools, 2 hooks, 6 templates, 173 tests
