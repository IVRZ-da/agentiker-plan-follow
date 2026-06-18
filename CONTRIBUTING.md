# Contributing

## Development

```bash
# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Tests
python -m pytest tests/ -v
```

## Plugin Structure

```
plugin.yaml              # Manifest
__init__.py              # Entry point — register(ctx)
plan_core.py             # Core logic
plan_tools.py            # Tool handlers (12 tools)
plan_hooks.py            # Hook handlers
plan_templates.py        # Plan templates
skills/                  # Companion skill
  plan-follow.md
tests/                   # pytest tests
  conftest.py            # Shared mocks
```

## Pull Request Process

1. Ensure tests pass: `python -m pytest tests/ -v --tb=short`
2. Update CHANGELOG.md with version and changes
3. Bump version in plugin.yaml
4. Submit PR via Forgejo
