"""base.py — Module state + Persistence + Session for plan_follow tools/ subpackage."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .paths import assert_writable
from .resolver import (
    resolve_archive_dir,
    resolve_plans_dir,
    resolve_plans_index,
    resolve_roadmaps_dir,
)
from .state import STATE

logger = logging.getLogger("plan_follow")


class PlanConflictError(RuntimeError):
    """Ein anderer Prozess hat den Plan seit dem Laden veraendert.

    Der Schreibvorgang wird abgewiesen und der fremde Stand bleibt erhalten;
    der eigene Stand wird als ``<plan_id>.conflict-<ts>.json`` gesichert.
    """


class PlanGoneError(RuntimeError):
    """Der Plan wurde archiviert oder geloescht — er darf nicht auferstehen."""


def get_session_id() -> str:
    """Get the current Hermes session ID, with fallback.

    Uses HERMES_SESSION_ID first (set by Hermes runtime), then SESSION_ID,
    then a once-generated UUID as last resort. Cached in _SESSION_ID after
    first call so all callers within a plan_session lifecycle agree on the
    same ID.
    """
    if STATE.session_id is not None:
        return STATE.session_id
    sid = os.environ.get("HERMES_SESSION_ID") or os.environ.get("SESSION_ID") or ""
    if not sid:
        sid = str(uuid.uuid4())
    # Setze die Umgebungsvariable, damit Subprozesse die selbe Session-ID sehen
    os.environ.setdefault("HERMES_SESSION_ID", sid)
    STATE.session_id = sid
    return STATE.session_id


def reset_session_id() -> None:
    """Reset the cached session ID (for testing)."""
    STATE.session_id = None


# ─── In-Memory Cache ─────────────────────────────────────────────────────────

def _reset_cache():
    STATE.active_plan = None
    STATE.active_plan_id = None
    STATE.active_plan_sig = None


# ─── Tool Usage Metrics ────────────────────────────────────────────────────────

def reset_tool_metrics():
    """Reset metrics and drift warnings for a new task."""
    STATE.tool_metrics = {}
    STATE.drift_warnings = []


def record_tool_call(tool_name: str, duration_ms: int, status: str):
    """Record a tool call for the active plan/task."""
    if not STATE.active_plan or not STATE.active_plan.get("current_task"):
        return
    tid = STATE.active_plan.get("current_task", "?")
    if tid not in STATE.tool_metrics:
        STATE.tool_metrics[tid] = {"total_calls": 0, "total_ms": 0, "by_category": {}}
    STATE.tool_metrics[tid]["total_calls"] += 1
    STATE.tool_metrics[tid]["total_ms"] += duration_ms
    cat = tool_name.split("_")[0] if "_" in tool_name else tool_name
    STATE.tool_metrics[tid].setdefault("by_category", {}).setdefault(cat, {"calls": 0, "ms": 0})
    STATE.tool_metrics[tid]["by_category"][cat]["calls"] += 1
    STATE.tool_metrics[tid]["by_category"][cat]["ms"] += duration_ms

def record_drift_warning(message: str):
    """Record a proactive drift warning from the post_tool_call hook."""
    if message not in STATE.drift_warnings:
        STATE.drift_warnings.append(message)
        logger.info("Drift warning recorded: %s", message)


def get_tool_metrics() -> dict:
    """Get current task's tool usage metrics."""
    if not STATE.active_plan or not STATE.active_plan.get("current_task"):
        return {}
    tid = STATE.active_plan["current_task"]
    return STATE.tool_metrics.get(tid, {})


def get_drift_warnings() -> list[str]:
    """Get drift warnings from the current session."""
    return list(STATE.drift_warnings)


# ─── Plans Index (Cross-Session Recovery) ─────────────────────────────────────


def _to_utc_iso(value: object) -> str:
    """Best-effort: beliebigen ISO-Timestamp nach UTC-aware normalisieren.

    Legacy-Werte in plans_index.json waren naiv/lokal, neue sind UTC-aware.
    Gemischte Werte machen jeden Vergleich/Sortierung um 1-2h falsch bzw. werfen
    TypeError beim Subtrahieren.
    """
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naiver Wert = lokale Zeit
    return dt.astimezone(timezone.utc).isoformat()


