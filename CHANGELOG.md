# Changelog

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
