---
name: plan-follow
description: "Plugin-provided skill (v1.6.0) — 39 plan tools + 3 hooks + 13 templates + p0-Review (opt-out) + TDD + parallel groups + roadmap + cross-session + Write-Guard + ehrlicher Disk-Banner. Strukturierte Task-Abarbeitung mit Enforcement."
version: 1.6.0
author: Hermes Agent
tags: [planning, enforcement, review, tasks, workflow, execution, templates, parallel, peer-review, tts, roadmap, cross-session]
related_skills: [requesting-code-review, code-intel-code-review, plan-peer-review]
---

# Plan-Follow Skill v1.6.0

**Plugin-provided skill (plan_follow plugin, v0.5.33).** Nutze `plan_create` → `plan_current` → `plan_complete` für strukturierte Task-Abarbeitung mit optionalem Review-Gate, Auto-Verify, Auto-Commit, parallelen Gruppen, automatischem Peer Review und TTS-Event-Markern.

Seit v1.4.2 Module-Split: `plan_core.py` (1774 Zeilen) → `tools/` Subpackage mit 10 Modulen + Re-Export Facade.

## Tools (39)

| Tool | Funktion |
|------|----------|
| `plan_create(goal, repo, template, tasks, parallel_groups)` | Plan anlegen — entweder template (Vorlage) ODER tasks (eigene Tasks) angeben. **inkl. p0 (Peer Review) + TDD + Auto Peer Review + TTS** |
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
| `plan_validate(plan_id)` | Plan-Struktur validieren (depends_on, Zyklen, orphan tasks, **Branch-Naming-Convention**) |
| `plan_duedate(task_id, due)` | Fälligkeit setzen/anzeigen |
| `plan_archive(plan_id)` | Plan archivieren |
| `plan_restore(plan_id)` | Archivierten Plan wiederherstellen |
| `plan_roadmap(cmd, action, name, phase, status, goal, phases, phase_data, priority, effort, impact, tasks)` | Roadmap YAML-Management (11 Subcommands) |
| `plan_session()` | Cross-Session Status + History anzeigen |
| `plan_lock(action, path, session_id)` | File-Lock-Management (acquire/release/list/check) |
| `plan_notify(action, to, message)` | Notifications senden/empfangen/listen |
| `plan_history(plan_id, lines)` | Git-History eines Plans anzeigen |
| `plan_git_init(message)` | Git-Repo für PLANS_DIR initialisieren |
| `plan_git_push(remote, branch)` | Push committed changes to remote |
| `plan_git_status()` | Git-Status: Branch, Dirty, Ahead/Behind |
| `plan_git_sync(remote, branch, push)` | Pull → Add → Commit → Push |
| `plan_git_stash(action, message)` | Stash push/pop/list |
| `plan_git_branch(action, name)` | Branch current/list/create/switch/delete |
| `plan_git_tag(action, tag_name, message)` | Tag create/list/delete |
| `plan_pr_create(title, body, head, base, owner, repo_name)` | PR via Forgejo API erstellen |

## Templates (13)

| Template | Tasks | Review | Beschreibung |
|----------|-------|--------|-------------|
| `deploy` | 4 | api-route | Build → Test → Deploy → Verify |
| `bugfix` | 3 | unit-test | RED → GREEN → REFACTOR (TDD) |
| `feature` | 4 | unit-test | RED → GREEN → REFACTOR → Docs (TDD) |
| `refactoring` | 4 | full | Coverage → Refactor → Verify |
| `research` | 3 | none | Search → Analyze → Summarize |
| `analysis` | 4 | unit-test | Code-Scan → Analyze → Report → Review |
| `fix` | 2 | none | RED → GREEN (TDD, schnelle Bug-Fixes) |
| `docs` | 4 | none | Research → Outline → Write → Review |
| `infrastructure` | 4 | api-route | Plan → Umsetzung → Test → Apply |
| `go-setup` | 3 | unit-test | Build → Test → Vet |
| `security` | 4 | security | Scan → Findings → Fix → Re-Scan |
| `multi` | 0 | unit-test | Benutzerdefinierte Tasks via `params.tasks` |
| `free` | 0 | none | Freies Template ohne TDD — eigene Tasks via `tasks` oder `params.tasks` |

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

## Hooks (3)

