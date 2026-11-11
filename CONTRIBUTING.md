# Contributing

## Development

Dieses Plugin laeuft im Hermes-Prozess und wird mit **dessen** Interpreter
getestet. Ein repo-lokales `.venv` ist eine Falle: es driftet gegen die
Hermes-Umgebung und findet dann weder `rich` noch `pytest`.

```bash
# Interpreter bestimmen (der Pre-Commit-Hook nutzt denselben Weg)
HERMES_PY="${HERMES_PYTHON:-$HOME/.hermes/hermes-agent/venv/bin/python3}"

# Tests (voller Lauf, ~80 s)
cd ~/.hermes/plugins/plan_follow
"$HERMES_PY" -m pytest tests/ -q

# Einzelne Datei / Auswahl
"$HERMES_PY" -m pytest tests/test_plan_create_contract.py -q -k normalize

# Coverage (Gate: >= 90 %)
"$HERMES_PY" -m pytest tests/ -q --cov=plan_follow --cov-report=term-missing

# Lint
ruff check .
```

`pip install -e ".[dev]"` ist nur noetig, wenn du bewusst in einer eigenen
Umgebung arbeiten willst (Optionale Extras: `pytest`, `pytest-cov`, `ruff`).
Der Test-Suite ist es egal, solange `rich`, `PyYAML`, `pytest` und `pytest-cov`
installiert sind.

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
