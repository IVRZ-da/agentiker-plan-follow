"""plan_roadmap.py — YAML-based Roadmap management for plan_follow.

A roadmap is a high-level strategic overview with prioritized phases.
It complements plan_follow's execution plans: roadmap = strategy, plan = execution.

Each roadmap is stored as a .yaml file in ~/.hermes/roadmaps/.
A roadmap has:
  - name, goal, created (metadata)
  - phases (list of Phase objects with priority, effort, impact, status, depends_on)

Tools:
  plan_roadmap(cmd="status")           -> Show roadmap overview with all phases
  plan_roadmap(cmd="show", phase="")    -> Show detail of a single phase
  plan_roadmap(cmd="to_plan", phase="") -> Convert phase to plan_follow tasks
  plan_roadmap(cmd="set", phase="", status="") -> Update phase status
  plan_roadmap(cmd="list")              -> List all available roadmaps
  plan_roadmap(cmd="create", name="", phases=[], goal="") -> Create new roadmap
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .plan_core import ROADMAPS_DIR, _roadmap_path, _list_roadmaps, _load_roadmap, _save_roadmap

logger = logging.getLogger("plan_follow")

# ─── Constants ────────────────────────────────────────────────────────────────

VALID_PRIORITIES = ("high", "medium", "low")
VALID_STATUSES = ("pending", "in_progress", "completed", "blocked")
PRIORITY_ICONS = {"high": "🔴", "medium": "🟡", "low": "🟢"}
STATUS_ICONS = {"pending": "⏳", "in_progress": "🔄", "completed": "✅", "blocked": "🔒"}

# ─── Active Roadmap (in-memory, last referenced) ─────────────────────────────

_active_roadmap: Optional[dict] = None
_active_roadmap_name: Optional[str] = None


def reset_active_roadmap() -> None:
    """Clear the active roadmap from memory."""
    global _active_roadmap, _active_roadmap_name
    _active_roadmap = None
    _active_roadmap_name = None


def set_active_roadmap(name: str) -> bool:
    """Set a roadmap as active by name. Returns True on success."""
    global _active_roadmap, _active_roadmap_name
    data = _load_roadmap(name)
    if data is None:
        return False
    _active_roadmap = data
    _active_roadmap_name = name
    return True


def get_active_roadmap() -> tuple[Optional[str], Optional[dict]]:
    """Return (name, data) of the active roadmap."""
    return _active_roadmap_name, _active_roadmap


# ─── Validation ───────────────────────────────────────────────────────────────

def _validate_roadmap(data: dict) -> list[str]:
    """Validate a roadmap data structure. Returns list of error messages (empty = valid)."""
    errors = []
    if "name" not in data or not data["name"]:
        errors.append("roadmap.name is required")
    if "phases" not in data or not isinstance(data["phases"], list):
        errors.append("roadmap.phases is required (non-empty list)")
        return errors

    phase_ids = set()
    for i, phase in enumerate(data["phases"]):
        prefix = f"phases[{i}]"
        if "id" not in phase or not phase["id"]:
            errors.append(f"{prefix}.id is required")
        else:
            if phase["id"] in phase_ids:
                errors.append(f"{prefix}.id '{phase['id']}' is duplicate")
            phase_ids.add(phase["id"])

        if "name" not in phase or not phase["name"]:
            errors.append(f"{prefix}.name is required")

        priority = phase.get("priority", "medium")
        if priority not in VALID_PRIORITIES:
            errors.append(f"{prefix}.priority must be one of {VALID_PRIORITIES}, got '{priority}'")
            phase["priority"] = "medium"

        status = phase.get("status", "pending")
        if status not in VALID_STATUSES:
            errors.append(f"{prefix}.status must be one of {VALID_STATUSES}, got '{status}'")
            phase["status"] = "pending"

        for dep in phase.get("depends_on", []):
            if dep not in phase_ids and dep != phase.get("id"):
                errors.append(f"{prefix}.depends_on '{dep}' references unknown phase")

    return errors


# ─── Phase Helpers ────────────────────────────────────────────────────────────

def _get_phase(roadmap: dict, phase_id: str) -> Optional[dict]:
    """Find a phase by ID in a roadmap."""
    for p in roadmap.get("phases", []):
        if p.get("id") == phase_id:
            return p
    return None


def _update_phase_status(roadmap: dict, phase_id: str, new_status: str) -> tuple[bool, str]:
    """Update a phase's status with dependency validation."""
    phase = _get_phase(roadmap, phase_id)
    if phase is None:
        return False, f"Phase '{phase_id}' not found"

    if new_status not in VALID_STATUSES:
        return False, f"Invalid status '{new_status}'. Valid: {', '.join(VALID_STATUSES)}"

    if new_status == "in_progress":
        for dep_id in phase.get("depends_on", []):
            dep = _get_phase(roadmap, dep_id)
            if dep and dep.get("status") != "completed":
                return False, f"Phase '{phase_id}' depends on '{dep_id}' which is still '{dep.get('status', 'unknown')}'"

    old_status = phase.get("status", "pending")
    phase["status"] = new_status

    if new_status == "completed":
        for p in roadmap.get("phases", []):
            if p.get("status") == "blocked" and all(
                _get_phase(roadmap, d).get("status") == "completed"
                for d in p.get("depends_on", [])
            ):
                p["status"] = "pending"

    return True, f"Phase '{phase_id}' -> {new_status} (was {old_status})"


