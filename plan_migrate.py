"""plan_migrate.py — Legacy-Migration: Alte JSON-Pläne in Kanban importieren.

Scannt ~/.hermes/plans/*.json und erzeugt für jeden Plan einen
Kanban-Task-Graphen (Root + Child-Tasks mit dependencies).

Ignoriert: plans_index.json, bereits migrierte Pläne (doppelte plan_id).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("plan_follow")

PLANS_DIR = Path.home() / ".hermes" / "plans"

# ─── Kanban-DB Verfügbarkeit ─────────────────────────────────────────────────


def _kanban_db():
    try:
        from hermes_cli import kanban_db
        return kanban_db
    except ImportError:
        return None


def _kanban_profile() -> str:
    import os
    return os.environ.get("HERMES_PROFILE", "default")


# ─── Migration ────────────────────────────────────────────────────────────────


def migrate_legacy_plans(dry_run: bool = True) -> dict:
    """Migrate old JSON plans from ~/.hermes/plans/ into Kanban-DB.

    Args:
        dry_run: If True (default), only scan and report without writing.

    Returns:
        Dict with migration report:
        {
            "status": "ok" | "no_kanban" | "no_plans",
            "found": N,           # Total JSON plans found
            "migrated": N,        # Successfully migrated
            "skipped": N,         # Already exists in Kanban
            "failed": N,          # Migration errors
            "plans": [...],       # Per-plan details
        }
    """
    kdb = _kanban_db()
    if not kdb:
        return {"status": "no_kanban", "message": "Kanban-DB nicht verfügbar — Migration nicht möglich"}

    if not PLANS_DIR.exists():
        return {"status": "no_plans", "message": f"Plans-Verzeichnis nicht gefunden: {PLANS_DIR}"}

    # Alle JSON-Pläne scannen
    json_files = sorted(PLANS_DIR.glob("*.json"), reverse=True)
    json_files = [f for f in json_files if f.name != "plans_index.json"]

    if not json_files:
        return {"status": "no_plans", "message": "Keine JSON-Pläne gefunden"}

    # Bereits migrierte plan_ids aus Kanban ermitteln
    existing_ids = set()
    try:
        conn = kdb.connect()
        rows = conn.execute(
            "SELECT body FROM tasks WHERE body LIKE '%\"type\":\"plan\"%'"
        ).fetchall()
        for row in rows:
            try:
                body = json.loads(row[0]) if row[0] else {}
                pid = body.get("plan_id")
                if pid:
                    existing_ids.add(pid)
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        logger.warning("Kanban query failed: %s", e)

    report = {
        "status": "ok",
        "found": len(json_files),
        "migrated": 0,
        "skipped": 0,
        "failed": 0,
        "plans": [],
    }

    for f in json_files:
        plan_id = f.stem
        result = _migrate_single_plan(f, plan_id, existing_ids, kdb, dry_run)
        report["plans"].append(result)
        if result["status"] == "migrated":
            report["migrated"] += 1
        elif result["status"] == "skipped":
            report["skipped"] += 1
        else:
            report["failed"] += 1

    return report


def _migrate_single_plan(
    path: Path, plan_id: str, existing_ids: set, kdb, dry_run: bool,
) -> dict:
    """Migrate a single JSON plan file into Kanban.

    Returns dict with plan_id, status (migrated/skipped/failed), details.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"plan_id": plan_id, "status": "failed", "error": str(e)}

    # Prüfen ob bereits migriert
    if plan_id in existing_ids:
        return {"plan_id": plan_id, "status": "skipped", "reason": "Bereits in Kanban vorhanden"}

    # JSON-Daten extrahieren
    goal = data.get("goal", plan_id)[:80]
    tasks = data.get("tasks", {})
    current_task = data.get("current_task")
    created = data.get("created", "")
    repo = data.get("repo", "")
    repos = data.get("repos", [])
    parallel_groups = data.get("parallel_groups", {})

    if dry_run:
        return {
            "plan_id": plan_id,
            "status": "dry_run",
            "goal": goal,
            "task_count": len(tasks),
            "message": f"Würde migrieren: {goal} ({len(tasks)} Tasks)" if tasks else f"Würde migrieren: {goal} (0 Tasks)",
        }

    # ─── Echten Import durchführen ────────────────────────────────────
    profile = _kanban_profile()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Root-Task erstellen
    root_body = json.dumps({
        "type": "plan",
        "plan_id": plan_id,
        "goal": goal,
        "created": created or now,
        "repo": repo,
        "repos": repos,
        "parallel_groups": parallel_groups,
        "current_task": current_task,
        "migrated_at": now,
        "template": "migrated",
        "version": "2",
    })

    try:
        kdb.create_task(
            title=goal[:80],
            body=root_body,
            assignee=profile,
            initial_status="in_progress" if current_task else "completed",
            priority=5,
        )
    except Exception as e:
        return {"plan_id": plan_id, "status": "failed", "error": f"Root-Task: {e}"}

    # 2. Child-Tasks (Unter-Tasks des Plans)
    child_count = 0
    for tid, tdef in tasks.items():
        t_name = tdef.get("name", tid)
        t_verify = tdef.get("verify", "")
        t_files = tdef.get("files", [])
        t_status = tdef.get("status", "pending")
        t_review = tdef.get("review_profile", "none")
        depends_on = tdef.get("depends_on", [])

        # Kanban-Status mappen
        kb_status = {
            "completed": "done",
            "in_progress": "running",
            "pending": "pending",
            "aborted": "blocked",
        }.get(t_status, "pending")

        task_body = json.dumps({
            "type": "plan_task",
            "plan_id": plan_id,
            "task_id": tid,
            "name": t_name,
            "verify": t_verify,
            "files": t_files,
            "review_profile": t_review,
            "depends_on": depends_on,
        })

        try:
            kdb.create_task(
                title=f"{plan_id[:30]}:{tid} — {t_name[:40]}",
                body=task_body,
                assignee=profile,
                initial_status=kb_status,
                skills=[f"review:{t_review}"] if t_review != "none" else [],
                priority=5,
            )
            child_count += 1
        except Exception as e:
            logger.warning("Child-Task %s/%s fehlgeschlagen: %s", plan_id, tid, e)
            continue

        # Dependencies verlinken
        for dep in depends_on:
            try:
                kdb.link_tasks(f"{plan_id}:{dep}", f"{plan_id}:{tid}")
            except Exception:
                pass

    return {
        "plan_id": plan_id,
        "status": "migrated",
        "goal": goal,
        "task_count": child_count,
        "message": f"{goal} ({child_count} Tasks migriert)",
    }


