"""plan_templates.py — Reusable plan templates for plan_follow plugin.

Each template defines a sequence of tasks with names, verify commands,
files patterns, and review profiles. Templates can be:

1. Built-in (Python dicts below)
2. User-defined (YAML files in ~/.hermes/plans/templates/*.yaml)

Tasks support {{param}} placeholders for parameterization:
  plan_create(template="deploy", params={"env": "staging", "url": "..."})
"""

from __future__ import annotations

import copy
import logging
import yaml
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("plan_follow")

TEMPLATES_DIR = Path.home() / ".hermes" / "plans" / "templates"

# ─── Built-in Templates ───────────────────────────────────────────────────────

# Default parameter values per template (users can override via params={})
TEMPLATE_DEFAULTS: dict[str, dict[str, str]] = {
    "deploy": {
        "build_command": "npx medusa build",
        "test_command": "npm test",
        "service": "medusa-staging",
        "verify_url": "http://localhost:9000/health",
    },
    "bugfix": {
        "test_command": "npm test",
        "lint_command": "npm run lint",
    },
    "feature": {
        "typecheck_command": "tsc --noEmit",
        "test_command": "npm test",
        "lint_command": "npm run lint",
    },
    "refactoring": {
        "test_coverage_command": "npm test -- --coverage",
        "typecheck_command": "tsc --noEmit",
        "lint_command": "npm run lint",
    },
}

BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "deploy": {
        "description": "Deployment: Build → Test → Deploy → Verify",
        "tasks": [
            {"id": "d1", "name": "Build check", "files": [], "verify": "{{build_command}}", "depends_on": []},
            {"id": "d2", "name": "Tests ausführen", "files": [], "verify": "{{test_command}}", "depends_on": ["d1"]},
            {"id": "d3", "name": "Deploy to {{env}}", "files": [],
             "verify": "systemctl --user restart {{service}}", "depends_on": ["d2"]},
            {"id": "d4", "name": "Health-Check verify", "files": [],
             "verify": "curl -f {{verify_url}}", "depends_on": ["d3"]},
        ],
        "repo_hint": "BENÖTIGT: repo-Parameter mit Git-Pfad",
        "review_profile": "api-route",
    },
    "bugfix": {
        "description": "Bug-Fix mit TDD: RED → GREEN → REFACTOR",
        "tasks": [
            {"id": "b1", "name": "RED: Failenden Test schreiben", "files": ["*spec.ts"],
             "verify": "{{test_command}} -- --grep 'new test'", "depends_on": []},
            {"id": "b2", "name": "GREEN: Fix implementieren", "files": ["src/"],
             "verify": "{{test_command}}", "depends_on": ["b1"]},
            {"id": "b3", "name": "REFACTOR: Code aufräumen", "files": ["src/"],
             "verify": "{{lint_command}}", "depends_on": ["b2"]},
        ],
        "review_profile": "unit-test",
    },
    "feature": {
        "description": "Neues Feature: Spec → Implementierung → Tests → Docs",
        "tasks": [
            {"id": "f1", "name": "Spec schreiben / Types definieren", "files": ["src/"],
             "verify": "{{typecheck_command}}", "depends_on": []},
            {"id": "f2", "name": "Implementierung", "files": ["src/"],
             "verify": "{{typecheck_command}}", "depends_on": ["f1"]},
            {"id": "f3", "name": "Tests schreiben", "files": ["*spec.ts"],
             "verify": "{{test_command}}", "depends_on": ["f2"]},
            {"id": "f4", "name": "Dokumentation", "files": ["README.md", "docs/"],
             "verify": "{{lint_command}}", "depends_on": ["f3"]},
        ],
        "review_profile": "unit-test",
    },
    "refactoring": {
        "description": "Refactoring: Coverage → Refactor → Verify → Docs",
        "tasks": [
            {"id": "r1", "name": "Coverage-Check vor Refactoring", "files": [],
             "verify": "{{test_coverage_command}}", "depends_on": []},
            {"id": "r2", "name": "Refactoring durchführen", "files": ["src/"],
             "verify": "{{typecheck_command}}", "depends_on": ["r1"]},
            {"id": "r3", "name": "Tests + Coverage nach Refactoring", "files": ["*spec.ts"],
             "verify": "{{test_coverage_command}}", "depends_on": ["r2"]},
            {"id": "r4", "name": "Dokumentation aktualisieren", "files": ["README.md", "docs/"],
             "verify": "{{lint_command}}", "depends_on": ["r3"]},
        ],
        "review_profile": "full",
    },
    "research": {
        "description": "Recherche: Web-Suche → Analyse → Zusammenfassung",
        "tasks": [
            {"id": "rs1", "name": "Web-Recherche durchführen", "files": [], "verify": "", "depends_on": []},
            {"id": "rs2", "name": "Ergebnisse analysieren", "files": [], "verify": "", "depends_on": ["rs1"]},
            {"id": "rs3", "name": "Zusammenfassung schreiben", "files": [], "verify": "", "depends_on": ["rs2"]},
        ],
        "review_profile": "none",
    },
    "analysis": {
        "description": "Code-Analyse: Code scannen → Ergebnisse analysieren → Report schreiben → Review",
        "tasks": [
            {"id": "a1", "name": "Code scannen und Daten sammeln", "files": [], "verify": "", "depends_on": []},
            {"id": "a2", "name": "Ergebnisse analysieren und Muster erkennen", "files": [], "verify": "", "depends_on": ["a1"]},
            {"id": "a3", "name": "Analyse-Report schreiben", "files": [], "verify": "", "depends_on": ["a2"]},
            {"id": "a4", "name": "Review: Report auf Vollständigkeit prüfen", "files": [], "verify": "", "depends_on": ["a3"], "review_profile": "unit-test"},
        ],
        "review_profile": "unit-test",
    },
}


