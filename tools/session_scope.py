"""session_scope.py — Welche Session ist gerade dran?

Eine Stelle für die Session-Identität, damit ``tools/base`` und ``tools/state`` nicht
zirkulär voneinander importieren müssen.

Reihenfolge: ContextVar des Gateways (``gateway.session_context``, pro Task korrekt) →
``HERMES_SESSION_ID`` aus der Env → ``SESSION_ID`` → leer.

Leer heißt: kein Hermes-Kontext (reines CLI-Skript, Test, Subprozess ohne Session). Dann
teilen sich alle Aufrufer einen gemeinsamen Slot — exakt das Verhalten von vor der
Trennung, damit nichts wegbricht.
"""
from __future__ import annotations

import os


def _read_contextvar() -> str:
    """Session-ID aus dem Gateway-ContextVar, ``""`` ohne Gateway im Prozess."""
    try:
        from gateway.session_context import get_session_env

        return (get_session_env("HERMES_SESSION_ID") or "").strip()
    except Exception:  # kein Gateway im Prozess — die Env ist dann die Wahrheit
        return ""


def runtime_session_id() -> str:
    """Session-ID der Laufzeit, oder ``""`` wenn es keine gibt."""
    sid = _read_contextvar()
    if sid:
        return sid
    return (os.environ.get("HERMES_SESSION_ID") or os.environ.get("SESSION_ID") or "").strip()


def scope_key() -> str:
    """Schlüssel für session-scoped State. ``""`` = gemeinsamer Fallback-Slot."""
    return runtime_session_id()