### pre_llm_call — Task-Banner
Injiziert einen Banner (alle 4 Turns bzw. sofort bei Task-Wechsel oder geänderter Zustands-Signatur) mit:
- **CURRENT TASK** — aus dem DISK-Stand dieser Session (`get_current_task_fresh`)
- **Provenienz-Zeile** — Stand, Quelle (Disk + mtime), Tasks n/m, Cache-Status
- **Drift-Warnung** — aus dem Observer-Snapshot, einmal pro Änderung
- **Review-State** — pending/passed/failed mit Issue-Count
- **Due-Info** — Fälligkeits-Status + Überfälligkeit
- **Coordination** — andere Sessions, Locks (nur mit `PLAN_FOLLOW_LOCKS=1`), Notifications
- **TTS-Marker** — plan_created / task_completed aus `~/.hermes/shared/tts_queue.json`
- **Health** — geladener Zustand + „geprüft vor Ns“, DEGRADED erst nach 2 Fehlschlägen

#### Was der Banner NIE tut
- **Nicht schreiben.** Kein `_save_plan`, kein Git, kein Subprozess im Renderpfad. Angezeigte TTS-Events werden im Prozess gemerkt; den persistenten Water mark setzt `post_tool_call`.
- **Nicht adoptieren.** Ein Lesezugriff übernimmt keinen fremden Plan (`_get_active_plan(recover=False)`); Adoption nur in `_try_session_recovery` mit Besitzprüfung.
- **Nicht raten.** Abschluss wird aus den Tasks berechnet (alle completed → „abgeschlossen“, mit aborted → „abgebrochen“); plan-level `status` existiert im Datenmodell nicht.
- **Nicht schlucken.** Jeder Teil hat einen Guard und rendert `⚠️ Banner-Teil <name> fehlgeschlagen: <Typ>`.

#### Abschluss-Epilog
Bei erledigtem Plan ist der Banner stumm, bis auf zwei Zeilen, genau einmal pro (plan_id, session_id): „✅ Plan abgeschlossen: <id> (n/n)“ plus berechnete Offen-Liste (nicht archiviert / Index zeigt noch darauf / offene Locks). Kein Dauer-Banner, kein Replay nach Restart.

### post_tool_call — Tool-Tracking
- Tool-Call-Tracking (duration, status, Kategorie)
- Lock-Check bei schreibenden Zugriffen (andere Sessions blocken)
- File-Logging in `.session-logs/` Verzeichnis

## Verhalten

- **Flexibles Plan-Erstellen:** `plan_create()` akzeptiert entweder ein `template` (Vorlage, z.B. fix/deploy/bugfix) ODER eine `tasks`-Liste mit eigenen Task-Definitionen. Ohne beides: Fehler.
- **p0 Auto-Peer-Review:** `expand_template()` stellt automatisch einen p0-Task (Peer Review) vor alle Template-Tasks. Der erste Code-Task hängt von p0 ab. Abschaltbar mit `p0_review=false` (Template-Parameter oder `plan_create`-Argument). Der Direkt-Tasks-Zweig (ohne Template) erzeugt kein p0.
- **Write-Guard (v0.5.32):** `tools/paths.py` blockt Schreibzugriffe auf `~/.hermes/plans|roadmaps|shared`, wenn `PLAN_FOLLOW_TEST_GUARD=1` gesetzt ist. `_save_plan` verweigert Pläne ohne `plan_id`/`tasks` und legt vor dem Überschreiben ein `.json.bak` an. Env-Overrides: `PLAN_FOLLOW_PLANS_DIR`, `PLAN_FOLLOW_ROADMAPS_DIR`, `PLAN_FOLLOW_SHARED_DIR`.
- **TDD in Code-Templates:** `fix`, `bugfix`, `feature` haben RED→GREEN (→REFACTOR). Tests werden VOR Implementation geschrieben.
- **pre_llm_call Hook** injiziert den Task-Banner alle 4 Turns bzw. sofort bei Task-Wechsel oder geänderter Zustands-Signatur. Beim ersten Turn einer Session wird der Plan einmalig von Disk adoptiert — nur wenn die Session ihn besitzt (kein Cross-Session-Leak). Danach gewinnt immer der Disk-Stand (Signatur-Check).
- **Schreibpfad geschützt (v0.5.33):** `_save_plan` prüft die Disk-Signatur (`PlanConflictError` + Konfliktkopie), schreibt atomar (`mkstemp` + `os.replace`) und verweigert archivierte Pläne (`PlanGoneError`). Mutierende Tools laden über `plan_for_write()` frisch von der Platte.
- **Locks sind opt-in:** `PLAN_FOLLOW_LOCKS=1` aktiviert Auto-Lock/Release; Default aus. Freigabe nur, wenn die Besitzer-Session fehlt oder selbst stale ist.
- **Disk-Recovery:** via `plans_index.json`/neuester Plan-Datei — im Hook beim ersten Turn der Session, sonst beim ersten `plan_`-Tool-Aufruf. Der Honcho-Fallback wurde in v0.5.32 entfernt (HTTP 422, speicherte nur die plan_id).
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
├── plan_templates.py    — Template-Engine (12 Built-in + User-Templates + YAML-Parser)
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
