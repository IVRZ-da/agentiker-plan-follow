---
name: plan-follow
description: "Plugin-provided skill (v1.5.1) — 24 plan tools + 2 hooks + 10 templates + template-required + p0 auto + TDD + parallel groups + roadmap + cross-session. Bietet strukturierte Task-Abarbeitung mit Enforcement."
version: 1.4.3
author: Hermes Agent
tags: [planning, enforcement, review, tasks, workflow, execution, templates, parallel, peer-review, tts, roadmap, cross-session]
related_skills: [requesting-code-review, code-intel-code-review, plan-peer-review]
---

# Plan-Follow Skill v1.4.2

**Plugin-provided skill (plan_follow plugin, v1.4.2).** Nutze `plan_create` → `plan_current` → `plan_complete` für strukturierte Task-Abarbeitung mit optionalem Review-Gate, Auto-Verify, Auto-Commit, parallelen Gruppen, automatischem Peer Review und TTS-Event-Markern.

Seit v1.4.2 Module-Split: `plan_core.py` (1774 Zeilen) → `tools/` Subpackage mit 10 Modulen + Re-Export Facade.

## Tools (24)

| Tool | Funktion |
|------|----------|
| `plan_create(goal, repo, template, parallel_groups)` | Plan anlegen (template=Pflicht, Tasks werden aus Template generiert) — **inkl. p0 (Peer Review) + TDD + Auto Peer Review + TTS** |
| `plan_current()` | Zeigt den/die aktiven Task(s) |
| `plan_complete(task_id, skip_review, auto_verify, auto_commit)` | Task abschliessen + Review-Gate + auto-verify + auto-commit + **TTS-Marker** |
| `plan_verify()` | Drift-Check: ungeplante Änderungen? |
| `plan_status()` | Alle Tasks als Übersicht |
| `plan_todo(todos, merge)` | Todo-Liste aus Plan-Tasks (ersetzt built-in `todo`) |
| `plan_update(task_id, changes)` | Task-Eigenschaften ändern |
| `plan_review(task_id, profile, depth)` | Review für aktuellen Task starten |
| `plan_auto_review(task_id, profile, depth)` | Automatischer Review mit Coverage + Prompt-Builder |
| `plan_review_profiles()` | Verfügbare Review-Profile anzeigen |
| `plan_list(include_archived)` | Alle Pläne anzeigen (auch archivierte) |
| `plan_abort(task_id?)` | Task oder ganzen Plan abbrechen |
| `plan_delete(plan_id)` | Plan von Disk löschen |
| `plan_select(plan_id)` | Zwischen Plänen wechseln |
| `plan_validate(plan_id)` | Plan-Struktur validieren (depends_on, Zyklen, orphan tasks) |
| `plan_duedate(task_id, due)` | Fälligkeit setzen/anzeigen |
| `plan_archive(plan_id)` | Plan archivieren |
| `plan_restore(plan_id)` | Archivierten Plan wiederherstellen |
| `plan_roadmap(cmd, action, name, phase, status, goal, phases, phase_data, priority, effort, impact, tasks)` | Roadmap YAML-Management (11 Subcommands) — siehe Subcommands-Tabelle unten |
| `plan_session()` | Cross-Session Status + History anzeigen |
| `plan_lock(action, path, session_id)` | File-Lock-Management (acquire/release/list/check) |
| `plan_notify(action, to, message)` | Notifications senden/empfangen/listen |
| `plan_history(plan_id, lines)` | Git-History eines Plans anzeigen |
| `plan_git_init(message)` | Git-Repo für PLANS_DIR initialisieren |

## Templates (7)

| Template | Tasks | Review | Beschreibung |
|----------|-------|--------|-------------|
| `deploy` | 4 | api-route | Build → Test → Deploy → Verify |
| `bugfix` | 3 | unit-test | RED → GREEN → REFACTOR (TDD) |
| `feature` | 4 | unit-test | RED → GREEN → REFACTOR → Docs (TDD) |
| `refactoring` | 4 | full | Coverage → Refactor → Verify |
| `research` | 3 | none | Search → Analyze → Summarize |
| `analysis` | 4 | unit-test | Code-Scan → Analyze → Report → Review |
| `fix` | 2 | none | Analyse → Fix (schnelle Bug-Fixes) |

## Review-Profile (6)

| Profil | Beschreibung |
|--------|-------------|
| `none` (default) | Kein Review |
| `unit-test` | Tests + Coverage + Edge-Cases |
| `api-route` | API-Routen: Validierung + Error-Handling + Security |
| `ui-component` | React/UI: A11y + SSR + State + Forms + Mobile |
| `security` | Secrets + Injection + XSS + Auth |
| `full` | Alle Checks kombiniert |

## Roadmap Subcommands (11)

`plan_roadmap(action=..., ...)` — strategic phase overviews.

| Aktion | Parameter | Funktion |
|--------|-----------|----------|
| `status` | — | Übersicht mit allen Phasen + Fortschritt |
| `show` | `phase` | Detail einer Phase anzeigen |
| `to_plan` | `phase` | Phase in plan_create-Tasks konvertieren |
| `set` | `phase`, `status` | Phase-Status ändern (pending/in_progress/completed/blocked) |
| `list` | — | Alle Roadmaps auflisten |
| `create` | `name`, `goal`, `phases` | Neue Roadmap erstellen |
| `update` | `name`, `goal` | Roadmap-Ziel aktualisieren |
| `edit-phase` | `phase`, `name`, `priority`, `effort`, `impact`, `tasks`, `status` | Phase-Eigenschaften ändern |
| `add-phase` | `phase_data` (dict) | Neue Phase anhängen |
| `remove-phase` | `phase` | Phase entfernen |
| `delete` | `name` | Ganze Roadmap löschen |