# ─── Tool-Handler ─────────────────────────────────────────────────────────────


def plan_migrate_tool(args: dict, **kwargs) -> str:
    """Migrate alte JSON-Pläne in Kanban-DB.

    Parameters:
    - dry_run (bool, optional): Wenn True (default), nur scannen ohne zu schreiben.
      Auf False setzen für echten Import.

    Returns:
    - Detaillierter Report über gefundene/migrierte/übersprungene/failed Pläne.
    """
    from ._fmt import fmt_err, fmt_info, fmt_ok, fmt_table

    dry_run = args.get("dry_run", True)

    if not _kanban_db():
        return fmt_err("Kanban-DB nicht verfügbar. Migration nicht möglich.")

    result = migrate_legacy_plans(dry_run=dry_run)

    if result["status"] == "no_kanban":
        return fmt_err(result["message"])
    if result["status"] == "no_plans":
        return fmt_info(result["message"])

    lines = [
        f"Gefundene JSON-Pläne: {result['found']}",
        f"Migriert: {result['migrated']}",
        f"Übersprungen (bereits in Kanban): {result['skipped']}",
        f"Fehlgeschlagen: {result['failed']}",
    ]

    details = []
    for p in result.get("plans", []):
        status_icon = {
            "migrated": "✅",
            "skipped": "⏭️",
            "failed": "❌",
            "dry_run": "🔍",
        }.get(p.get("status", "?"), "?")
        details.append({
            "plan": p.get("plan_id", "?")[:30],
            "status": f"{status_icon} {p.get('status', '?')}",
            "detail": p.get("message") or p.get("error", "") or "",
        })

    table = fmt_table(details, columns=["Plan", "Status", "Detail"])

    if dry_run:
        lines.insert(0, "🔍 TROCKENLAUF — Setze dry_run=False für echten Import")
        return fmt_info("\n".join(lines) + "\n\n" + table)

    return fmt_ok({
        "status": "completed",
        "total": result["found"],
        "migrated": result["migrated"],
        "skipped": result["skipped"],
        "failed": result["failed"],
        "details": result.get("plans", []),
    })
