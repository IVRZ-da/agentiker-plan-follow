"""Tool schemas for plan_follow plugin — ausgelagert aus __init__.py."""

from __future__ import annotations

from .. import VALID_REVIEW_PROFILES, VALID_REVIEW_PROFILES_WITH_AUTO

PER_TOOL_SCHEMAS = {
    "plan_create": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Das Ziel des Plans"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "files": {"type": "array", "items": {"type": "string"}},
                        "verify": {"type": "string"},
                        "review_profile": {
                            "type": "string",
                            "enum": VALID_REVIEW_PROFILES,
                            "description": "Review-Profil (optional, default: none)",
                        },
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "name"],
                },
                "description": "Liste der Tasks. Nur nutzbar wenn template nicht gesetzt ist (alternative zu template). Jeder Task braucht id und name, optional files/verify/review_profile/depends_on.",
            },
            "plan_id": {"type": "string", "description": "Optionale eigene Plan-ID (sonst auto-generiert aus goal)"},
            "template": {
                "type": "string",
                "enum": ["deploy", "bugfix", "feature", "refactoring", "research", "analysis", "docs", "fix", "go-setup", "infrastructure", "security", "multi"],
                "description": "Template-Name (optional). Wenn gesetzt, werden Tasks automatisch aus der Vorlage generiert. Wenn nicht gesetzt, müssen tasks angegeben werden.\n  - multi: eigener Aufgabenkatalog via params.tasks. Bsp: params={'tasks': [{'id':'a','name':'...','files':[...],'verify':'...'}]}",
            },
            "repo": {"type": "string", "description": "Pfad zum Git-Repo (optional)"},
            "parallel_groups": {
                "type": "object",
                "description": "Optionale parallele Gruppen. Jeder Key ist eine Gruppen-ID, Value ist {\"tasks\": [task_id, ...]}. Gruppen werden sequentiell verarbeitet — alle Tasks einer Gruppe laufen parallel.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "tasks": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["tasks"],
                },
            },
            "params": {
                "type": "object",
                "description": "Optionale Parameter fuer Template-Placeholders {{var}}. Fuer multi-Template: params={'tasks': [{'id':'a', 'name':'...', ...}]}",
            },
        },
        "required": ["goal"],
    },
    "plan_current": {
        "type": "object",
        "properties": {},
    },
    "plan_complete": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID des abzuschliessenden Tasks"},
            "skip_review": {"type": "boolean", "description": "Review-Gate überspringen (default: false)"},
            "auto_verify": {"type": "boolean", "description": "verify-Command automatisch ausführen (default: false)"},
            "auto_commit": {"type": "boolean", "description": "Git-Commit nach Abschluss (default: false)"},
        },
        "required": ["task_id"],
    },
    "plan_verify": {
        "type": "object",
        "properties": {},
    },
    "plan_status": {
        "type": "object",
        "properties": {},
    },
    "plan_todo": {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Task items to write. Omit to read current list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Task identifier"},
                        "content": {"type": "string", "description": "Task description"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "New status (completed → plan_complete)",
                        },
                    },
                },
            },
            "merge": {
                "type": "boolean",
                "description": "true: update existing items. false: read mode (default).",
                "default": False,
            },
        },
    },
    "plan_update": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID des zu aktualisierenden Tasks"},
            "changes": {
                "type": "object",
                "description": "Zu ändernde Felder (files, verify, depends_on, name, review_profile)",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}},
                    "verify": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "name": {"type": "string"},
                    "review_profile": {
                        "type": "string",
                        "enum": VALID_REVIEW_PROFILES,
                    },
                },
                "additionalProperties": False,
            },
        },
        "required": ["task_id", "changes"],
    },
    "plan_auto_review": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID zum Reviewen"},
            "profile": {
                "type": "string",
                "enum": VALID_REVIEW_PROFILES_WITH_AUTO,
                "description": "Review-Profil (auto = aus Task, sonst override)",
                "default": "auto",
            },
            "depth": {
                "type": "string",
                "enum": ["quick", "normal", "deep"],
                "description": "Review-Tiefe (default: normal)",
                "default": "normal",
            },
        },
        "required": ["task_id"],
    },
    "plan_review": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID zum Reviewen"},
            "profile": {
                "type": "string",
                "enum": VALID_REVIEW_PROFILES_WITH_AUTO,
                "description": "Review-Profil (auto = aus Task, sonst override)",
                "default": "auto",
            },
            "depth": {
                "type": "string",
                "enum": ["quick", "normal", "deep"],
                "description": "Review-Tiefe (default: normal)",
                "default": "normal",
            },
        },
        "required": ["task_id"],
    },
    "plan_review_profiles": {
        "type": "object",
        "properties": {},
    },
    "plan_review_save_result": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID"},
            "status": {"type": "string", "description": "'passed' or 'failed'", "default": "passed"},
            "issues": {"type": "array", "items": {"type": "object"}, "description": "List of issue dicts"},
            "summary": {"type": "string", "description": "Review summary text"},
        },
        "required": ["task_id"],
    },
    "plan_template": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "list, detail, save, or delete"},
            "name": {"type": "string", "description": "Template name (required for detail/save/delete)"},
            "tasks": {"type": "array", "description": "Task dicts for save action"},
            "description": {"type": "string", "description": "Template description"},
            "review_profile": {"type": "string", "description": "Review profile for template"},
        },
        "required": ["action"],
    },
    "plan_suggest": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "The goal to generate suggestions for"},
            "project_root": {"type": "string", "description": "Optional project root path"},
        },
        "required": ["goal"],
    },
    "plan_time": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "start, stop, status, or history"},
            "task_id": {"type": "string", "description": "Task ID"},
            "plan_id": {"type": "string", "description": "Plan ID"},
        },
        "required": ["action"],
    },
    "plan_simulate": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Plan ID (optional — defaults to active plan)"},
        },
    },
    "plan_sync": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "github, export, or import"},
            "plan_id": {"type": "string", "description": "Plan ID"},
            "repo": {"type": "string", "description": "GitHub repo (owner/repo)"},
            "markdown": {"type": "string", "description": "Markdown content for import"},
        },
        "required": ["action"],
    },
    "plan_decompose": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "expand, collapse, status, create, or delegate"},
            "task_id": {"type": "string", "description": "Task ID"},
            "name": {"type": "string", "description": "Compound task name for create"},
            "subtasks": {"type": "array", "description": "Sub-task definitions for create"},
        },
        "required": ["action"],
    },
    "plan_list": {
        "type": "object",
        "properties": {},
    },
    "plan_abort": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID to abort (optional — aborts whole plan if omitted)"},
        },
    },
    "plan_delete": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des zu löschenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_select": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des zu aktivierenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_validate": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Plan-ID zum Validieren (optional — ohne wird der aktive Plan validiert)"},
        },
    },
    "plan_duedate": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task-ID (optional — ohne wird der aktuelle Task verwendet)"},
            "due": {"type": "string", "description": "ISO-8601 Datum (z.B. '2026-06-25') zum Setzen. Ohne: View-Mode. Leerstring: Löschen."},
        },
    },
    "plan_archive": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des zu archivierenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_restore": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "ID des wiederherzustellenden Plans"},
        },
        "required": ["plan_id"],
    },
    "plan_roadmap": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "show", "to_plan", "set", "list", "create", "update", "edit-phase", "add-phase", "remove-phase", "delete"],
                "description": "Aktion: status, show, to_plan, set, list, create, update, edit-phase, add-phase, remove-phase, delete",
            },
            "cmd": {
                "type": "string",
                "enum": ["status", "show", "to_plan", "set", "list", "create", "update", "edit-phase", "add-phase", "remove-phase", "delete"],
                "description": "Alias für 'action' (deprecated, nutze action= für Konsistenz mit plan_lock/plan_notify)",
            },
            "name": {"type": "string", "description": "Roadmap-Name (ohne .yaml). Auto-select bei Weglassung."},
            "phase": {"type": "string", "description": "Phase-ID für show/to_plan/set/edit-phase/remove-phase"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "blocked"],
                "description": "Neuer Status für 'set'/'edit-phase'",
            },
            "goal": {"type": "string", "description": "Roadmap-Ziel für 'create'/'update'"},
            "phases": {
                "type": "array",
                "description": "Phasen-Liste für 'create'",
                "items": {"type": "object"},
            },
            "phase_data": {
                "type": "object",
                "description": "Phase als JSON-Objekt für 'add-phase'",
            },
            "priority": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Neue Priorität für 'edit-phase'",
            },
            "effort": {"type": "string", "description": "Neuer Aufwand für 'edit-phase'"},
            "impact": {"type": "string", "description": "Neuer Impact für 'edit-phase'"},
            "tasks": {
                "type": "array",
                "description": "Tasks-Liste für 'edit-phase'",
                "items": {"type": "string"},
            },
        },
        "required": [],
    },
    "plan_session": {
        "type": "object",
        "properties": {
            "include_history": {
                "type": "boolean",
                "description": "Git-basierte Plan-History anzeigen (default: false)",
                "default": False,
            },
        },
    },
    "plan_lock": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["lock", "unlock", "status"],
                "description": "Aktion: lock (sperren), unlock (freigeben), status (prüfen)",
            },
            "path": {"type": "string", "description": "Datei- oder Verzeichnispfad"},
            "session_id": {"type": "string", "description": "Session-ID (optional, auto-detect)"},
        },
        "required": ["action", "path"],
    },
    "plan_notify": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "check"],
                "description": "Aktion: send (Nachricht senden), check (eigene Nachrichten prüfen)",
            },
            "to": {"type": "string", "description": "Ziel-Session-ID (erforderlich für send)"},
            "message": {"type": "string", "description": "Nachrichtentext (erforderlich für send)"},
            "kind": {
                "type": "string",
                "enum": ["info", "warning", "alert"],
                "description": "Nachrichtentyp (default: info)",
                "default": "info",
            },
            "session_id": {"type": "string", "description": "Session-ID (optional)"},
        },
        "required": ["action"],
    },
    "plan_history": {
        "type": "object",
        "properties": {
            "plan_id": {"type": "string", "description": "Plan-ID (optional — default: aktueller Plan)"},
            "lines": {"type": "integer", "description": "Anzahl Log-Einträge (default: 10)", "default": 10},
        },
    },
    "plan_git_init": {
        "type": "object",
        "properties": {
            "commit_message": {"type": "string", "description": "Initiale Commit-Nachricht (optional)"},
        },
    },
    "plan_git_push": {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote-Name (default: origin)"},
            "branch": {"type": "string", "description": "Branch zum Pushen (default: aktueller Branch)"},
        },
    },
    "plan_git_status": {
        "type": "object",
        "properties": {},
    },
    "plan_git_sync": {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote-Name (default: origin)"},
            "branch": {"type": "string", "description": "Branch (default: aktueller)"},
            "push": {"type": "boolean", "description": "Nach Commit pushen (default: true)"},
        },
    },
    "plan_git_stash": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["push", "pop", "list"],
                "description": "Aktion: push (stashen), pop (wiederherstellen), list (anzeigen)",
            },
            "message": {"type": "string", "description": "Stash-Beschreibung (push only)"},
        },
        "required": ["action"],
    },
    "plan_git_branch": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["current", "list", "create", "switch", "delete"],
                "description": "Aktion: current, list, create, switch, delete",
            },
            "name": {"type": "string", "description": "Branch-Name (create/switch/delete)"},
            "start_point": {"type": "string", "description": "Start-Punkt (create only)"},
        },
        "required": ["action"],
    },
    "plan_git_tag": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "delete"],
                "description": "Aktion: create, list, delete",
            },
            "tag_name": {"type": "string", "description": "Tag-Name (create/delete)"},
            "message": {"type": "string", "description": "Tag-Beschreibung (create only, annotierter Tag)"},
        },
        "required": ["action"],
    },
    "plan_pr_create": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR-Titel (erforderlich)"},
            "body": {"type": "string", "description": "PR-Beschreibung"},
            "head": {"type": "string", "description": "Quell-Branch (default: aktueller Branch)"},
            "base": {"type": "string", "description": "Ziel-Branch (default: main)"},
            "owner": {"type": "string", "description": "Repo-Owner (default: aus Git-Remote)"},
            "repo_name": {"type": "string", "description": "Repo-Name (default: aus Git-Remote)"},
        },
        "required": ["title"],
    },
    "plan_coord_cleanup": {
        "type": "object",
        "properties": {
            "session_max_age": {"type": "integer", "description": "Session-Max-Alter in Minuten (default: 60)"},
            "lock_max_age": {"type": "integer", "description": "Lock-Max-Alter in Minuten (default: 120)"},
            "dry_run": {"type": "boolean", "description": "Nur Report, keine Löschung (default: false)"},
        },
    },
}
