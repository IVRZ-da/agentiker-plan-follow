|---
name: plan-follow
description: "Plugin-provided skill (v1.0.1) — 12 plan tools + 2 hooks + 6 templates + review gate + parallel groups. Bietet strukturierte Task-Abarbeitung mit Enforcement."
version: 1.0.1
author: Hermes Agent
tags: [planning, enforcement, review, tasks, workflow, execution, templates, parallel, peer-review, tts]
related_skills: [requesting-code-review, code-intel-code-review, plan-peer-review]
---

# Plan-Follow Skill v1.0.0

**Plugin-provided skill (plan_follow plugin, v1.0.0).** Nutze `plan_create` → `plan_current` → `plan_complete` für strukturierte Task-Abarbeitung mit optionalem Review-Gate, Auto-Verify, Auto-Commit, parallelen Gruppen, automatischem Peer Review und TTS-Event-Markern.

## Tools

| Tool | Funktion |
|------|----------|
| `plan_create(goal, tasks, repo, template, parallel_groups)` | Plan anlegen (Tasks, Dependencies, Templates, parallele Gruppen) — **inkl. Auto Peer Review + TTS** |
| `plan_current()` | Zeigt den/die aktiven Task(s) |
| `plan_complete(task_id, skip_review, auto_verify, auto_commit)` | Task abschliessen + Review-Gate + auto-verify + auto-commit + **TTS-Marker** |
| `plan_verify()` | Drift-Check: ungeplante Änderungen? |
| `plan_status()` | Alle Tasks als Übersicht |
| `plan_update(task_id, changes)` | Task-Eigenschaften ändern |
| `plan_review(task_id, profile, depth)` | Review für aktuellen Task starten |
| `plan_review_profiles()` | Verfügbare Review-Profile anzeigen |
| `plan_list()` | Alle Pläne anzeigen (auch abgeschlossene) |
| `plan_abort(task_id?)` | Task oder ganzen Plan abbrechen |
| `plan_delete(plan_id)` | Plan von Disk löschen |
| `plan_select(plan_id)` | Zwischen Plänen wechseln |

## Templates

| Template | Tasks | Review | Beschreibung |
|----------|-------|--------|-------------|
| `deploy` | 4 | api-route | Build → Test → Deploy → Verify |
| `bugfix` | 3 | unit-test | RED → GREEN → REFACTOR (TDD) |
| `feature` | 4 | unit-test | Spec → Implement → Test → Docs |
| `refactoring` | 4 | full | Coverage → Refactor → Verify |
| `research` | 3 | none | Search → Analyze → Summarize |
| `analysis` | 4 | unit-test | Code-Scan → Analyze → Report → Review |

## Review-Profile

| Profil | Beschreibung |
|--------|-------------|
| `none` (default) | Kein Review |
| `unit-test` | Tests + Coverage + Edge-Cases |
| `api-route` | API-Routen: Validierung + Error-Handling + Security |
| `ui-component` | React/UI: A11y + SSR + State + Forms + Mobile |
| `security` | Secrets + Injection + XSS + Auth |
| `full` | Alle Checks kombiniert |

## Verhalten

- **pre_llm_call Hook** injiziert Task-Banner in JEDEN Turn (CURRENT TASK + Drift + Review + Health + TTS Marker)
- **TTL-Cache (60s)** — health_check + drift werden nicht auf jedem Turn neu ausgeführt
- **Health-Warnung am ENDE** des Banners (blockiert nicht mehr den Task-Banner)
- **Disk-Recovery:** nach `/new` wird der letzte aktive Plan automatisch geladen
- **Parallele Gruppen:** `plan_create(parallel_groups={"g1": {"tasks": ["a","b"]}})`
- **Auto-Verify:** `plan_complete(task_id, auto_verify=true)` führt verify-Command aus
- **Auto-Commit:** `plan_complete(task_id, auto_commit=true)` committed Task-Files
- **post_tool_call Hook** loggt Tool-Aufrufe für Analyse
- **Auto Peer Review:** Nach `plan_create()` läuft automatisch `run_peer_review()` gegen die 8-Punkte-Checkliste. Findings werden via `apply_findings()` eingearbeitet. Kein Parameter — immer aktiv.
- **TTS Marker:** Bei `plan_create()` wird `[TTS:event=plan_created]` gesetzt, bei `plan_complete()` ein `[TTS:event=task_completed]`. Der Agent sieht die Marker im Hook-Banner.
- **TTS Events:** Marker erscheinen im Banner, werden genau einmal angezeigt, dann gelöscht.

## Auto Peer Review

Nach jedem `plan_create()` wird automatisch ein Peer Review des Plans ausgeführt:

1. Prüfung gegen 8-Punkte-Checkliste (depends_on, verify, files, ordering, profiles, parallel_groups)
2. Findings werden automatisch via `apply_findings()` korrigiert
3. Kritische Findings erscheinen als `peer_review` im `plan_create()` Ergebnis
4. Bei kritischen Findings bekommt der Status `warning` statt `created`
5. Der Plan wird nach der Korrektur automatisch gespeichert

## TTS Event Marker

Das Plugin setzt `tts_flags` im Plan. Der Hook zeigt sie als `[TTS:event=X:message=Y]`:

| Trigger | Event | Wann |
|---------|-------|------|
| Plan erstellt | `plan_created` | Nach `plan_create()` |
| Task abgeschlossen | `task_completed` | Nach `plan_complete()` |
| Review fehlgeschlagen | `review_failed` | Bei failed review_result |

Der Agent (LLM) sieht diese Marker und ruft `text_to_speech(message)` auf.
Marker werden genau einmal angezeigt und dann aus dem Plan gelöscht.

## Review-Workflow

1. Task mit `review_profile` anlegen
2. Task bearbeiten
3. `plan_review(task_id)` → Checks anzeigen
4. `delegate_task` mit `build_review_prompt()` → Reviewer prüft
5. `save_review_result(task_id, result)` persistieren
6. `plan_complete(task_id)` → Review-Gate gibt frei
7. Bei Fail: Issues fixen → erneut reviewen

## Tool-Hierarchie

Die übergreifende Tool-Hierarchie ist im Skill `plan-following` (software-development) dokumentiert.
Dieses Plugin registriert nur die plan_follow-eigenen Tools — die Hierarchie wird zentral im Skill `plan-following` gesteuert.
