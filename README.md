# 📋 plan_follow — Hermes Plugin

> Structured plan creation, task enforcement, review gates, parallel groups, auto-verify, and session isolation for Hermes Agent.
> 38 tools — plan from spec to completion without leaving the conversation.

[![Version](https://img.shields.io/badge/version-1.5.2-blue.svg)]()
[![Tests](https://img.shields.io/badge/tests-1027-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen.svg)]()

---

## 📋 Table of Contents

- [✨ Why?](#-why)
- [🚀 Quick Start](#-quick-start)
- [🛠 Tools](#-tools)
- [📦 Installation](#-installation)
- [🏗 Architecture](#-architecture)
- [Features](#features)
- [🧪 Development](#-development)
- [📄 Version History](#-version-history)
- [🤝 Contributing](#-contributing)

---

## ✨ Why?

Hermes Agent runs as a conversation — powerful, but without structure, tasks drift. You start fixing bug A, discover bug B, refactor C along the way, and an hour later nothing is finished.

**plan_follow gives every task a container:**

- **Create** a plan from a template — `deploy`, `bugfix`, `feature`, `refactoring`, `research`, `analysis`, `docs`, and more
- **Enforce** task order with `depends_on` and parallel groups
- **Review** before completion — 6 review profiles (unit-test, security, full, etc.)
- **Auto-verify** — run tests/checks automatically on task completion
- **Drift detection** — catch unplanned changes between task scope and reality
- **Cross-session** — plans survive `/new`, lock files prevent parallel-session conflicts

The result: **structured, auditable progress** from plan creation to completion, with every step verified.

---

## 🚀 Quick Start

```python
# Einen Plan aus einem Template erstellen
plan_create(
    goal="Login-Validation fixen",
    template="bugfix",
    params={"files": ["lib/validation.ts"]}
)

# Aktuellen Task anzeigen
plan_current()

# Task abschliessen — auto-verify + auto-commit
plan_complete("p0", skip_review=True)
plan_complete("f1", auto_verify=True, auto_commit=True)

# Plan-Status und Verwaltung
plan_status()                        # Alle Tasks + Fortschritt
plan_list()                          # Alle Pläne
plan_validate()                      # Plan-Konsistenz prüfen
plan_archive("alter-plan")           # Archivieren
plan_restore("alter-plan")           # Wiederherstellen
```

---

## 🛠 Tools

<!-- AUTO-GENERATED -->
| Tool | Description |
|------|-------------|
| `plan_abort` | Task oder ganzen Plan abbrechen |
| `plan_archive` | Plan archivieren (soft-delete) |
| `plan_auto_review` | Automatischer Review mit Coverage + Prompt-Builder |
| `plan_complete` | Task abschliessen — optional mit Review-Gate, Verify, Commit |
| `plan_create` | Plan anlegen — Template-Pflicht, automatischer p0 Peer-Review-Task + TDD |
| `plan_current` | Zeigt den aktiven Task mit Details |
| `plan_decompose` | HTN-Zerlegung: komplexe Tasks in Teil-Tasks aufbrechen |
| `plan_delete` | Plan dauerhaft löschen |
| `plan_duedate` | Fälligkeit setzen/anzeigen — Banner bei 🟡 SOON / 🔴 OVERDUE |
| `plan_git_branch` | Branch current/list/create/switch/delete |
| `plan_git_init` | Git-Repo für PLANS_DIR initialisieren |
| `plan_git_push` | Commits zu Remote pushen |
| `plan_git_stash` | Stash push/pop/list |
| `plan_git_status` | Status: Branch, Dirty, Ahead/Behind |
| `plan_git_sync` | Pull → Add → Commit → Push |
| `plan_git_tag` | Tag create/list/delete |
| `plan_history` | Git-History eines Plans anzeigen |
| `plan_list` | Alle Pläne anzeigen (auch archivierte) |
| `plan_lock` | File-Lock-Management (acquire/release/list/check) |
| `plan_notify` | Notifications senden/empfangen |
| `plan_pr_create` | PR via Forgejo API erstellen |
| `plan_restore` | Archivierten Plan wiederherstellen |
| `plan_review` | Review für aktuellen Task starten |
| `plan_review_profiles` | Verfügbare Review-Profile anzeigen |
| `plan_review_save_result` | Review-Ergebnis persistieren |
| `plan_roadmap` | Roadmap YAML-Management mit 11 Subcommands |
| `plan_select` | Zwischen Plänen wechseln |
| `plan_session` |  |
| `plan_simulate` | What-If-Simulation für Plan-Verlauf |
| `plan_status` | Alle Tasks als Übersicht mit Fortschrittsbalken (███░░░) |
| `plan_suggest` | KI-Vorschlag für Plan-Struktur |
| `plan_sync` |  |
| `plan_template` | Template anzeigen oder parametrisieren |
| `plan_time` | Zeit-Schätzung und Tracking |
| `plan_todo` | Todo-Liste aus Plan-Tasks (ersetzt built-in `todo`) |
| `plan_update` | Task-Eigenschaften ändern |
| `plan_validate` | Plan-Struktur validieren (depends_on, Zyklen, orphan tasks, Branch-Naming) |
| `plan_verify` | Drift-Check — ungeplante Änderungen seit letztem Commit |
<!-- END AUTO-GENERATED -->

### Review Profiles (6)

| Profile | Description |
|---------|-------------|
| `none` (default) | Kein Review |
| `unit-test` | Tests + Coverage + Edge-Cases |
| `api-route` | Validierung + Error-Handling + Security |
| `ui-component` | A11y + SSR + State + Forms + Mobile |
| `security` | Secrets + Injection + XSS + Auth |
| `full` | Alle Checks kombiniert |

---

## 📦 Installation

Enable in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - plan_follow
```

Dependencies installieren:

```bash
# Ins Hermes-Venv installieren
~/.hermes/hermes-agent/venv/bin/pip install -e /home/jo/.hermes/plugins/plan_follow/

# Oder via Script
./scripts/install-deps.sh

# Mit Dashboard-Unterstützung:
pip install -e /home/jo/.hermes/plugins/plan_follow/[dashboard]
```

**Dependencies:** `rich>=13.0`, `PyYAML>=6.0`, `fastapi>=0.133.0` (optional für Dashboard)

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     plan_follow Plugin                       │
├──────────────────────┬──────────────────┬───────────────────┤
│   Plan Lifecycle     │  Auto-Review     │  Git Integration   │
│                      │  & Verify        │                    │
│  ┌───────────────┐   │ ┌─────────────┐  │ ┌──────────────┐  │
│  │ plan_create   │   │ │ plan_review │  │ │ plan_git_sync│  │
│  │ plan_complete │   │ │ plan_verify │  │ │ plan_git_push│  │
│  │ plan_abort    │   │ │ plan_auto_  │  │ │ plan_pr_     │  │
│  │ plan_select   │   │ │   review    │  │ │   create     │  │
│  └───────────────┘   │ └─────────────┘  │ └──────────────┘  │
├──────────────────────┴──────────────────┴───────────────────┤
│                    Shared Core                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ plan_core│ │ plan_    │ │ coord_   │ │ plan_roadmap  │  │
│  │ (Data)   │ │ templates│ │ state    │ │ (YAML-Phasen) │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    Hooks (2)                                 │
│  • pre_llm_call — Task-Banner in JEDEM Turn                │
│  • post_tool_call — Tool-Tracking + Lock-Check              │
└─────────────────────────────────────────────────────────────┘
```

### Key Behaviors

| Feature | Description |
|---------|-------------|
| **Template-Pflicht** | `plan_create()` erfordert zwingend ein Template — keine manuellen Tasks |
| **p0 Peer-Review** | Automatischer Peer-Review-Task vor allen Code-Tasks |
| **TDD in Code-Templates** | RED → GREEN (→ REFACTOR) — Tests vor Implementation |
| **Parallele Gruppen** | Tasks in einer Gruppe laufen parallel, Gruppen sequentiell |
| **Auto-Verify** | Optionales Ausführen des verify-Commands bei `plan_complete()` |
| **Auto-Commit** | Optionaler Git-Commit bei Task-Abschluss |
| **Drift-Erkennung** | Ungeplante Änderungen werden proaktiv via post_tool_call getrackt |
| **Cross-Session** | Locks verhindern parallele Bearbeitung, Pläne überleben `/new` |
| **TTL-Cache (60s)** | Health + Drift nicht auf jedem Turn — spart Tokens |
| **Coverage Gate** | Pre-Commit-Hook blockiert bei <90% Coverage |

---

## 🧪 Development

```bash
cd /home/jo/.hermes/plugins/plan_follow

# Tests ausführen
python3 -m pytest tests/ -q --tb=short

# Coverage messen
python3 -m pytest tests/ --cov=plan_follow --cov-config=.coveragerc

# Pre-Commit Hook aktivieren
git config core.hooksPath .githooks
```

Aktuell: **1027 Tests**, Coverage ≥90%

---

## 📄 Version History

- **1.5.2** (2026-06-23) — 7 Bugfixes, 12 Templates, 31 Tools, MCP-Server, Dashboard-Plugin
- **1.1.0** (2026-06-18) — plan_archive/restore, plan_validate, plan_duedate, deadline warnings
- **1.0.1** (2026-06-17) — Minor bugfixes, template parametrization
- **1.0.0** (2026-06-16) — Initial release with 12 tools, 2 hooks, 6 templates, 173 tests

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch
3. Add tests for your changes (Coverage ≥90%)
4. Run `python3 -m pytest tests/ -q` — alle Tests müssen grün sein
5. Open a PR

Siehe `CONTRIBUTING.md` und `BRANCHING.md` für Details.

## 📄 License

[MIT](LICENSE)
