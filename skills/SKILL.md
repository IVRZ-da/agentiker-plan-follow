---
name: plan-follow
description: "Default für jede mehrschrittige Aufgabe (>2 Min): plan_create statt Ad-hoc-Markdown. 39 Tools, 3 Hooks, 13 Templates, Review-Gates, ehrlicher Disk-Banner."
version: 1.7.0
author: Hermes Agent
tags: [planning, enforcement, review, tasks, workflow, execution, templates, parallel, peer-review, tts, roadmap, cross-session]
related_skills: [requesting-code-review, code-intel-code-review, plan-peer-review]
---

# Plan-Follow Skill v1.7.0

**Plugin-provided skill (plan_follow plugin, v0.5.34).** Nutze `plan_create` → `plan_current` → `plan_complete` für strukturierte Task-Abarbeitung mit optionalem Review-Gate, Auto-Verify, Auto-Commit, parallelen Gruppen, automatischem Peer Review und TTS-Event-Markern.

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
- **Auto Peer Review:** VOR dem Persistieren auf einem Draft — `run_peer_review()` (8-Punkte-Checkliste) + `apply_findings()`; auto-fixbare Findings werden übernommen, verbleibende critical Findings verhindern das Speichern (`status=error`, keine Plan-Datei). Review-Tasks (`kind: review`, p0) sind von verify/files/profile ausgenommen.
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

## Ops-/Infra-Pläne ohne Code

1. **Aufrufweg:** Ab v0.5.34 liegen `plan_create`, `plan_current`, `plan_complete`, `plan_update`
   und `plan_status` eager im Tool-Set — direkt aufrufen. Ist nur die Bridge verfügbar (ältere
   Installation oder `tool_search` greift), zuerst `tool_describe(['plan_create'])`, dann
   `tool_call({"calls": [{"name": "plan_create", "arguments": {...}}]})`. `arguments` NICHT
   verschachteln — genau eine Ebene `{name, arguments}`.
2. **Tasks statt Template:** `plan_create` akzeptiert `tasks` direkt (ohne `template`) oder
   `template: 'free'`/`'multi'` mit `params.tasks`. Sind beide gesetzt, gewinnt `tasks`.
   Der Direkt-Zweig erzeugt keinen p0-Task — bei Bedarf selbst einen Task `p0` anlegen und
   vom ersten Task per `depends_on` referenzieren.
3. **verify ehrlich halten:** Bei fehlendem oder bedeutungslosem verify (`echo`, `true`)
   ersetzt der Auto-Review den Projekt-Testbefehl — bei Ops-Plänen ist das falsch. Vorher
   einen echten Shell-Check eintragen (z.B. `systemctl is-active nginx`), sonst besteht der
   Plan eine Prüfung, die nichts prüft.
4. `plan_update` ist pro `tool_call` ein einzelner Aufruf. Lokale Plan-Tools nicht in einem
   Block bündeln; nur `connectors__`-Tools dürfen gebündelt werden.
5. Verify-Befehle müssen fehlschlagen können. Scheinprüfungen wie `test -n "1"` immer
   verwerfen, sie bestehen immer und schützen nichts.
6. Danach `plan_validate(plan_id)` ausführen und den Plan dem User zur Freigabe zeigen.
   Erst nach expliziter Freigabe mit dem ersten Task beginnen.
