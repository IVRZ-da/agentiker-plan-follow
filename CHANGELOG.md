# Changelog

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
  gegen den eigenen Plan. Tasks, die Reviews *abarbeiten* („Peer-Review-Kommentare
  einarbeiten"), bleiben bewusst prüfpflichtig.
- **Kein erfundenes pytest für Ops-Pläne:** ohne Projekt-Marker (package.json, pyproject.toml,
  go.mod, Cargo.toml, composer.json, requirements.txt, tox.ini, pytest.ini, Makefile, Gemfile,
  pom.xml, build.gradle[.kts], deno.json, uv.lock, *.csproj, *.sln) wird kein Testbefehl
  eingesetzt. Ohne `repo` wird nicht auf das Agenten-cwd zurückgefallen; `repos` und `~` werden
  aufgelöst.
- **Severity-Trennung:** fehlender verify = Hinweis (IMPORTANT); bewusst wertloser verify
  (`echo`, `true`, `:`) = CRITICAL, auch ohne Projekt-Marker.
- Vorbestehender Bug behoben: die `|| true`-Maskierungsprüfung lag eingerückt im grep-Zweig
  und griff bei `make test || true` nie.

### 🟠 Eingaben robust — ein Fehlerbild statt fünf
- **`normalize_tasks()`** für alle Zweige (top-level `tasks`, `params.tasks`, Template-Tasks):
  Liste, Dict `{id: {...}}`, `{"tasks": …}`, JSON-String, Einzel-Task, Liste von Strings.
  `id` wird String (numerische IDs machten den Task nach dem Reload unauflösbar),
  doppelte IDs werden eindeutig (`T1` → `T1-2`) statt still überschrieben,
  fehlende `id` laufend vergeben, `name` aus `title`/`task`/`summary`/`description`.
  Korrekturen werden unter `normalized` ausgewiesen (sichtbar gekappt).
- **Ein Fehlertext** nennt beide Optionen (`tasks` ODER `template`), mit kopierfertigem Beispiel
  und der Template-Liste. Kaputtes JSON wird als solches gemeldet, nicht als „keine Tasks".
- **`task-dict`-Falle:** ein einzelner Task (`{id, name, …}`) erzeugte vorher drei
  Phantom-Tasks mit den IDs `id`, `name`, `verify`.

### 🟠 Ehrliche Fehlerpfade
- **Review läuft VOR dem Persistieren** (Draft): ein blockierter Plan hinterlässt keine Datei
  mehr auf der Platte. Vorher stand „nicht erstellt" in der Antwort, die Datei lag aber da.
- **`fmt_err` statt `fmt_ok`** bei Blockade und bei Template-Fehlern — keine grüne Success-Box
  mit `error`-Feld mehr.
- **Response kompakt:** max. 3 Findings, nach Severity priorisiert, plus `peer_review_summary`
  mit Zählern und `peer_review_more`. Vorher bis 24 KB Finding-Lawine; `auto-fixes applied`
  wird nur noch behauptet, wenn wirklich etwas angewandt wurde.

### 🟢 plan_follow wird Standard statt Option
- **Die 5 Hot-Path-Tools liegen eager im Tool-Set** (`plan_create`, `plan_current`,
  `plan_complete`, `plan_update`, `plan_status`). Hermes deferrt Plugin-Tools grundsätzlich
  hinter `tool_search`; `plan_create` war damit nur über `tool_describe` + `tool_call`
  erreichbar (2 Extra-Turns, „Tool does not exist"-Fehler). Gemessen: 1834 Tokens Schema pro
  Turn für die 5, die übrigen 34 bleiben deferred (plan_roadmap allein ~850). Fail-open: fehlt
  oder ändert sich `_HERMES_CORE_TOOLS`, bleibt es beim Deferral, mit Warning im Log.
  Bekannter Nebeneffekt: die 5 zählen im GUI-Plugin-Panel als „builtin".
- **Einmaliger Nudge ohne aktiven Plan:** ab Turn 3, 1× pro Session, nennt den exakten
  Aufrufweg (eager bzw. `tool_call(name='plan_create', arguments={...})`), jede Zeile ≤ 90
  Zeichen (der Banner schneidet bei 96). Nicht in delegierten Kindern, nicht auf
  cron/webhook/headless/kanban/api. Abschaltbar: `PLAN_FOLLOW_NUDGE=0`.

### 🟡 Doku, Tests, Umgebung
- **Schema der echten Toleranz angepasst:** `tasks` ist nicht mehr nur `array` mit
  `required [id, name]` — sonst weist Hermes' Bridge (`tool_call`) genau die Dicts,
  `title`-Tasks und id-losen Tasks ab, die `normalize_tasks` reparieren kann. `kind` und
  `title` sind deklariert, numerische IDs erlaubt.
- **`kind: review` wird persistiert** (`create_plan`-Whitelist), sonst verschwand die
  Review-Ausnahme nach einem Reload wieder.
- **`depends_on` wird stringifiziert** wie die Task-ID: numerische Abhängigkeiten fielen
  vorher still weg (Review meldete „depends_on 1 does not exist", Auto-Fix löschte die
  Abhängigkeit, Plan hatte am Ende `depends_on: []` — ohne Hinweis).
- **Template-Platzhalter entfernt:** `echo 'build: nicht konfiguriert'` & Co. sind
  Scheinprüfungen und blockierten `deploy`/`feature`/`refactoring`/`infrastructure` ohne
  `repo`. Jetzt leer = Hinweis statt Blocker.
- **`free`/`multi` ohne echte Tasks** werden abgelehnt (vorher entstand ein Plan, der nur
  aus dem p0-Review-Task bestand — und der ist von allen Prüfungen ausgenommen).
- `status=warning` nur noch bei tatsächlich offenen critical Findings (vorher auch bei
  „1 auto-fix, 0 offen").
- Nudge-Skipliste enthält `api_server` (Hermes' Plattform-Key) statt nur `api`.
- `coverage.json` (kaputtes 13-Byte-Artefakt) nicht mehr getrackt.
- `plan_create`-Beschreibung und Schema sagen die Wahrheit (kein „TEMPLATE IS REQUIRED",
  `free` in der Template-Liste, Beispiel, Review-Semantik). Companion-Skill v1.7.0: korrekter
  Aufrufweg, task/template-Semantik, Ops-Plan-Abschnitt neu.
- Templates aufgeräumt: Review-Schritte mit `kind: review`, Status-`echo`-Verifies entfernt,
  `research`-Checks ohne maskierendes `echo`.
- **+99 Tests** (1521 → 1620, kein Skip), u.a. `tests/test_plan_create_contract.py` mit den fünf
  Fehlersignaturen aus dem Incident als Contract. Coverage 91,03 % (Gate 90).
- Test-Umgebung dokumentiert: das kaputte repo-lokale `.venv` (ohne pip/rich) ist entfernt,
  CONTRIBUTING nennt `HERMES_PYTHON` / `~/.hermes/hermes-agent/venv/bin/python3`,
  `pyproject.toml` hat `[project.optional-dependencies] dev`. `.coverage` nicht mehr getrackt.

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
- **Release im Lifecycle**: `complete`/`abort`/`archive`/`delete` und Session-Ende; Housekeeping läuft auch ohne aktiven Task (vorher early return → nichts wurde je aufgeräumt).
- **Heartbeat + Owner-Liveness**: Locks tragen `heartbeat`; `cleanup_stale_locks` gibt nur frei, wenn zusätzlich die Besitzer-Session fehlt oder selbst stale ist. Ein 45-Minuten-Lock einer aktiven Session bleibt.
- **Einheitliche Schwellen** `LOCK_STALE_MIN=30` / `SESSION_STALE_MIN=60` für Anzeige und Cleanup (vorher 30 vs. 120).
- **Session-ID aus dem Hook-Payload** statt prozessglobalem `get_session_id()`.

### 🟡 Health & Tool-Check
- **Kein `find_spec`/`import_module` mehr für Fremdmodule**: Der Check maß `sys.path`. Im Hermes-Prozess liegt das Plugin-Verzeichnis dort nicht — deshalb „plan_follow/code_intel nicht importierbar“, während die Tools liefen. Jetzt `sys.modules` + Selbst-Check der eigenen Attribute.
- **Flap-Dämpfung**: DEGRADED erst nach zwei aufeinanderfolgenden Fehlschlägen; ein einzelner Fehlschlag ist ein Hinweis.
- **Zeitstempel** (`checked_at`, „geprüft vor Ns“) und **HTTP-Checks nur mit `PLAN_FOLLOW_VERBOSE_HEALTH=1`** (kosteten bis zu 6 s pro Turn).
- **Tool-Check-Banner**: eine Zeile aus dem geladenen Zustand, keine Imports, keine hartkodierte Tool-Hierarchie („unbekannt“ = `?`, nicht ❌).
- **Fehler werden sichtbar**: jeder Banner-Teil hat einen eigenen Guard und rendert `⚠️ Banner-Teil <name> fehlgeschlagen: <Typ>` statt `except Exception: pass`.

### Changed (Verhalten)
- **`review_failed`-TTS-Event entfernt** — es hatte nie einen Writer (nur Leser).
- **`plan_follow/hooks/` gelöscht** — zweiter Hook-Baum, dessen `__init__.py` ein nicht existierendes `hooks/base.py` importierte; `breaker.py` war eine Kopie. `tests/test_breaker.py` prüft jetzt `plan_hooks`.
- **Layout**: Box wird zentral gepolstert (einheitliche Breite, < 1500 Zeichen im Normalfall).
- **Drift-Warnung** einmal pro Änderung statt in jedem Turn.

### Tests
- **1556 Tests** grün (vorher 1521). Neu: `test_banner_freshness`, `test_tts_pure`, `test_lock_lifecycle`, `test_health_flap`, `test_banner_provenance`, `test_banner_side_effects`, `test_save_conflict`, `test_epilogue`; Test-Migration für `test_hooks`, `test_hooks_coverage`, `test_tts_markers`, `test_health`, `test_plan_follow`, `test_review_integration`.
- `scripts/check_isolation.sh`: Ausnahme für `shared/tts_queue.json|lock`; Lauf mit laufendem Gateway bleibt grün.

## [0.5.32] — 2026-11-10

### 🔴 Critical — Datenverlust durch die Testsuite
- **Test-Isolation auf Import-Ebene** — `tests/conftest.py` bog bisher nur `plan_core.PLANS_DIR` um (und das auch nur in 7 von 37 Testfiles). Die autouse-Fixture schrieb `"{}"` in ALLE `*.json` des ECHTEN `~/.hermes/plans` und `rmtree`'te Unterordner. Am 10.11.2026 wurden so 81 Pläne, `plans_index.json`, `archived/` und `templates/` zerstört — bei 1480/1480 grünen Tests. Jetzt werden alle sieben Import-Zeit-Pfadkonstanten (`plan_core.PLANS_DIR/PLANS_INDEX/ARCHIVE_DIR/ROADMAPS_DIR`, `plan_templates.TEMPLATES_DIR`, `plan_suggest._TRACKING_FILE`, `coord_state.SHARED_DIR`) auf ein tmp-Root umgebogen, inkl. fail-fast-Assertion pro Test. `except Exception: pass` im destruktiven Block entfernt.
- **Write-Guard im Produktionscode** — neues `tools/paths.py` mit `assert_writable()`; aufgerufen in allen Schreib-Primitiven (`_save_plan`, `_update_plans_index`, `_clear_plans_index`, `_ensure_dirs`, `coord_state._atomic_write`, `save_user_template`, `delete_user_template`, `_ensure_tracking_file`, `archive_plan`, `delete_plan`, `restore_plan`, `plan_git_init`). Aktiv bei `PLAN_FOLLOW_TEST_GUARD=1`.
- **`_save_plan` verweigert kaputte Pläne** — `ValueError` ohne `plan_id` oder ohne `tasks`; vor dem Überschreiben eines Plans mit Inhalt wird ein `.json.bak` angelegt.
- **Env-Overrides für Isolation** — `PLAN_FOLLOW_PLANS_DIR`, `PLAN_FOLLOW_ROADMAPS_DIR`, `PLAN_FOLLOW_SHARED_DIR` wirken bereits beim Import (auch für Subprozesse/Skripte).
- **`scripts/check_isolation.sh`** — CI-Beweis: Manifest vor/nach der vollen Suite muss identisch sein.

### Fixed
- **Hook-Regression `session_end` → `on_session_end`** — der falsche Name wurde bei jedem Load nur als WARNING gemeldet; `_register_hooks` prüft die Namen jetzt gegen die Hermes-`VALID_HOOKS`-Liste und protokolliert Fehler als ERROR (`HOOK_REGISTRATION_ERRORS`).
- **Companion-Skill wurde nie registriert** — `_register_skill` suchte `skills/plan-follow.md`, real heißt die Datei `skills/SKILL.md`. Jetzt Fallback auf beide Namen + `logger.error` wenn keine Datei existiert; der Test in `test_init.py` ist nicht mehr bedingt formuliert.
- **Banner-Recovery ohne Session-Leak** — nach einem Hermes-Restart blieb der Task-Banner stumm, bis ein `plan_`-Tool lief. Jetzt wird beim ersten Turn einer Session (`is_first_turn`) einmalig von Disk adoptiert — aber nur, wenn die Session den Plan besitzt (`coord_state.get_session`), sonst nicht. Regressionstest: zwei Sessions, kein Cross-Banner.
- **Circuit-Breaker las `error`** — Hermes sendet `error_type`/`error_message`; der Fallback auf `result` schrieb die komplette Tool-Ausgabe (bei `terminal` die volle stdout) als "Fehlertext" in den Banner. Jetzt `error_type: error_message`, Platzhalter wenn leer.
- **`plan_list` unbrauchbar** — 82 Einträge, 80 leere 2-Byte-Dateien, alle als `is_active: true` (Vergleich `None == None`). Leere/beschädigte Dateien werden übersprungen, `is_active` nur bei gesetzter `active_plan_id`, Sortierung nach `created`, Default-Limit 20 mit `total`/`has_more`.
- **Honcho-Fallback entfernt** — `POST /v3/workspaces/{ws}/conclusions/query` ist semantische Suche (HTTP 422 ohne observer/observed), Workspace/Peer passten nicht zu `~/.hermes/honcho.json`, und Honcho speicherte nur die `plan_id`. `_load_plan_state_from_honcho()` ist jetzt ein No-op.
- **`plans_index.json`-Timestamps** — `active_since` war naiv/lokal, `last_updated` UTC-aware (Vergleiche 1-2h falsch, `TypeError` möglich). `created` wird UTC-aware geschrieben, Bestandswerte werden konvertiert (`_to_utc_iso`).
- **`rich` und `PyYAML` waren undeklariert** — das Plugin-`.venv` konnte 13 Testdateien nicht einsammeln. `_fmt.py` hat jetzt einen reinen Text-Fallback (12 Formatter, 300 Aufrufstellen unverändert), `plan_templates.py` behandelt PyYAML optional; beide sind in `pyproject.toml` (`dependencies`) und `plugin.yaml` (`python_dependencies`) deklariert. `build-backend` korrigiert (`setuptools.build_meta`).

### Changed (Verhalten)
- **`create_plan()` gibt `None` bei leeren Tasks** — statt in die neue `_save_plan`-Sperre zu laufen (`ValueError`). Rückgabetyp jetzt `Optional[str]`.
- **`plan_list`-Sortierung** — `created` hat nur Sekundengenauigkeit; bei Gleichstand entscheidet die Datei-mtime (zuletzt geschrieben = neuer).
- **`plan_roadmap` mit fehlendem `name`** — der Hinweis nennt jetzt den Parameter `name=<name>`, auch wenn (noch) keine Roadmap existiert.
- **Aufräumarbeiten nach dem Datenverlust** — die 80 leeren 2-Byte-Plan-Dateien in `~/.hermes/plans` wurden gelöscht; erhalten bleiben die zwei echten Pläne (`2026-11-10-code-intel-hermes-v0231-kompatibilitaet`, `2026-11-10-plan-follow-v0231-fixes`). Keine Rekonstruktion aus `state.db`.

### Tests
- **An das neue Verhalten angepasst** — `test_list_plans_skips_missing_tasks_key` (Dateien ohne `tasks` werden übersprungen), `test_on_post_tool_call_error_result_fallback` (kein `result`-Fallback, Platzhalter statt Tool-Output), `test_git_skip_on_no_git` (Plan braucht mindestens einen Task), `TestLoadPlanStateFromHoncho` (5 Tests durch 2 No-op-Assertions ersetzt).
- **Neu** — `tests/test_status.py` (8), `tests/test_breaker_fields.py` (5), `tests/test_write_guard.py` (14), `tests/test_hook_names.py` (4), `tests/test_fmt_fallback.py` (2), `tests/test_banner_recovery.py`, `tests/test_base.py::TestIndexTimestamps` (4), `tests/test_templates.py::TestP0OptOut` (5).
- **`scripts/check_isolation.sh`** — Manifest-basierter Beweis, dass die Suite `~/.hermes/{plans,roadmaps,shared}` unberührt lässt (ignoriert nur Laufzeitdateien des Live-Gateways).

### Added
- **`p0_review`-Opt-out** — `plan_create(p0_review=false)` (bzw. `params.p0_review`) überspringt den automatischen p0-Peer-Review-Task. Default bleibt `true`.
- **Doku/Manifest auf Ist-Stand** — `plugin.yaml` nennt jetzt 39 Tools, 3 Hooks, 13 Templates; `hooks` enthält `on_session_end`. Companion-Skill auf v1.5.2 (Banner-Frequenz, Recovery-Semantik, Write-Guard).


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
- **Subagent-Integration dokumentiert** — Auto-Review, Profiles, Hooks
- **Header aufgewertet** — Inspirierender Title + aktuelle Metriken (v0.5.27, 1480+ Tests)
- **Stale Version gefixt** — Architektur-Sektion zeigte v1.1.0 statt v0.5.x

## [0.5.26] (2026-06-29)

### Removed
- **Hardcodierte Frameworks:** `_detect_project_type()` entfernt medusa, nextjs, react dependency-scan
- **Dead Code:** Duplicate Tool-Handler aus plan_suggest.py (Relikt aus Monolith-Split v0.5.7)

### Changed
- **Framework Detection:** _detect_project_type() ist jetzt rein marker-basiert (package.json, go.mod, pyproject.toml, Cargo.toml, composer.json, Gemfile)

### Tests
- 5 Framework-spezifische Tests entfernt, 60 Tests passed


## [0.5.25] - 2026-06-28

### Changed
- **Performance: Tool-Schema-Deduplizierung** — `__init__.py` von 933→143 Zeilen (-86%), Tool-Metadaten via Import aus `tools/descriptions.py` + `tools/schemas.py`
- **Performance: Koordinations-Banner** — 30s TTL Cache + Change-Detection + Compact-Mode (1-Zeiler wenn unverändert)
- **Pre-Commit Hook** — Coverage-Gate nur bei vollem Test-Durchlauf, MODULE_TEST_MAP erweitert

### Fixed
- **Test-Isolation:** 9 Test-Failures in test_hooks_coverage, TestReviewBanner, mcp_server_coverage gefixt
- **Cache-Poisoning:** conftest.py mit autouse Fixture für Koordinations-Cache-Reset
- **pre-commit hook:** Ruff I001 Import-Order in Tests

### Added
- **test_base.py:** 10 Tests für tools/base.py Error-Handling (uuid, JSON/OSError, __getattr__)
- **test_task.py:** 6 Tests für tools/task.py Edge Cases (plan_id_override, parallel_groups)
- **test_plan_mgmt.py:** 9 Tests für tools/plan_mgmt.py (relative dates, validation, errors)
- **test_plan_core.py:** 14 Tests für plan_core.py (__getattr__ lazy imports, __setattr__, HONCHO defaults)

## [0.5.24] - 2026-06-27

### Fixed
- **Test-Failures:** 3 pre-existing Failures in test_auto.py gefixt (_get_repos os.getcwd Mock)
- **Coverage-Lücken:** health.py 100%, validation.py 93.58%, roadmap_data.py 88.28%
- **mcp_server.py:** sys.path.insert(0) durch from . import plan_core ersetzt

### Added
- **test_health.py:** 16 Tests für health.py Error-Pfade
- **test_validation.py:** 19 Tests für validate_plan (deps, profiles, groups, git-branch)
- **test_roadmap_data.py:** 23 Tests für roadmap CRUD + Parser

## [0.5.23] - 2026-06-27

### Added
- **plan_duedate: relative Dates** — unterstützt jetzt +2d, +1w, tomorrow (ISO-8601 bleibt)
- **plan_git_*: repo-Parameter** — optionaler repo=<path> pro Tool + CWD .git Fallback

### Fixed
- **_format_phase_detail character-split:** Gleicher Type-Guard wie in _phase_to_plan_tasks

## [0.5.22] - 2026-06-27

### Fixed
- **parallel_groups KeyError:** Auto-Create fehlender Task-IDs aus parallel_groups in create_plan()
- **plan_roadmap to_plan character-split:** Type-Guard in _phase_to_plan_tasks() bei tasks-als-String
- **plan_roadmap show character-split:** Gleicher Type-Guard in _format_phase_detail()

## [0.5.21] - 2026-06-27

### Removed
- **P6: Dead Code Bereinigung** — backward-compat stubs tools/handlers_*.py gelöscht (51 Zeilen)
- **conftest.py:** Veraltete handler_*-Einträge aus mock_fmt-Fixture entfernt

## [0.5.20] - 2026-06-27

### Added
- **P2: tools/git.py Coverage 42%→100%** — 59 neue Tests für alle 9 Git-Handler
- **P5: mcp_server.py Coverage 74%→94.74%** — 15 neue Tests für MCP-Server
- **Multi-Template Bugfix:** Falscher Indent in Zeile 462 gefixt (ERROR immer returned)

### Changed
- **Gesamt-Coverage: 90.42% → 93.52%** (4584 Stmts, 297 Miss)
- **1388 Tests** (+75 seit v0.5.19)

## [0.5.19] - 2026-06-27

### Added
- **Coverage-Sprint P1:** Coverage von 82.88% auf 90.34% gesteigert
  - `hooks/breaker.py` 0%→100%, `hooks/__init__.py` 0%→100%
  - `tools/config.py` 0%→100%, `tools/schemas.py` 0%→100%, `tools/descriptions.py` 0%→100%
  - `tools/coordination.py` 68%→100%
  - `plan_hooks.py` 87%→100%, `plan_review.py` 81%→100%, `plan_sync.py` 87%→100%
  - `plan_templates.py` 52%→99%, `plan_todo.py` 70%→92%
  - `plan_decompose.py` 85%→96%, `plan_peer_review.py` 88%→93%
- **Neue Test-Dateien:** test_breaker, test_config_module, test_coordination, test_templates_and_todo, test_hooks_coverage, test_decompose_coverage, test_sync_coverage, test_review_coverage, test_peer_review_coverage
- **Bug gefunden:** `multi` Template in plan_templates.py Z.462 — falscher Indent, immer Error

## [0.5.18] - 2026-06-27

### Changed
- **Modul-Split abgeschlossen:** handlers_*.py Funktionen in logische Module verteilt
  - `tools/handlers_crud.py` → `tools/task.py`, `tools/status.py`, `tools/auto.py`, `tools/plan_mgmt.py`, `tools/validation.py`, `plan_templates.py`, `plan_suggest.py`
  - `tools/handlers_git.py` → `tools/git.py`
  - `tools/handlers_misc.py` → `coord_state.py`, `plan_decompose.py`, `plan_sync.py`, `plan_suggest.py`
  - `tools/handlers_review.py` → `tools/review.py`
- **plan_tools.py:** Importiert jetzt direkt aus neuen Modulen statt via backward-compat Stubs
- **conftest.py:** `mock_fmt`-Fixture patcht jetzt alle neuen Modul-Standorte

## [0.5.17] - 2026-06-27

### Changed
- plan_tools.py Module-Split: 37 Handler in tools/handlers_*.py ausgelagert
- plan_tools.py ist jetzt eine Re-Export Facade (Rückwärtskompatibel)
- Coverage von 71% → 83% durch Wegfall von 914 Zeilen Dead Code

### Removed
- tools/handlers_crud.py, handlers_git.py, handlers_misc.py, handlers_review.py:
  Alte ungenutzte Duplikate gelöscht, durch echte Implementierungen ersetzt

## [0.5.16] - 2026-06-26

### Added
- Cross-Session Warnung in post_tool_call Hook (terminal() auf test/build/git)
- Cross-Session Git-Check in handlers_git.py (sync/push prüft andere Sessions)
- Cross-Session Git-Check in auto.py (auto_commit/auto_push prüft andere Sessions)
- Coordination-Banner: Repo-Konflikt-Warnung bei Überschneidungen

## [0.5.15] - 2026-06-26

### Fixed
- coord_state.py: fcntl flock für Race-Condition-Schutz bei atomic_read/atomic_write
- coord_state.py: logger.warning bei atomic_write-Fehlern hinzugefügt
- coord_state.py: logger.debug bei Notification-Fehlern hinzugefügt
- plan_hooks.py: logger.debug in _cached_or_fresh() bei fetcher-Fehlern
- plan_hooks.py: logger.debug in allen banner-builder except:pass Blöcken (10+ Stellen)
- plan_tools.py: f-string → %s-Formatierung in logger.warning() (P1 Bug)
- plan_tools.py: Exception-Message sanitizing in plan_pr_create_tool

## [0.5.14] - 2026-06-25

### Fixed
- plan_update Bug: plan_id wird durchgereicht

## [0.5.10] - 2026-06-24

### Changed
- Kanban-Integration revertiert
- Cross-Session Koordination via coord_state.py
