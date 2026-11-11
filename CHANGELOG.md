# Changelog

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