7. **Wenn der Transport den Payload nicht durchbringt** (`tool_call` bricht mit „calls is not
   valid JSON" ab, schon bei wenigen KB und verschachtelten Task-Arrays): Plan-Datei direkt
   schreiben und per `plan_select` aktivieren. Das ist derselbe Speicherort, den die Tools
   nutzen, und `plan_validate` prüft danach die Struktur:
   - Pfad: `~/.hermes/plans/<plan_id>.json`
   - Top-Level-Keys: `plan_id`, `goal`, `created`, `plan_version` ("1"), `repo`,
     `current_task` (null), `tasks`, `tts_flags` (`{"task_completed": []}`)
   - `tasks` ist ein **DICT** (Key = Task-ID), kein Array. Jeder Task: `id`, `status`
     ("pending"), `name`, `files` (Liste), `verify` (String), `review_profile`
     ("none"…"full"), `review_result` (null), `depends_on` (Liste)
   - Reihenfolge: `plan_select(plan_id)` (kleiner Payload, geht durch) →
     `plan_validate(plan_id)` → `plan_status()`
   - In `verify` nur ASCII und einfache Anführungszeichen verwenden; mehrzeilige oder
     backslash-lastige Regex-Kommandos stattdessen in ein `scripts/`-Skript auslagern.
8. **Was der Auto-Review beim Anlegen ablehnt** — `plan_create` endet dann mit
   `status=blocked` und schreibt nichts auf Disk:
   - `parallel_groups`-Tasks, die per `depends_on` auf einen Task **ausserhalb** der Gruppe
     zeigen → `critical`. Entweder die Abhängigkeit mit in die Gruppe nehmen oder die
     Gruppe weglassen. Der praktische Nutzen der Gruppe ist gering: Build und Download
     lassen sich im EXECUTE auch ohne Gruppendefinition gleichzeitig anstossen.
   - Tasks ohne `files`-Eintrag → `important`. Jeder Task braucht mindestens einen Pfad,
     auch reine Ops-Tasks — das Protokoll- oder Doku-File, das er schreibt, genügt.
     Ohne `files` funktionieren Drift-Check und Auto-Commit nicht.
9. **Einen Task nachträglich einfügen** (neue Erkenntnis mitten in der Planung):
   `plan_update` ändert nur bestehende Tasks und kann keinen anlegen. Plan-JSON direkt
   editieren, Task-Dict einsetzen, die `depends_on` der Nachfolger umbiegen, Task-Keys in
   Laufreihenfolge neu sortieren, dann `plan_select(plan_id)` + `plan_validate(plan_id)`.
   Task-IDs müssen nicht numerisch fortlaufend sein — `P5G` zwischen `P5` und `P6` ist
   zulässig, die Laufreihenfolge steuert allein `depends_on`.
10. **Zwei Sessions, ein Index.** `plans_index.json` ist geteilt: eine parallele Session, die
    `plan_select`/`plan_create` aufruft, verschiebt den aktiven Plan. Dein `plan_complete`
    scheitert dann mit `P3 is not the current task (current: P5)` oder — wenn der fremde
    Index gerade auf einem abgeschlossenen Plan steht — mit `No active plan`, obwohl P3 in
    deiner Plan-Datei offen ist: die Plan-Dateien sind getrennt, nur der Index kollidiert.
    Beide Meldungen haben dieselbe Ursache. `plan_status()` zeigt, welcher Plan aktiv ist,
    `plan_select(<eigene plan_id>)` holt ihn zurück.
    `plan_select` vor jedem Block hilft nur bis zum nächsten Umschalten der anderen Session.
    Vorgehen: verify-Command einmal im Terminal laufen lassen, dann `status` und
    `current_task` direkt im eigenen Plan-JSON setzen (die fremde Session fasst nur den Index
    an, nie deine Datei). Am Ende gegenprüfen, dass alle Tasks `completed` sind.
11. **`auto_verify` läuft in einer Subprocess-Shell mit der Env des Hermes-Prozesses.**
    Verify-Strings mit Kommandosubstitution oder Pipes (`test $(find … | wc -l) -le 5`) können dort
    fehlschlagen, obwohl derselbe String im Terminal grün ist — dann bleibt der Task auf
    `pending` und der Plan sieht aus, als wäre die Arbeit nicht getan. Bei allem jenseits
    eines einzelnen einfachen Kommandos: erst im Terminal verifizieren, dann
    `plan_complete(auto_verify=false)`.
    - **Geerbter `PYTHONPATH` ist die häufigste Ursache.** Der Hermes-Prozess setzt
      `PYTHONPATH` auf Kernel-Scratch + eine fremde Runtime-venv; ein Verify, der `pytest`
      im Plugin-Repo startet, importiert dann fremde `site-packages` und liefert Dutzende
      Phantom-Failures (`ModuleNotFoundError`, ein Bruchteil der Tests wird überhaupt
      gesammelt). Fix: jeden Interpreter-Aufruf im Verify mit `env -u PYTHONPATH` prefixen
      (`env -u PYTHONPATH /path/to/venv/bin/python -m pytest …`). Im Terminal-Tool tritt das
      nicht auf — nur im `plan_complete`-Pfad, was die Diagnose verfälscht.
    - **Ketten ohne `;`.** `a && b; c` führt `c` auch aus, wenn `b` scheitert, und der Task
      wird grün. Ausschließlich `&&` verketten.
    - **Vor dem Abschließen syntaktisch prüfen:** `bash -n -c "<verify>"` über alle Tasks.
      Ein Verify mit Syntaxfehler ist ein garantiert roter Task.
    - **Remote-Vergleich nicht über lokale Refs.** `git rev-parse github/main` schlägt fehl,
      wenn der Ref lokal nie gefetcht wurde, obwohl der Push klappte. Stattdessen
      `test "$(git rev-parse HEAD)" = "$(git ls-remote <remote> refs/heads/main | cut -f1)"`.
    - **Kein `grep -q pattern && exit 1`-Muster** — das `||`/`&&`-Konstrukt feuert auch bei
      gefundenem Pattern falsch. `test -z "$(git status --porcelain)"` bzw.
      `if grep -q …; then exit 1; else echo ✅; fi` schreiben.
15. **Ein grep-Verify darf nicht auf den eigenen Erklärtext passen.** Verifiziert ein Task ein
    Dokument, das seine Regel selbst beschreibt, matcht das Suchmuster den Satz „keine mit
    Status: OFFEN" oder das Kleingeschriebene im Fließtext — der Task wird rot, obwohl die
    Arbeit stimmt. Muster an den Zeilenanfang binden (`^[[:space:]]*Status: OFFEN`),
    Flags nutzen (`test("dispatcher"; "i")` in jq) oder die Prüfung auf Code-Zeilen filtern
    (`line for line in src.splitlines() if not line.lstrip().startswith("#")`). Gilt auch für
    Source-Checks gegen Docstrings: Kommentare/Prosa, die das entfernte Muster nur erklären,
    müssen ausgenommen werden.
16. **Eine unbeantwortete Entscheidungsfrage blockiert die Ausführung nicht.** Läuft ein
    `clarify` in einen Timeout (oder antwortet der User nicht), nicht warten und nicht raten:
    den Teil der Arbeit erledigen, der unter **allen** Optionen identisch ist, und die
    Entscheidung ausdrücklich offen halten (im Plan-Task benannt, im Abschlussbericht
    genannt). Bei einer Weggabelung wie „Feature X behalten oder durch Config ersetzen“
    ist alles andere am Task unabhängig — Rückfrage später, Fortschritt jetzt.
12. **`plan_id` bleibt ASCII.** Ein `goal` mit `+`, `&`, `/` oder Umlauten kann die
    abgeleitete Plan-ID zerhacken, sodass `plan_create` zwar antwortet, der Plan aber nicht
    auffindbar/validierbar ist. ID vorab selbst festlegen (Buchstaben, Ziffern, Bindestrich),
    Sonderzeichen im `goal` vermeiden.
13. **Bei Template-Plänen zuerst `p0` abschließen.** `plan_create` mit `template` stellt
    einen Peer-Review-Task `p0` voran; der ist der aktuelle Task. Ein `plan_complete` auf
    den ersten eigenen Task scheitert mit `Task 'X' is not the current task. Aktuell: p0`.
    Reihenfolge: `plan_complete('p0', skip_review=true)` (der automatische Review lief schon
    beim Anlegen) → dann der erste eigene Task. Wer keinen p0 braucht: `p0_review=false`
    oder eigene `tasks`-Liste übergeben.
14. **Verify prüft ein Artefakt, das beim Abschließen schon existieren muss.**
    `verify: test -s <reportdatei>` schlägt fehl, wenn der Report erst nach dem
    `plan_complete` geschrieben wird — und das kostet eine Runde. Artefakt zuerst schreiben,
    dann abschließen. Wer den Verify an eine Datei bindet, die ein *späterer* Task erzeugt,
    baut die Prüfung falsch herum.

## Review-Workflow

1. Task mit `review_profile` anlegen
2. Task bearbeiten
3. `plan_review(task_id)` → Checks anzeigen
4. `delegate_task` mit `build_review_prompt()` → Reviewer prüft
5. `save_review_result(task_id, result)` persistieren
6. `plan_complete(task_id)` → Review-Gate gibt frei
7. Bei Fail: Issues fixen → erneut reviewen

## Externer Peer Review (Standard bei jedem Nicht-Trivial-Plan)

Johannes will vor der EXECUTE-Freigabe einen kritischen Zweitblick — **immer mit
`deepseek-v4.1-flash`**, nicht mit MiniMax. Aufruf über `~/bin/peer-review`:

```
peer-review                          # aktiver plan_follow-Plan
peer-review <plan.json>              # konkreter Plan
peer-review --file konzept.md        # freier Text (Konzept, Patch, Doku)
peer-review --context fakten.txt <plan.json>
```

Ablauf, der sich bewährt hat:

1. **Fakten ins `--context`-File legen**, nicht in den Chat: verifizierte Beobachtungen
   (Tool-Output, Messwerte, Quellcode-Stellen mit Datei:Zeile), das eigentliche Ziel des
   Users und was der Plan bewusst **nicht** tut. Ohne diesen Kontext erfindet der Reviewer
   Risiken, die an deinem Plan vorbeigehen.
2. **Findings in eine Datei schreiben**, je Finding eine Zeile `- F<n> <severity>` plus
   `Status: FIXED — <Maßnahme>` oder `Status: REJECTED — <Begründung>`. Kein Finding ohne
   Entscheidung; „offen" ist keine gültige Endlage.
3. **Plan überarbeiten**, nicht nur zur Kenntnis nehmen: neue Tasks einfügen, `verify`
   schärfen, Abhängigkeiten/A-Reihenfolge korrigieren, und dem User die Änderungen nennen.
4. `p0` („Peer Review + Korrekturen einarbeiten") erst abschließen, wenn die Findings-Datei
   vollständig entschieden ist (`test -f … && test $(grep -c '^- F' …) -ge N && ! grep -qE '^[[:space:]]*Status: OFFEN' …`).

Pitfalls:

- **Cloudflare 403 statt Auth-Fehler.** `opencode.ai` antwortet ohne `User-Agent`-Header mit
  `HTTP 403 / error code: 1010` (Browser Integrity Check) — das sieht wie ein Key-Problem aus,
  ist keins. Immer `User-Agent: HermesAgent/...` mitsenden.
- **`max_tokens` ≥ 16000.** Das Modell ist ein Reasoning-Modell: mit einem kleinen Budget
  frisst das Thinking alles, `content` kommt leer oder mitten im Satz abgeschnitten zurück.
- **Der Reviewer sieht nur, was du ihm gibst.** Abgeschnittene `verify`-Strings im Prompt
  (z.B. `t["verify"][:400]`) führt garantiert zu falschen Findings über „truncated commands".
  Immer das vollständige Plan-JSON zustellen.
- **Findings sind Vorschläge, nicht Wahrheit.** Manche Befunde beruhen auf Annahmen über
  APIs, die du schon geprüft hast (z.B. „P5 ist nicht umsetzbar") — dann mit Nachweis
  ablehnen und das im Status-File dokumentieren, statt den Plan zu verbiegen.
