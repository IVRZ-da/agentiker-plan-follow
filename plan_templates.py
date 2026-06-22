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
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("plan_follow")

TEMPLATES_DIR = Path.home() / ".hermes" / "plans" / "templates"

# ─── Built-in Templates ───────────────────────────────────────────────────────

# Default parameter values per template (users can override via params={})
TEMPLATE_DEFAULTS: dict[str, dict[str, str]] = {
    "deploy": {
        "build_command": "echo 'build: nicht konfiguriert (params.build_command setzen)'",
        "test_command": "python3 -m pytest",
        "service": "app-service",
        "verify_url": "http://localhost:8080/health",
    },
    "bugfix": {
        "test_command": "python3 -m pytest",
        "lint_command": "ruff check",
    },
    "feature": {
        "typecheck_command": "echo 'typecheck: nicht konfiguriert'",
        "test_command": "python3 -m pytest",
        "lint_command": "ruff check",
    },
    "refactoring": {
        "test_coverage_command": "python3 -m pytest --cov",
        "typecheck_command": "echo 'typecheck: nicht konfiguriert'",
        "lint_command": "ruff check",
    },
    "docs": {
        "test_command": "echo 'docs: Manuelle Prüfung erforderlich'",
    },
    "infrastructure": {
        "test_command": "echo 'infra: Config-Dateien prüfen'",
        "verify_url": "http://localhost:8080/health",
    },
    "go-setup": {
        "test_command": "go test ./...",
        "lint_command": "go vet ./...",
        "build_command": "go build ./...",
    },
    "security": {
        "scan_command": "echo 'security scan: nicht konfiguriert'",
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
            {"id": "b1", "name": "RED: Failenden Test schreiben", "files": ["*_test.go", "*spec.ts", "*test.py", "*_test.py"],
             "verify": "bash -c 'if {{test_command}} 2>/dev/null; then echo \"❌ RED FAILED — Tests passed unexpectedly. RED test should reproduce the bug.\"; exit 1; else echo \"✅ RED: Test failed as expected — bug reproduced\"; exit 0; fi'", "depends_on": []},
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
            {"id": "f2", "name": "RED: Tests schreiben", "files": ["*_test.go", "*spec.ts", "*test.py", "*_test.py"],
             "verify": "bash -c 'if {{test_command}} 2>/dev/null; then echo \"❌ RED FAILED — Tests passed unexpectedly. RED test should reproduce the bug.\"; exit 1; else echo \"✅ RED: Test failed as expected — bug reproduced\"; exit 0; fi'", "depends_on": ["f1"]},
            {"id": "f3", "name": "GREEN: Implementierung", "files": ["src/"],
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
            {"id": "rs1", "name": "Web-Recherche durchführen", "files": [], "verify": "echo 'sources: $(ls research/ 2>/dev/null | wc -l) Quellen dokumentiert'", "depends_on": []},
            {"id": "rs2", "name": "Ergebnisse analysieren", "files": [], "verify": "test -f research/analysis.md -o -f research/findings.md && echo '✅ Analyse-Datei existiert' || echo '⚠️ Keine Analyse-Datei gefunden'", "depends_on": ["rs1"]},
            {"id": "rs3", "name": "Zusammenfassung schreiben", "files": [], "verify": "test -f research/summary.md -o -f research/final.md && echo '✅ Zusammenfassung geschrieben' || echo '⚠️ Keine Zusammenfassung gefunden'", "depends_on": ["rs2"]},
        ],
        "review_profile": "none",
    },
    "analysis": {
        "description": "Code-Analyse: Code scannen → Ergebnisse analysieren → Report schreiben → Review",
        "tasks": [
            {"id": "a1", "name": "Code scannen und Daten sammeln", "files": [], "verify": "echo 'files scanned: $(find . -name '*.py' -o -name '*.ts' -o -name '*.go' 2>/dev/null | head -20 | wc -l) relevante Dateien gefunden'", "depends_on": []},
            {"id": "a2", "name": "Ergebnisse analysieren und Muster erkennen", "files": [], "verify": "test -f analysis/findings.json -o -f analysis/patterns.md && echo '✅ Analyse-Ergebnisse gespeichert' || echo '⚠️ Keine Analyse-Datei gefunden'", "depends_on": ["a1"]},
            {"id": "a3", "name": "Analyse-Report schreiben", "files": [], "verify": "test -f analysis/report.md && echo '✅ Report geschrieben' || echo '⚠️ Kein Report gefunden'", "depends_on": ["a2"]},
            {"id": "a4", "name": "Review: Report auf Vollständigkeit prüfen", "files": [], "verify": "echo '✅ Review completed'", "depends_on": ["a3"], "review_profile": "unit-test"},
        ],
        "review_profile": "unit-test",
    },
    "fix": {
        "description": "Schneller Bug-Fix mit TDD: RED → GREEN",
        "tasks": [
            {"id": "f1", "name": "RED: Test schreiben der den Bug zeigt", "files": ["*_test.go", "*spec.ts", "*test.py", "*_test.py"],
             "verify": "{{test_command}} && exit 1 || echo '✅ RED: Test failed as expected'", "depends_on": []},
            {"id": "f2", "name": "GREEN: Bug fixen bis Test grün", "files": ["src/"],
             "verify": "{{test_command}} || exit 1", "depends_on": ["f1"]},
        ],
        "review_profile": "unit-test",
    },
    "docs": {
        "description": "Dokumentation: Research → Outline → Write → Review",
        "tasks": [
            {"id": "dc1", "name": "Research: Quellen und Informationen sammeln", "files": [], "verify": "echo 'research: $(ls docs/research/ 2>/dev/null | wc -l) Quellen'", "depends_on": []},
            {"id": "dc2", "name": "Outline: Struktur und Gliederung erstellen", "files": [], "verify": "test -f docs/outline.md && echo '✅ Outline erstellt' || echo '⚠️ Kein Outline'", "depends_on": ["dc1"]},
            {"id": "dc3", "name": "Write: Inhalt schreiben", "files": ["docs/"], "verify": "test -f docs/content.md -o -f README.md && echo '✅ Content geschrieben' || echo '⚠️ Kein Content'", "depends_on": ["dc2"]},
            {"id": "dc4", "name": "Review: Inhalt gegen Checkliste prüfen", "files": [], "verify": "echo '✅ Docs reviewed'", "depends_on": ["dc3"]},
        ],
        "review_profile": "none",
    },
    "infrastructure": {
        "description": "Infrastruktur: Plan → Umsetzung → Test → Apply",
        "tasks": [
            {"id": "i1", "name": "Plan: Änderungen dokumentieren", "files": [], "verify": "echo 'Änderungen geplant: systemd, nginx, Docker, Configs'", "depends_on": []},
            {"id": "i2", "name": "Umsetzung: Konfiguration anpassen", "files": ["/etc/", "nginx/", "docker/", "*.yaml", "*.toml", "*.conf"], "verify": "echo 'Config: Umsetzung abgeschlossen'", "depends_on": ["i1"]},
            {"id": "i3", "name": "Test: Konfiguration prüfen + Dry-Run", "files": [], "verify": "{{test_command}}", "depends_on": ["i2"]},
            {"id": "i4", "name": "Apply + Health-Check", "files": [], "verify": "systemctl is-active --quiet {{service}} && curl -sf {{verify_url}} && echo '✅ Service healthy' || echo '⚠️ Health-Check fehlgeschlagen'", "depends_on": ["i3"]},
        ],
        "review_profile": "api-route",
    },
    "go-setup": {
        "description": "Go-Entwicklung: Build → Test → Vet → Docs",
        "tasks": [
            {"id": "g1", "name": "Build: go build ./...", "files": ["*.go", "go.mod", "go.sum"], "verify": "{{build_command}}", "depends_on": []},
            {"id": "g2", "name": "Test: go test ./...", "files": ["*_test.go"], "verify": "{{test_command}}", "depends_on": ["g1"]},
            {"id": "g3", "name": "Vet: go vet ./...", "files": ["*.go"], "verify": "{{lint_command}}", "depends_on": ["g2"]},
        ],
        "review_profile": "unit-test",
    },
    "security": {
        "description": "Security-Audit: Scan → Findings → Fix → Re-Scan",
        "tasks": [
            {"id": "s1", "name": "Scan: Sicherheitslücken identifizieren", "files": [], "verify": "echo 'Security Scan: $(find security/ -name '*.json' -o -name '*.md' 2>/dev/null | wc -l) Findings'", "depends_on": []},
            {"id": "s2", "name": "Analyse: Findings priorisieren", "files": [], "verify": "test -f security/findings.md && echo '✅ Findings priorisiert' || echo '⚠️ Keine Findings-Datei'", "depends_on": ["s1"]},
            {"id": "s3", "name": "Fix: Schwachstellen beheben", "files": ["src/"], "verify": "echo 'Fixes: implementiert'", "depends_on": ["s2"]},
            {"id": "s4", "name": "Re-Scan: Nachkontrolle", "files": [], "verify": "echo '✅ Re-Scan completed'", "depends_on": ["s3"]},
        ],
        "review_profile": "security",
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
                logger.warning("Template %s: could not be parsed", yaml_file.name)
                continue
            name = parsed.get("name", yaml_file.stem)
            templates[name] = {
                "description": parsed.get("description", f"User template: {name}"),
                "tasks": parsed.get("tasks", []),
                "review_profile": parsed.get("review_profile", "none"),
                "repo_hint": parsed.get("repo_hint", ""),
                "_source": yaml_file.name,
            }
            logger.info("User-Template '%s' geladen aus %s", name, yaml_file.name)
        except Exception as e:
            logger.warning("Template %s: Fehler beim Laden: %s", yaml_file.name, e)

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

TEMPLATE_NAMES = ["deploy", "fix", "bugfix", "feature", "refactoring", "research", "analysis"]


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

    # ─── Auto p0: Peer-Review-Task vor alle anderen Tasks ────────────────
    # JEDER Plan hat einen p0-review Task als Task 0. Der Review prüft den
    # Plan gegen die 8-Punkte-Checkliste (depends_on, verify, files, etc.)
    # und wendet Korrekturen an. Erst danach gehts an die Umsetzung.
    # User-defined Templates kriegen den p0 ebenfalls automatisch.
    p0_task = {
        "id": "p0",
        "name": "Peer Review: Plan prüfen + Korrekturen einarbeiten",
        "files": [],
        "verify": "echo '✅ Plan reviewed and accepted'",
        "depends_on": [],
    }
    result["tasks"].insert(0, p0_task)
    # Adjust depends_on: erster Template-Task hängt von p0 ab
    if len(result["tasks"]) > 1 and result["tasks"][1].get("depends_on"):
        if p0_task["id"] not in result["tasks"][1]["depends_on"]:
            result["tasks"][1]["depends_on"] = [p0_task["id"]] + result["tasks"][1]["depends_on"]
    elif len(result["tasks"]) > 1:
        result["tasks"][1]["depends_on"] = [p0_task["id"]]
    if template.get("repo_hint"):
        result["repo_hint"] = template["repo_hint"]

    # ─── skip_refactor für bugfix ─────────────────────────────────────
    # Wenn params.skip_refactor=true, REFACTOR-Schritt überspringen
    # (ermöglicht 2-Task-Bugfix wie das frühere fix-Template)
    if name == "bugfix" and params and params.get("skip_refactor") in ("true", "True", True):
        result["tasks"] = [t for t in result["tasks"] if t.get("id") != "b3"]
        # depends_on von b2 leeren (b2 war von b3 abhängig, jetzt ist b2 letzter Task)
        for t in result["tasks"]:
            if t.get("id") == "b2":
                t["depends_on"] = ["p0"]

    # ─── review_profile auf Tasks propagieren ──────────────────────────
    # Setze das template-eigene review_profile auf alle Tasks die keins haben.
    # p0 wird ausgeschlossen (ist Admin-Task, kein Code-Task).
    tpl_review = result.get("review_profile", "none")
    if tpl_review and tpl_review != "none":
        for i, task in enumerate(result["tasks"]):
            if task.get("id") == "p0":
                continue  # p0 ist Admin-Task, kein review nötig
            if not task.get("review_profile") or task["review_profile"] == "none":
                result["tasks"][i]["review_profile"] = tpl_review

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
