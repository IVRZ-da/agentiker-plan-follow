# Changelog

## [0.1.4] — 2026-06-18

### Version Reset
- **Version corrected: v1.1.0 → v0.1.4** — granular 0.1.x semantic versioning
- BRANCHING.md — branch naming convention + 0.1.x versioning policy
- Branch protection on main (no direct pushes, 1 approval required)

### New Features
- **plan_archive / plan_restore** — Archive plans as soft delete. `plan_archive(plan_id)` moves to `~/.hermes/plans/archived/`, `plan_restore(plan_id)` brings it back. `plan_list(include_archived=true)` shows archived plans.
- **plan_validate** — Plan integrity checker: validates `depends_on` references, circular dependencies (Kahn's algorithm), parallel group consistency, review profiles, task statuses, and orphan detection.
- **plan_duedate** — Set/view due dates per task. `plan_duedate(task_id="p1", due="2026-06-25")`. The `pre_llm_call` hook shows a 🟡 DEADLINE SOON or 🔴 DEADLINE OVERDUE warning.
- **Deadline Warning in Banner** — Automatic deadline display in the `pre_llm_call` hook banner when a due date is set and approaching/overdue.
- **post_tool_call Hook Enhancements** — Per-task tool call metrics (count, duration, category), proactive drift tracking when `code_*`/`patch` tools write outside `task.files`, session log file.

### Changes
- **Error messages English** — All user-facing error and status messages translated from German to English (~30% of strings were German).
- **Logger updated** — Registration log message now shows 17 tools (was 14).
- **Schema completeness** — Added missing `PER_TOOL_SCHEMAS` for plan_archive and plan_restore.
- **Archive path robustness** — `archive_plan()` success message now handles paths outside home directory gracefully.

### Test Improvements
- **217 tests (was 173)** — New test classes:
  - `TestPlanValidate` (7 tests) — validity, missing deps, circular deps, invalid status, plan ID lookup.
  - `TestPlanDueDate` (11 tests) — set, clear, get, overdue detection, default to current task, hook banner integration.
  - `TestPlanArchive` (12 tests) — archive, restore, list archived, tool handler dispatch, roundtrip, data preservation.
  - `TestPostToolCallHook` (10 tests) — metrics recording, drift warnings, deduplication, reset on advance, hook dispatch.

### Tool Count
- **17 tools** (was 12): `plan_create`, `plan_current`, `plan_complete`, `plan_verify`, `plan_status`, `plan_update`, `plan_review`, `plan_review_profiles`, `plan_list`, `plan_abort`, `plan_delete`, `plan_select`, `plan_validate`, `plan_duedate`, `plan_archive`, `plan_restore`.