## Hooks (2)

### pre_llm_call — Task-Banner (Complexity: 52)
Injiziert in JEDEN Turn einen Banner mit:
- **CURRENT TASK** — Task-Name + Goal + Progress (███░░░)
- **Drift-Warnung** — ungeplante Änderungen seit letztem Commit
- **Review-State** — pending/passed/failed mit Issue-Count
- **Due-Info** — Fälligkeits-Status + Überfälligkeit
- **Coordination** — andere Sessions, active Locks, Notifications
- **TTS-Marker** — plan_created / task_completed / review_failed
- **Health-Check** — Plan-Tools, Code-Tools, Honcho-Status
- **TTL-Cache (60s)** — für Health + Drift

### post_tool_call — Tool-Tracking
- Tool-Call-Tracking (duration, status, Kategorie)
- Lock-Check bei schreibenden Zugriffen (andere Sessions blocken)
- File-Logging in `.session-logs/` Verzeichnis

## Verhalten

- **Template-Pflicht:** `plan_create()` erfordert zwingend ein Template — manuelle Tasks werden nicht akzeptiert. Ohne Template: Fehler.
- **p0 Auto-Peer-Review:** `expand_template()` stellt automatisch einen p0-Task (Peer Review) vor alle Template-Tasks. Der erste Code-Task hängt von p0 ab.
- **TDD in Code-Templates:** `fix`, `bugfix`, `feature` haben RED→GREEN (→REFACTOR). Tests werden VOR Implementation geschrieben.
- **pre_llm_call Hook** injiziert Task-Banner in JEDEN Turn
- **TTL-Cache (60s)** — health_check + drift nicht auf jedem Turn
- **Disk-Recovery:** nach `/new` wird letzter aktiver Plan automatisch geladen (via plans_index.json)
- **Parallele Gruppen:** `plan_create(parallel_groups={"g1": {"tasks": ["a","b"]}})`
- **Auto-Verify:** `plan_complete(task_id, auto_verify=true)` führt verify-Command aus
- **Auto-Commit:** `plan_complete(task_id, auto_commit=true)` committed Task-Files via Git
- **Auto Peer Review:** Nach `plan_create()` läuft `run_peer_review()` (8-Punkte-Checkliste) + `apply_findings()`
- **TTS Marker:** `[TTS:event=plan_created]` bei create, `[TTS:event=task_completed]` bei complete
- **Cross-Session Koordination:** Sessions, Locks, Notifications via `coord_state.py` (atomic JSON)
- **Roadmap-Management:** YAML-basierte Phasen mit Abhängigkeiten und Prioritäten
- **plan_todo ersetzt built-in todo:** `registry.deregister("todo")` beim Plugin-Start
- **Coverage Enforcement:** `plan_coverage.py` misst pytest-cov Coverage + Mutation Testing (mutmut)
- **Git-Integration:** Auto-Commit in PLANS_DIR `.git`, plan_history zeigt Git-Log

## Architektur (seit v1.4.2)

```
plan_follow/
├── __init__.py          — Plugin-Entry, 24 PER_TOOL_SCHEMAS, Steering Hints, todo-Deregister
├── plan_core.py         — Re-Export Facade für tools/* (Rückwärtskompatibilität)
├── plan_tools.py        — 24 Tool-Handler
├── plan_hooks.py        — pre_llm_call + post_tool_call
├── plan_peer_review.py  — Auto Peer Review (8-Punkt-Checkliste + apply_findings)
├── plan_review.py       — Review-Dispatch, Prompt-Builder, Coverage-Check, auto_review()
├── plan_roadmap.py      — Roadmap YAML-CLI (11 Subcommands: status/show/to_plan/set/list/create/update/edit-phase/add-phase/remove-phase/delete)
├── plan_templates.py    — Template-Engine (7 Built-in + User-Templates + YAML-Parser)
├── plan_todo.py         — Todo-Liste aus Plan-Tasks (ersetzt built-in todo)
├── plan_coverage.py     — pytest-cov Wrapper + Mutation Testing (mutmut)
├── coord_state.py       — Cross-Session Koordination (Sessions, Locks, Notifications, atomic JSON)
├── review_profiles.py   — 6 Review-Profil Definitionen
├── _fmt.py              — Rich-Formatierung (fmt_ok/err/warn/table/banner/code/json)
├── tools/               — plan_core Subpackage (10 + 3 Hilfsmodule)
│   ├── base.py          — Module-State, Persistenz, Session-ID
│   ├── coordination.py  — Honcho, Git, Lock-Integration
│   ├── task.py          — Task CRUD (create, complete, set_active)
│   ├── status.py        — Status, Liste, Progress-Formatierung
│   ├── plan_mgmt.py     — Abort, Delete, Due-Dates, Archive
│   ├── auto.py          — Auto-Verify, Auto-Commit, Drift
│   ├── review.py        — Review-Helper
│   ├── health.py        — Health-Check
│   ├── validation.py    — Plan-Validierung (DAG, orphan, profiles)
│   ├── roadmap_data.py  — Roadmap-Datenfunktionen
│   ├── state.py         — Shared mutable STATE (Singleton)
│   ├── resolver.py      — Monkeypatch-safe Config-Resolution
│   └── config.py        — Mutable Config (ersetzt module-level Konstanten)
└── skills/
    └── plan-follow.md   — Dieser Companion-Skill
```

## Review-Workflow

1. Task mit `review_profile` anlegen
2. Task bearbeiten
3. `plan_review(task_id)` → Checks anzeigen
4. `delegate_task` mit `build_review_prompt()` → Reviewer prüft
5. `save_review_result(task_id, result)` persistieren
6. `plan_complete(task_id)` → Review-Gate gibt frei
7. Bei Fail: Issues fixen → erneut reviewen
