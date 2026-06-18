---
name: plan-follow
description: "Plan enforcement tools: plan_create/current/complete/verify/status/update + pre_llm_call hook for task tracking. Bietet SOUL.md + automatische Task-Injektion + Drift-Detection."
version: 1.0.0
author: Hermes Agent
tags: [planning, enforcement, tasks, workflow, execution]
related_skills: [tool-choice-priorities, writing-plans]
---

# Plan-Follow Skill

**Plugin-provided skill (plan_follow plugin).** Nutze `plan_create` → `plan_current` → `plan_complete` für strukturierte Task-Abarbeitung.

## Tools

| Tool | Funktion |
|------|----------|
| `plan_create(goal, tasks, repo)` | Plan anlegen (Tasks mit Files + Dependencies) |
| `plan_current()` | Zeigt NUR den aktuellen Task |
| `plan_complete(task_id)` | Task abschliessen + verifizieren + weiter |
| `plan_verify()` | Drift-Check: ungeplante Änderungen? |
| `plan_status()` | Alle Tasks als Übersicht |
| `plan_update(task_id, changes)` | Task-Eigenschaften ändern (lebendes Dokument) |

## Verhalten

- Der `pre_llm_call` Hook injiziert den aktuellen Task in JEDE Prompt
- Health-Check prüft alle 4 Kernsysteme vor jedem Turn
- Drift-Detection warnt bei ungeplanten Änderungen
- Plans überleben Session-Crash via Honcho

## Hierarchie

agentiker_code_intel (code_* Tools) FIRST → Serena SECOND → Firecrawl → Postgres → Built-ins
