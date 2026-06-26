# Changelog

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
