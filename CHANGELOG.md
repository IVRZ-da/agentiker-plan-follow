# Changelog

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