# ─── User Templates (YAML) ────────────────────────────────────────────────────

def _load_user_templates() -> dict[str, dict[str, Any]]:
    """Load user-defined templates from TEMPLATES_DIR/*.yaml using PyYAML."""
    templates = {}
    if not TEMPLATES_DIR.exists():
        return templates

    for yaml_file in sorted(TEMPLATES_DIR.glob("*.yaml")):
        try:
            content = yaml_file.read_text(encoding="utf-8")
            parsed = yaml.safe_load(content)
            if not parsed or not isinstance(parsed, dict):
                logger.warning(f"Template {yaml_file.name}: could not be parsed")
                continue
            name = parsed.get("name", yaml_file.stem)
            templates[name] = {
                "description": parsed.get("description", f"User template: {name}"),
                "tasks": parsed.get("tasks", []),
                "review_profile": parsed.get("review_profile", "none"),
                "repo_hint": parsed.get("repo_hint", ""),
                "_source": yaml_file.name,
            }
            logger.info(f"User-Template '{name}' geladen aus {yaml_file.name}")
        except Exception as e:
            logger.warning(f"Template {yaml_file.name}: Fehler beim Laden: {e}")

    return templates


def _parse_yaml_simple(content: str) -> Optional[dict]:
    """Parse YAML content via PyYAML.

    PyYAML is always available in Hermes plugins (standard dependency).
    This function exists for backward compatibility — delegates to yaml.safe_load.
    """
    import yaml
    return yaml.safe_load(content)


# ─── Template Merging ─────────────────────────────────────────────────────────

def _get_all_templates() -> dict[str, dict[str, Any]]:
    """Merge built-in and user-defined templates. User templates override built-ins."""
    templates = dict(BUILTIN_TEMPLATES)
    user_templates = _load_user_templates()
    for name, tpl in user_templates.items():
        templates[name] = tpl
    return templates


def get_template_names() -> list[str]:
    """Return all available template names (built-in + user)."""
    return sorted(_get_all_templates().keys())


# ─── Parameter Substitution ───────────────────────────────────────────────────

def _substitute_params(value: Any, params: dict[str, str]) -> Any:
    """Replace {{param}} placeholders in a value with params dict.

    Handles strings, lists (recursive), and nested dicts.
    Unknown placeholders are left as-is (silent skip).
    """
    if isinstance(value, str):
        for key, val in params.items():
            placeholder = "{{" + key + "}}"
            if placeholder in value:
                value = value.replace(placeholder, str(val))
        return value
    elif isinstance(value, list):
        return [_substitute_params(item, params) for item in value]
    elif isinstance(value, dict):
        return {k: _substitute_params(v, params) for k, v in value.items()}
    return value


# ─── Public API ───────────────────────────────────────────────────────────────

TEMPLATE_NAMES = ["deploy", "bugfix", "feature", "refactoring", "research", "analysis"]


def expand_template(name: str, goal: str = "", params: Optional[dict] = None) -> dict:
    """Expand a named template into a tasks list, with optional parameter substitution.

    Args:
        name: Template name (deploy, bugfix, feature, refactoring, research, analysis, or user-defined).
        goal: Optional plan goal.
        params: Optional dict of {{param}} → value substitutions for template placeholders.

    Returns:
        Dict with 'tasks' list and optionally 'review_profile'.
        Returns {'error': '...'} if template not found.
    """
    templates = _get_all_templates()
    template = templates.get(name)
    if not template:
        available = sorted(templates.keys())
        return {"error": f"Template '{name}' not found. Available: {', '.join(available) if available else '(keine)'}"}

    # Deep-copy and substitute params
    result = {
        "tasks": copy.deepcopy(template["tasks"]),
        "review_profile": template.get("review_profile", "none"),
        "description": template.get("description", ""),
    }
    if template.get("repo_hint"):
        result["repo_hint"] = template["repo_hint"]

    # Merge default params with user-provided params (user wins)
    merged_params = dict(TEMPLATE_DEFAULTS.get(name, {}))
    if params:
        merged_params.update(params)

    # Substitute {{param}} placeholders in task fields
    if merged_params:
        for i, task in enumerate(result["tasks"]):
            for field in ("id", "name", "verify", "files", "depends_on", "review_profile"):
                if field in task:
                    result["tasks"][i][field] = _substitute_params(task[field], merged_params)

    return result
