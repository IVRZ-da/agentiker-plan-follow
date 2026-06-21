# Changelog

## 1.4.0 (2026-06-21)

### Neue Features
- **Auto Peer Review**: `plan_create()` führt automatisch `run_peer_review()` gegen die 8-Punkte-Checkliste aus. Findings werden via `apply_findings()` eingearbeitet. Kein Parameter — immer aktiv.
- **TTS-Event-Marker**: `plan_create()` setzt `[TTS:event=plan_created]`, `plan_complete()` setzt `[TTS:event=task_completed]`. Marker erscheinen im Hook-Banner und werden vom Agenten via `text_to_speech()` umgesetzt.
- **Neues Modul `plan_peer_review.py`**: Enthält `run_peer_review()` mit 8 Checks (depends_on, verify, files, ordering, profiles, parallel_groups), `apply_findings()` und `PEER_REVIEW_CHECKS` Definitionen.

### Neue Tests
- 25 Tests für `plan_peer_review.py` (alle Checks, apply_findings, perfect plan)
- 7 Tests für TTS-Marker in `plan_hooks.py`
- 5 Integrationstests (plan_create → review → TTS, plan_complete → TTS, full chain)

### Infrastruktur
- Companion-Skill aktualisiert (Auto Peer Review + TTS Events dokumentiert)
- Version: 1.3.0 → 1.4.0
- Gesamte Test-Suite: 479 Tests, 0 failed