def _get_next_phases(roadmap: dict) -> list[dict]:
    """Get phases that are ready to work on (pending and not blocked by dependencies)."""
    ready = []
    for p in roadmap.get("phases", []):
        if p.get("status") != "pending":
            continue
        deps = p.get("depends_on", [])
        if not deps:
            ready.append(p)
        elif all(
            _get_phase(roadmap, d).get("status") == "completed" for d in deps
        ):
            ready.append(p)
    return ready


def _get_phase_progress(roadmap: dict) -> dict:
    """Return progress stats: total, completed, in_progress, pending, blocked."""
    phases = roadmap.get("phases", [])
    total = len(phases)
    counts = {"completed": 0, "in_progress": 0, "pending": 0, "blocked": 0}
    for p in phases:
        s = p.get("status", "pending")
        if s in counts:
            counts[s] += 1
    return {"total": total, **counts}


# ─── Formatting ───────────────────────────────────────────────────────────────

def _format_roadmap_overview(roadmap: dict, name: str) -> str:
    """Format a full roadmap overview as text."""
    lines = []
    progress = _get_phase_progress(roadmap)
    pct = int(progress["completed"] / max(progress["total"], 1) * 100)

    lines.append(f"Roadmap: {roadmap.get('name', name)}")
    lines.append(f"  Goal: {roadmap.get('goal', '-')}")
    lines.append(f"  Fortschritt: {progress['completed']}/{progress['total']} ({pct}%)")
    lines.append("")

    for p in roadmap.get("phases", []):
        prio = p.get("priority", "medium")
        icon = PRIORITY_ICONS.get(prio, "O")
        status_icon = STATUS_ICONS.get(p.get("status", "pending"), "?")
        deps = p.get("depends_on", [])
        dep_str = f" -> {', '.join(deps)}" if deps else ""
        lines.append(f"  {icon} {status_icon} {p.get('name', p.get('id', '?'))}{dep_str}")
        lines.append(f"      [{p.get('status', 'pending')}]  {p.get('effort', '?')}  - {p.get('impact', '')}")

    next_phases = _get_next_phases(roadmap)
    if next_phases:
        lines.append("")
        lines.append(f"  -> Naechste Phase(n): {', '.join(p.get('name', p.get('id', '?')) for p in next_phases)}")

    return "\n".join(lines)


def _format_phase_detail(phase: dict) -> str:
    """Format a single phase detail view."""
    lines = []
    prio = phase.get("priority", "medium")
    icon = PRIORITY_ICONS.get(prio, "O")
    status_icon = STATUS_ICONS.get(phase.get("status", "pending"), "?")

    lines.append(f"  {icon} {status_icon} {phase.get('name', '?')}")
    lines.append(f"     ID: {phase.get('id', '?')}")
    lines.append(f"     Status: {phase.get('status', 'pending')}")
    lines.append(f"     Prioritaet: {prio}")
    lines.append(f"     Aufwand: {phase.get('effort', '?')}")
    lines.append(f"     Impact: {phase.get('impact', '?')}")

    tasks = phase.get("tasks", [])
    if tasks:
        lines.append(f"     Tasks ({len(tasks)}):")
        for t in tasks:
            lines.append(f"       - {t}")

    deps = phase.get("depends_on", [])
    if deps:
        lines.append(f"     Abhaengigkeiten: {', '.join(deps)}")

    return "\n".join(lines)


def _format_roadmap_list(roadmaps: list[dict]) -> str:
    """Format list of available roadmaps."""
    if not roadmaps:
        return "Keine Roadmaps gefunden. Lege eine unter ~/.hermes/roadmaps/ an."
    lines = ["Verfuegbare Roadmaps:"]
    for r in roadmaps:
        lines.append(f"  - {r['name']}  ({r['path']})")
    return "\n".join(lines)


