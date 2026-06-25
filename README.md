# agentiker-plan-follow

Plan-Follow Plugin für Hermes Agent — strukturierte Planerstellung, Execution-Enforcement und Cross-Session-Koordination.

## Tools (38)

| Kategorie | Tools |
|-----------|-------|
| **CRUD** | plan_create, plan_current, plan_complete, plan_verify, plan_status, plan_update, plan_list, plan_abort, plan_delete, plan_select, plan_validate, plan_duedate, plan_archive, plan_restore, plan_template |
| **Review** | plan_review, plan_review_profiles, plan_review_save_result, plan_auto_review |
| **Git** | plan_git_init, plan_git_push, plan_git_status, plan_git_sync, plan_git_stash, plan_git_branch, plan_git_tag, plan_pr_create |
| **Misc** | plan_suggest, plan_time, plan_simulate, plan_sync, plan_decompose, plan_session, plan_lock, plan_notify, plan_history, plan_roadmap |

## Architektur

```
plan_follow/
├── __init__.py        — Plugin-Entry, TOOL_DESCRIPTIONS, PER_TOOL_SCHEMAS, 38 Tool-Registrierungen
├── plan_tools.py      — 38 Tool-Handler (Facade)
├── plan_core.py       — Re-Export Facade für tools/ Subpackage
├── plan_hooks.py      — pre_llm_call + post_tool_call + on_session_end Hooks
├── plan_roadmap.py    — Roadmap YAML-Management (11 Subcommands)
├── plan_templates.py  — Template-Engine (7 Built-in Templates)
├── plan_peer_review.py— Auto Peer Review (6 extrahierte Checks)
├── plan_review.py     — Review-Dispatch & Coverage-Check
├── plan_todo.py       — Todo-Liste aus Plan-Tasks
├── plan_coverage.py   — pytest-cov Wrapper
├── plan_suggest.py    — Projektanalyse → Task-Vorschlag
├── plan_sync.py       — GitHub/Markdown Sync
├── plan_decompose.py  — HTN-Style Compound Tasks
├── mcp_server.py      — MCP stdio+HTTP Server
├── coord_state.py     — Cross-Session Koordination
├── _fmt.py            — Rich-Formatierung
├── hooks/             — Hook-Subpackage (base.py, breaker.py)
└── tools/             — Plan-Core Subpackage (13 Module)

Weitere: tests/ (16 Test-Dateien, 1028+ Tests), dashboard/ (Hermes Dashboard Plugin)
```

## Tests

```bash
python3 -m pytest tests/ -q --no-header
# 1028+ tests, ~38s Laufzeit
```

## Installation

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - agentiker-plan-follow
```