def _update_plans_index(plan: dict) -> None:
    """Write active plan info to a small index file for session recovery."""
    index = {}
    if resolve_plans_index().exists():
        try:
            index = json.loads(resolve_plans_index().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    if plan.get("current_task"):
        index["active_plan_id"] = plan["plan_id"]
        index["active_goal"] = plan.get("goal", "")[:80]
        index["active_since"] = _to_utc_iso(plan.get("created", ""))
    else:
        # Erledigter/abgebrochener Plan darf nicht als "aktiv" gelten. Sonst
        # zeigt plans_index.json dauerhaft auf einen 14/14-Plan und jede
        # Recovery adoptiert ihn erneut.
        index.pop("active_plan_id", None)
        index.pop("active_goal", None)
        index.pop("active_since", None)
    assert_writable(resolve_plans_index())
    try:
        resolve_plans_index().write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("plans_index.json could not be written")


def _clear_plans_index() -> None:
    """Remove active plan entry from plans_index.json."""
    index = {}
    if resolve_plans_index().exists():
        try:
            index = json.loads(resolve_plans_index().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    index.pop("active_plan_id", None)
    index.pop("active_goal", None)
    index.pop("active_since", None)
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    assert_writable(resolve_plans_index())
    try:
        resolve_plans_index().write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("plans_index.json could not be written")


def _recover_plan_from_disk() -> Optional[str]:
    """Find the most recent active plan on disk.

    Search order:
    1. plans_index.json → active_plan_id, only if plan has a current_task
    2. Newest .json with current_task set (actively in progress)

    Returns plan_id or None (no in-progress plan on disk).
    """
    # 1. Index file — only if the plan has a valid current_task
    if resolve_plans_index().exists():
        try:
            index = json.loads(resolve_plans_index().read_text(encoding="utf-8"))
            pid = index.get("active_plan_id")
            if pid and _plan_path(pid).exists():
                plan = _load_plan(pid)
                if plan and plan.get("current_task"):
                    logger.info("Disk-Recovery (Index): Plan '%s' loaded from index", pid)
                    return pid
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    # 2. Neueste JSON mit current_task != null
    json_files = sorted(
        resolve_plans_dir().glob("*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for f in json_files:
        if f.name == "plans_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("current_task"):
                pid = data.get("plan_id", f.stem)
                logger.info("Disk-Recovery (Active): Plan '%s' loaded from active JSON", pid)
                return pid
        except (json.JSONDecodeError, OSError):
            continue

    # No in-progress plan found — return None so _get_active_plan() stays empty
    return None


# ─── JSON Persistence ─────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    """Lazy init: create data dirs on first write (not at module import)."""
    plans_dir = resolve_plans_dir()
    roadmaps_dir = resolve_roadmaps_dir()
    assert_writable(plans_dir)
    assert_writable(roadmaps_dir)
    plans_dir.mkdir(parents=True, exist_ok=True)
    roadmaps_dir.mkdir(parents=True, exist_ok=True)


def _plan_path(plan_id: str) -> Path:
    return resolve_plans_dir() / f"{plan_id}.json"


def _plan_disk_signature(plan_id: str) -> Optional[tuple]:
    """Signatur der Plan-Datei: (mtime_ns, size, sha256).

    Die Signatur ist die einzige Verbindung zwischen Prozess-Cache und Platte.
    Sie wird nach jedem Write gesetzt und bei jedem ``_get_active_plan()``
    geprueft — damit kann der Banner keinen Stand behaupten, der auf der Platte
    nicht (mehr) gilt.
    """
    path = _plan_path(plan_id)
    try:
        data = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        logger.warning("Signatur fuer Plan '%s' nicht lesbar: %s", plan_id, exc)
        return None
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (mtime, len(data), hashlib.sha256(data).hexdigest())


def _save_plan(plan: dict) -> None:
    """Persist a plan — konfliktgeschuetzt und atomar.

    Datenverlust-Schutz (v0.5.32): ein Plan ohne ``plan_id`` oder ohne ``tasks``
    wird nie geschrieben.

    v0.5.33 (Schreibpfad):
    * Ein archivierter/geloeschter Plan wird nicht wiederbelebt (PlanGoneError).
    * Hat ein anderer Prozess seit dem Laden geschrieben, wird nicht
      ueberschrieben (PlanConflictError + Konfliktkopie).
    * Geschrieben wird ueber tempfile + os.replace (kein halber Plan bei Crash).
    * Die Signatur wird NACH dem Write gesetzt, sonst meldet der naechste
      Lesezugriff einen Konflikt mit sich selbst.
    """
    _ensure_dirs()
    plan_id = plan.get("plan_id") if isinstance(plan, dict) else None
    if not plan_id:
        raise ValueError("_save_plan: 'plan_id' fehlt — Schreiben abgelehnt (Datenverlust-Schutz)")
    if not plan.get("tasks"):
        raise ValueError(
            f"_save_plan: Plan '{plan_id}' hat keine Tasks — Schreiben abgelehnt (Datenverlust-Schutz)"
        )

    path = _plan_path(plan_id)
    assert_writable(path)

    # Archivierter Plan darf nicht auferstehen
    archived = resolve_archive_dir() / f"{plan_id}.json"
    if archived.exists():
        raise PlanGoneError(
            f"Plan '{plan_id}' ist archiviert — Schreiben abgelehnt. "
            "Zum Weiterarbeiten plan_restore() benutzen."
        )

    disk_sig = _plan_disk_signature(plan_id)
    if disk_sig is not None and STATE.active_plan_sig is not None and disk_sig != STATE.active_plan_sig:
        conflict_path = path.with_name(
            f"{plan_id}.conflict-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        try:
            conflict_path.write_text(
                json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Konfliktkopie fuer '%s' fehlgeschlagen: %s", plan_id, exc)
        raise PlanConflictError(
            f"Plan '{plan_id}' wurde von einem anderen Prozess geaendert. "
            f"Eigener Stand gesichert unter {conflict_path.name}. "
            "Bitte plan_select()/plan_current() neu laden und wiederholen."
        )

    # .bak aus dem alten Inhalt
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if isinstance(existing, dict) and existing.get("tasks"):
            try:
                shutil.copy2(path, path.with_suffix(".json.bak"))
            except OSError:
                logger.warning("plan backup failed for %s", path)

    payload = json.dumps(plan, indent=2, ensure_ascii=False)
    tmp_path = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{plan_id}.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    STATE.active_plan = plan
    STATE.active_plan_id = plan["plan_id"]
    STATE.active_plan_sig = (path.stat().st_mtime_ns, len(payload.encode("utf-8")), hashlib.sha256(payload.encode("utf-8")).hexdigest())
    _update_plans_index(plan)

    # Optional: Git-Commit wenn PLANS_DIR ein Git-Repo ist
    # Nur bei create_plan oder complete_task (nicht bei jedem update)
    from .coordination import _git_commit_if_active  # noqa: F811
    _git_commit_if_active(plan)


def _load_plan(plan_id: str) -> Optional[dict]:
    """Plan von der Platte lesen. Kaputte/unlesbare Dateien liefern None.

    Bewusst tolerant: ein gleichzeitiger Writer darf den Banner nicht mit einer
    JSONDecodeError-Exception aus dem Hook katapultieren.
    """
    path = _plan_path(plan_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        logger.warning("Plan '%s' nicht lesbar: %s", plan_id, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Plan '%s' ist beschaedigt (JSON): %s", plan_id, exc)
        return None
    return data if isinstance(data, dict) else None


def _get_active_plan(recover: bool = True) -> Optional[dict]:
    """Get the active plan — der Disk-Stand gewinnt gegen den Cache.

    ``recover=False`` schaltet die Disk-Adoption ab. Der Banner benutzt das:
    Adoption ist ein Besitzakt (``_try_session_recovery``) und darf nicht als
    Nebeneffekt eines Lesezugriffs passieren — sonst adoptiert ein Gateway-
    Prozess den Plan einer fremden Session.

    Fallback-Kette:
    1. In-Memory-Cache, aber nur solange die Signatur der Datei unveraendert ist
       (sonst neu laden bzw. Cache leeren, wenn die Datei verschwunden ist)
    2. Ohne Signatur (Altbestand/Restart): Datei ist autoritativ
    3. Disk-Scan via plans_index.json / newest JSON (nur mit ``recover=True``)
    """
    # 1. In-Memory mit Freshness-Pruefung
    if STATE.active_plan is not None:
        pid = STATE.active_plan_id or STATE.active_plan.get("plan_id") or ""
        if not pid:
            return STATE.active_plan

        if STATE.active_plan_sig is None:
            # Kein Signatur-Anker (Altbestand, Test-Setup, Restart): Platte gewinnt.
            fresh = _load_plan(pid)
            if fresh is None:
                logger.info("Plan '%s' nicht auf der Platte — Cache geleert", pid)
                _reset_cache()
                return None
            if fresh != STATE.active_plan:
                logger.info("Plan '%s' auf der Platte neuer — Cache neu geladen", pid)
                STATE.active_plan = fresh
            STATE.active_plan_sig = _plan_disk_signature(pid)
            return STATE.active_plan

        disk_sig = _plan_disk_signature(pid)
        if disk_sig == STATE.active_plan_sig:
            return STATE.active_plan
        if disk_sig is None:
            logger.info("Plan '%s' ist von der Platte verschwunden — Cache geleert", pid)
            _reset_cache()
            return None

        fresh = _load_plan(pid)
        if fresh is None:
            _reset_cache()
            return None
        logger.info("Plan '%s' hat sich auf der Platte geaendert — neu geladen", pid)
        STATE.active_plan = fresh
        STATE.active_plan_sig = disk_sig
        return fresh

    # 2. Disk-Scan
    if not recover:
        return None
    plan_id = _recover_plan_from_disk()
    if plan_id:
        # Lazy import to avoid circular dependency
        from .task import set_active_plan  # noqa: F811
        if set_active_plan(plan_id):
            return STATE.active_plan

    # 3. Honcho — bewusst NICHT mehr (v0.5.32)
    # Der Fallback war doppelt kaputt: POST /v3/workspaces/{ws}/conclusions/query
    # ist semantische Suche und antwortet ohne observer/observed mit HTTP 422;
    # zusaetzlich schrieb das Plugin hart in Workspace 'plan-follow'/Peer
    # 'plan-follow-agent', waehrend ~/.hermes/honcho.json 'hermes'/'johannes' nutzt.
    # Honcho speichert ohnehin nur die plan_id, nie den Planinhalt (Recovery unmoeglich).
    return None


def plan_for_write(plan_id: str = "") -> Optional[dict]:
    """Plan frisch von der Platte laden — fuer mutierende Tools.

    Mutierende Tools duerfen nicht auf einem beliebig alten In-Memory-Objekt
    arbeiten: sonst wird eine Aenderung auf Basis eines veralteten Standes
    geschrieben (Lost Update). ``_save_plan`` prueft zusaetzlich die Signatur.
    """
    pid = plan_id or STATE.active_plan_id or _recover_plan_from_disk() or ""
    if not pid:
        return None
    plan = _load_plan(pid)
    if plan is None:
        _reset_cache()
        return None
    STATE.active_plan = plan
    STATE.active_plan_id = pid
    STATE.active_plan_sig = _plan_disk_signature(pid)
    return plan


def _get_cached_plan() -> Optional[dict]:
    """Get active plan from in-memory cache ONLY — no disk/Honcho recovery.

    Use this in the pre_llm_call hook to avoid leaking plans
    from other sessions. Plans on disk are still accessible
    via plan_list() + plan_select().
    """
    return STATE.active_plan


# ─── Module __getattr__: backward-compatible attribute access ────────────────
# These proxy to STATE so that `from .base import _active_plan` works correctly.
# (PEP 562 — Python 3.7+)

def __getattr__(name: str):
    if name == "_active_plan":
        return STATE.active_plan
    if name == "_active_plan_id":
        return STATE.active_plan_id
    if name == "_active_plan_sig":
        return STATE.active_plan_sig
    if name == "_tool_metrics":
        return STATE.tool_metrics
    if name == "_drift_warnings":
        return STATE.drift_warnings
    if name == "_SESSION_ID":
        return STATE.session_id
    raise AttributeError(f"module 'plan_follow.tools.base' has no attribute '{name}'")


# ─── Archive ───────────────────────────────────────────────────────────────────
