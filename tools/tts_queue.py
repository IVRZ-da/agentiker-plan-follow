"""tts_queue.py — TTS-Events ausserhalb der Plan-Datei.

Bis v0.5.32 lagen die TTS-Marker als ``plan["tts_flags"]`` in der Plan-Datei.
Der Banner hat sie beim Anzeigen entfernt und die Datei zurueckgeschrieben
(``_build_tts_banner`` → ``_save_plan``). Damit war ein Anzeige-Pfad ein
Schreibpfad: ein veralteter In-Memory-Stand konnte den neueren Disk-Stand
ueberschreiben.

v0.5.33 trennt Produzent und Konsument:

* Produzent (``enqueue``) laeuft in ``create_plan``/``complete_task`` und schreibt
  append-only in ``~/.hermes/shared/tts_queue.json`` (eigene Datei, eigener Lock,
  atomar via tempfile + os.replace).
* Konsument (``read_events``) ist **rein lesend**. Der Renderpfad darf nichts
  schreiben; den water mark setzt der Observer-Hook ``post_tool_call``
  (``commit_watermark``).

Struktur der Datei::

    {
      "seq": 7,                         # letzte vergebene Sequenz
      "events": [{"seq": 7, "kind": "task_completed", ...}],
      "last_seq": 7,                    # bis hierher wurde angesagt
      "emitted": {"epilogue:p1:s1": true}
    }
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .paths import assert_writable

try:  # pragma: no cover - nur auf POSIX
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

QUEUE_FILENAME = "tts_queue.json"
LOCK_FILENAME = "tts_queue.lock"
MAX_EVENTS = 200


def _shared_dir() -> Path:
    # Lazy import: coord_state haelt SHARED_DIR mutierbar (Tests set_shared_dir)
    from .. import coord_state

    return Path(coord_state.SHARED_DIR)


def queue_path() -> Path:
    return _shared_dir() / QUEUE_FILENAME


def lock_path() -> Path:
    return _shared_dir() / LOCK_FILENAME


@contextmanager
def _locked():
    """Sidecar-Lock: die Lock-Datei wird nie ersetzt (kein os.replace)."""
    shared = _shared_dir()
    shared.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path(), "a+")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _empty_state() -> dict:
    return {"seq": 0, "events": [], "last_seq": 0, "emitted": {}}


def _read_unlocked() -> dict:
    """Queue lesen. Kaputte/fehlende Datei = leere Queue (nie werfen)."""
    path = queue_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return _empty_state()
    except OSError:
        return _empty_state()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    state = _empty_state()
    state.update(
        seq=int(data.get("seq") or 0),
        last_seq=int(data.get("last_seq") or 0),
        events=[e for e in data.get("events") or [] if isinstance(e, dict)],
        emitted=dict(data.get("emitted") or {}),
    )
    return state


def _write_unlocked(state: dict) -> None:
    path = queue_path()
    assert_writable(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tts_queue.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def enqueue(
    kind: str,
    plan_id: str,
    task_id: str = "",
    name: str = "",
    message: str = "",
    session_id: str = "",
) -> int:
    """Event anhaengen. Returns die vergebene Sequenznummer."""
    with _locked():
        state = _read_unlocked()
        state["seq"] += 1
        seq = state["seq"]
        state["events"].append(
            {
                "seq": seq,
                "kind": kind,
                "plan_id": plan_id,
                "task_id": task_id,
                "name": name,
                "message": message,
                "session_id": session_id,
                "ts": time.time(),
            }
        )
        if len(state["events"]) > MAX_EVENTS:
            state["events"] = state["events"][-MAX_EVENTS:]
        _write_unlocked(state)
    return seq


def read_state() -> dict:
    """Rein lesender Snapshot (kein Write, kein Lock noetig)."""
    return _read_unlocked()


def read_events(plan_id: str, session_id: str = "", since_seq: int = 0) -> list[dict]:
    """Events fuer diesen Plan seit ``since_seq`` — rein lesend."""
    state = _read_unlocked()
    floor = max(since_seq, state["last_seq"])
    result = []
    for event in state["events"]:
        if int(event.get("seq") or 0) <= floor:
            continue
        if event.get("plan_id") != plan_id:
            continue
        owner = event.get("session_id") or ""
        if owner and session_id and owner != session_id:
            continue
        result.append(event)
    return result


def commit_watermark(seq: int) -> None:
    """Water mark setzen — ausschliesslich aus Observer-Hooks aufrufen."""
    if seq <= 0:
        return
    with _locked():
        state = _read_unlocked()
        if seq > state["last_seq"]:
            state["last_seq"] = seq
            # Angesagte Events duerfen weg (die Datei bleibt klein)
            state["events"] = [e for e in state["events"] if int(e.get("seq") or 0) > seq]
            _write_unlocked(state)


def epilogue_key(plan_id: str, session_id: str) -> str:
    return f"epilogue:{plan_id}:{session_id or '-'}"


def is_emitted(key: str) -> bool:
    return bool(_read_unlocked()["emitted"].get(key))


def mark_emitted(key: str) -> None:
    with _locked():
        state = _read_unlocked()
        state["emitted"][key] = True
        # Nur die letzten 200 Merker behalten
        if len(state["emitted"]) > 200:
            keep = list(state["emitted"])[-200:]
            state["emitted"] = {k: state["emitted"][k] for k in keep}
        _write_unlocked(state)


def reset() -> None:
    """Queue leeren (Tests/Wartung)."""
    with _locked():
        _write_unlocked(_empty_state())


def describe() -> Optional[str]:
    """Kurzbeschreibung fuer Diagnose (read-only)."""
    state = _read_unlocked()
    return (
        f"tts_queue: {len(state['events'])} offen, seq={state['seq']}, "
        f"last_seq={state['last_seq']}, emitted={len(state['emitted'])}"
    )
