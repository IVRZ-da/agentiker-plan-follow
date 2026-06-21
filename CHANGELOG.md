# Changelog

## 1.5.1 (2026-06-22)

### Breaking — Template-Zwang

- **`template` required in `plan_create()`** — manuelle Tasks werden nicht mehr akzeptiert. Ohne Template: Fehler.
- **`tasks`-Parameter entfernt** aus `plan_create`-Schema — Tasks kommen nur noch aus Templates

### Neue Features

- **p0 Auto-Peer-Review:** `expand_template()` stellt automatisch p0 (Peer Review) vor alle Template-Tasks. Erster Code-Task hängt von p0 ab.
- **TDD in `feature` Template:** RED → GREEN → REFACTOR → Docs (vorher: Spec → Implement → Test → Docs)
- **TDD in `fix` Template:** RED → GREEN (schreibt Test der den Bug zeigt, dann fixen)

### Skills

- **plan-follow.md:** v1.4.3 mit Template-Pflicht, p0, TDD dokumentiert

## 1.5.0 (2026-06-21)

### Major — Module-Split + Code-Qualität (9 Phasen)

- **Module-Split:** `plan_core.py` (1774 Zeilen) → `tools/` Subpackage mit 10 Submodulen
  - `tools/base.py` — Module-State, Persistenz, Session-ID
  - `tools/coordination.py` — Honcho, Git, Lock-Integration
  - `tools/task.py` — Task CRUD (create, complete, set_active)
  - `tools/status.py` — Status, Liste, Progress-Formatierung
  - `tools/plan_mgmt.py` — Abort, Delete, Due-Dates, Archive
  - `tools/auto.py` — Auto-Verify, Auto-Commit, Drift
  - `tools/review.py` — Review-Helper
  - `tools/health.py` — Health-Check
  - `tools/validation.py` — Plan-Validierung (DAG, orphan, profiles)
  - `tools/roadmap_data.py` — Roadmap-Datenfunktionen
- **Shared State:** `tools/state.py` — STATE-Singleton ersetzt 4 verteilte Global-Variablen
- **Config-Resolution:** `tools/resolver.py` — Monkeypatch-safe Config-Resolution für Test-Kompatibilität
- **`plan_core.py`:** Re-Export Facade mit `__getattr__`/`__setattr__` für Rückwärtskompatibilität

### Refactoring
- **PyYAML statt eigenem Parser:** `_parse_yaml_simple` von 93 Zeilen auf 3 Zeilen reduziert (direktes `yaml.safe_load`). 7 Template-YAML-Dateien in `data/templates/`
- **Complexity-Reduktion:** `on_pre_llm_call` von 52 auf 7 Branches reduziert durch Extraktion von 9 Sub-Funktionen
- **Companion-Skill:** Version 1.0.1→1.4.2, Tools 12→24 dokumentiert, Templates 6→7, Architektur ergänzt

### Coverage-Verbesserungen
- `_fmt.py`: 46% → 98% (neue `test_fmt.py` mit 45 Tests)
- `plan_templates.py`: 45% → 99% (neue `test_templates.py` mit 29 Tests)
- `plan_coverage.py`: 50% → 86% (neue `test_coverage.py` mit 28 Tests)
- `__init__.py`: 35% → 98% (neue `test_init.py` mit 16 Tests)
- **Gesamtcoverage:** 79% → ~88%

### Neue Features
- **pytest-cov Fallback:** Graceful Degradation wenn pytest-cov nicht installiert ist
- **Template-YAML-Dateien:** 7 Referenz-Templates in `data/templates/*.yaml`

### Tests
- **601 Tests (vorher 483), 0 failed**
- 4 neue Test-Dateien: `test_fmt.py`, `test_templates.py`, `test_coverage.py`, `test_init.py`
- 118 neue Tests insgesamt
- Subprocess-Mocking, Filesystem-Isolation, Registry-Mocking

## 1.4.3 (2026-06-22)

### Fixes
- **Flaky Git-Tests behoben:** 3 Tests in `test_coord_state.py` schlugen im Combined Run fehl
  - Root Cause: `shutil.move()` zwischen ext4 und tmpfs verursachte cross-device link Fehler
  - Fix: `subprocess.run(["cp", "-a"])` + `["rm", "-rf"]` statt `shutil.move()`
  - Resultat: 557 passed, 0 failed

## 1.4.2 (2026-06-22)

### Tests — E2E-Konvertierung
- **E2E-Tests in Unit-Tests konvertiert:** Alle 29 E2E-Tests (gated via E2E_TEST=1) wurden konvertiert:
  - 25 Plan-Tests (tools + plan_more): **100% redundant** — existierende Unit-Tests decken alles ab
  - 3 Roadmap-Tests: **2 neue Tests** in `test_plan_follow.py` (create+list, create + list)
  - 1 Workflow-Test: **redundant**
  - 4 Lückentests ergänzt: `TestPlanValidateTool`, `TestPlanVerifyTool`, `TestRoadmapDelete` in `test_plan_follow.py`
- **`test_e2e/` Verzeichnis gelöscht** — `_setup_plan_follow_package()` conftest entfällt
- Resultat: 483 passed, 0 von E2E_TEST abhängig

## 1.4.1 (2026-06-22)

### Bug Fixes
- **Plugin-Start repariert**: plan_tools.py importierte `plan_roadmap_handler` nicht aus `plan_roadmap.py` — `AttributeError` beim Laden des Plugins. Fix: `from .plan_roadmap import plan_roadmap_handler` ergänzt.

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
