# Plan-Follow Plugin

Hermes Plugin for structured plan creation, execution enforcement, and cross-session persistence via Honcho.

**Location:** `~/.hermes/plugins/plan_follow/`

## Tools

| Tool | Description |
|------|-------------|
| `plan_create(goal, tasks, repo)` | Create a plan with task dependencies |
| `plan_current()` | Show only the current task |
| `plan_complete(task_id)` | Complete task, verify, advance |
| `plan_verify()` | Drift detection against git diff |
| `plan_status()` | All tasks overview |
| `plan_update(task_id, changes)` | Living-document updates |

## Architecture

```
__init__.py     — Plugin entry: register 6 tools + pre_llm_call hook + skill
plan_core.py    — Data model, JSON persistence, Honcho REST API, health check
plan_tools.py   — Tool function implementations
plan_hooks.py   — pre_llm_call hook: task injection, health check, drift warning
skills/         — Plugin-provided companion skill
tests/          — Pytest test suite
```

## Integration

- **agentiker_code_intel (code_*):** Used for drift detection (code_search, code_impact)
- **Honcho:** Cross-session plan state via REST API (localhost:8001)
- **Serena MCP:** Project activation only
- **Firecrawl:** Web search/scrape (not directly used by plugin, but health-checked)

## Testing

```bash
pytest tests/ -v
```