# ─── Phase -> Plan Conversion ──────────────────────────────────────────────────

def _phase_to_plan_tasks(phase: dict) -> list[dict]:
    """Convert a roadmap phase into plan_follow compatible tasks."""
    tasks = phase.get("tasks", [])
    if not tasks:
        return [{
            "id": phase.get("id", "phase"),
            "name": phase.get("name", "Phase umsetzen"),
            "files": [],
            "verify": "",
            "depends_on": [],
        }]

    plan_tasks = []
    prev_id = None
    for idx, t in enumerate(tasks):
        task_id = f"{phase.get('id', 'phase')}-{idx + 1}"
        task = {
            "id": task_id,
            "name": t if isinstance(t, str) else t.get("name", str(t)),
            "files": [],
            "verify": "",
            "depends_on": [prev_id] if prev_id else [],
        }
        plan_tasks.append(task)
        prev_id = task_id

    return plan_tasks


# ─── Main Tool Handler ────────────────────────────────────────────────────────

def plan_roadmap_handler(args: dict, **kwargs: Any) -> str:
    """Handle plan_roadmap tool calls.
    
    Accepts both ``cmd`` (legacy) and ``action`` (consistent with plan_lock/plan_notify).
    If neither is specified, defaults to "status".
    """
    cmd = args.get("cmd") or args.get("action") or "status"

    # Commands that work without an active roadmap
    if cmd == "list":
        return _format_roadmap_list(_list_roadmaps())

    if cmd == "create":
        name = args.get("name", "")
        goal = args.get("goal", "")
        phases = args.get("phases", [])
        if not name or not phases:
            return "Bitte name= und phases= (Liste) angeben."
        data = {
            "name": name,
            "goal": goal,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "phases": phases,
        }
        errors = _validate_roadmap(data)
        if errors:
            return "Fehler:\n" + "\n".join(f"  - {e}" for e in errors)
        if _save_roadmap(name, data):
            set_active_roadmap(name)
            return f"Roadmap '{name}' erstellt mit {len(phases)} Phasen."
        return f"Konnte Roadmap '{name}' nicht speichern."

    # Remaining commands need an active roadmap
    name = args.get("name", "")
    if name:
        if not set_active_roadmap(name):
            avail = [r["name"] for r in _list_roadmaps()]
            return f"Roadmap '{name}' nicht gefunden. Verfuegbar: {avail}"
    elif _active_roadmap_name is None:
        roadmaps = _list_roadmaps()
        if not roadmaps:
            return "Keine Roadmaps verfuegbar. Lege eine unter ~/.hermes/roadmaps/ an."
        if not set_active_roadmap(roadmaps[0]["name"]):
            return f"Konnte Roadmap '{roadmaps[0]['name']}' nicht laden"

    rname, rdata = _active_roadmap_name, _active_roadmap
    if rdata is None:
        return "Keine aktive Roadmap."

    if cmd == "status":
        return _format_roadmap_overview(rdata, rname or "")

    elif cmd == "show":
        phase_id = args.get("phase", "")
        if not phase_id:
            available = ", ".join(p.get("id", "?") for p in rdata.get("phases", []))
            return f"Bitte phase=<id> angeben. Verfuegbar: {available}"
        phase = _get_phase(rdata, phase_id)
        if phase is None:
            available = [p.get("id") for p in rdata.get("phases", [])]
            return f"Phase '{phase_id}' nicht gefunden. Verfuegbar: {available}"
        return _format_phase_detail(phase)

    elif cmd == "to_plan":
        phase_id = args.get("phase", "")
        if not phase_id:
            return "Bitte phase=<id> angeben."
        phase = _get_phase(rdata, phase_id)
        if phase is None:
            return f"Phase '{phase_id}' nicht gefunden."
        tasks = _phase_to_plan_tasks(phase)
        return json.dumps({
            "status": "ready",
            "message": f"Phase '{phase_id}' in {len(tasks)} Tasks konvertiert. Verwende plan_create() mit diesen Tasks.",
            "goal": phase.get("name", phase_id),
            "tasks": tasks,
        }, indent=2, ensure_ascii=False)

    elif cmd == "set":
        phase_id = args.get("phase", "")
        new_status = args.get("status", "")
        if not phase_id or not new_status:
            return "Bitte phase=<id> und status=<wert> angeben."
        success, msg = _update_phase_status(rdata, phase_id, new_status)
        if success:
            _save_roadmap(rname or "", rdata)
            return f"Phase '{phase_id}' -> {new_status}"
        return f"Fehler: {msg}"

    else:
        return f"Unbekannter Befehl '{cmd}'. Verfuegbar: status, show, to_plan, set, list, create"
