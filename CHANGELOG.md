# Changelog

## 0.5.7 (2026-06-25)
- **Monolith-Split:** plan_tools.py (1237 Zeilen, 36 Handler) → tools/handlers_crud.py + handlers_git.py + handlers_review.py + handlers_misc.py
- **Re-Export Facade:** plan_tools.py re-exportiert alle Handler via `from .tools.handlers_* import ...`
- **Bug-Hunt Fixes:** coord_state.py fcntl.flock(), Forgejo API Base env-var, MCP Auth, sys.path Cache, NOTIFICATIONS_FILE konsolidiert
- **Test-Infrastruktur:** _parse_result() unterstützt jetzt Multi-Line-Values, ast.literal_eval, None/True/False-Konvertierung, fmt_err/fmt_info-Erkennung

## 0.5.6 (2026-06-24)
- **Hook-System Upgrade:** Smart Banner mit TTL-Cache, on_session_end Hook, Circuit Breaker
- **Modularisierung:** plan_hooks.py → hooks/base.py + hooks/breaker.py
- **Health-Check-Fix:** `find_spec()` → `import_module()` — keine falschen "degraded"-Meldungen mehr
- **tools/__init__:** Vollständige Exports für alle 13 Submodule
- **plan_peer_review:** Complexity 43→6 — 6 Check-Funktionen extrahiert aus run_peer_review()
- **Banner-Builder:** 9 Funktionen (315 Zeilen) aus plan_hooks.py in hooks/base.py ausgelagert
- **Test-Kompatibilität:** plan_tools.py re-exports fmt_ok/fmt_err für Mock-Kompatibilität
- **Bugfix:** Banner-Cache-Key health→health_v2 (TTL 300s→600s)

## 0.5.5 (2026-06-23)
- Coverage-Jagd 63%→86% auf plan_tools.py (647 Zeilen, 30+ Handler)
- 8 neue Tools: plan_suggest, plan_time, plan_simulate, plan_sync, plan_decompose, plan_review_save_result
- Pre-Commit Coverage-Gate (fail_under=90)
- Multi-Plan-Sequential-Workflow: 1 Roadmap + N Pläne

## 0.5.4 (2026-06-23)
- Cache-Fix: plans_index wird nach Plan-Abbruch geleert
- Bugfix: plan_create ignoriert plan_id (gefixt)
- Bugfix: parallel_groups nicht editierbar (gefixt)

## 0.5.3 (2026-06-22)
- 4 neue Templates: multi, docs, infrastructure, go-setup, security
- Auto-Detect für verify-Commands (package.json→npm test, go.mod→go test)
- Review-Gate: auto-default "unit-test" für non-p0 Tasks

## 0.5.2 (2026-06-21)
- Modul-Split: plan_core.py (1774 Zeilen) → tools/ Subpackage (10 Module)
- Re-Export Facade plan_core.py für Rückwärtskompatibilität
- Coverage-Optimierung auf 46%→98% in _fmt.py

## 0.5.1 (2026-06-20)
- Template-Pflicht: plan_create erfordert zwingend ein Template
- TDD in Code-Templates: RED→GREEN→REFACTOR
- 42 Test-Failures gefixt, 483 Tests gesamt
- Peer Review Enforcement: p0 Auto-Peer-Review nach plan_create

## 0.5.0 (2026-06-19)
- Initiale Veröffentlichung als agentiker-plan-follow
- 24 Tools: plan_create/current/complete/verify/status/update/review/list/abort/delete/select/validate/duedate/archive/restore/roadmap/template
- Git-Integration: plan_git_* Tools
- Cross-Session Koordination: coord_state.py
- MCP Server für externe Tools
- Dashboard Plugin für Hermes Dashboard
- Hot Path: plan_core.py (3 Caller)
