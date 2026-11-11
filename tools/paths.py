"""paths.py — Pfad-Guards fuer plan_follow.

Schuetzt die Produktionsdaten des Plugins vor Schreibzugriffen aus Testlaeufen.

Hintergrund: bis v0.5.31 hat ``tests/conftest.py`` in einer autouse-Fixture
ALLE ``*.json`` in ``plan_core.PLANS_DIR`` mit ``"{}"`` ueberschrieben und
Unterordner per ``shutil.rmtree`` geloescht. Weil die Fixture den ganzen Block in
``except Exception: pass`` kapselte und nur 7 von 37 Testfiles ``PLANS_DIR``
patchen, wurden am 10.11.2026 im echten ``~/.hermes/plans`` 81 Plaene,
``plans_index.json``, ``archived/`` und ``templates/`` zerstoert — bei
1480/1480 gruenen Tests.

Der Guard sitzt deshalb hier, in den Schreib-Primitiven des Produktionscodes,
und nicht im Testcode: Test-Fixtures koennen Exceptions schlucken, dieser Guard
wird dort aufgerufen, wo tatsaechlich geschrieben wird.

Aktivierung: ``PLAN_FOLLOW_TEST_GUARD=1`` (setzt ``tests/conftest.py`` beim
Import). Ohne die Variable verhaelt sich das Plugin unveraendert.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

GUARD_ENV = "PLAN_FOLLOW_TEST_GUARD"


def _production_roots() -> tuple[Path, ...]:
    """Die geschuetzten Produktionswurzeln (beim Import eingefroren)."""
    home = Path.home()
    return (
        home / ".hermes" / "plans",
        home / ".hermes" / "roadmaps",
        home / ".hermes" / "shared",
    )


# Beim Import einfrieren: ein Test, der Path.home() monkeypatcht, darf den Guard
# nicht entwaffnen.
_PROTECTED_ROOTS: tuple[Path, ...] = _production_roots()


def guard_enabled() -> bool:
    """True wenn der Test-Guard aktiv ist."""
    return os.environ.get(GUARD_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def is_protected(path: Union[str, Path]) -> bool:
    """True wenn *path* in einer geschuetzten Produktionswurzel liegt."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return any(resolved == root or root in resolved.parents for root in _PROTECTED_ROOTS)


def assert_writable(path: Union[str, Path]) -> None:
    """Wirft RuntimeError, wenn bei aktivem Guard in Produktionsdaten geschrieben wuerde.

    Aufzurufen in jeder Schreib-Primitive (write_text, unlink, move, mkdir).
    """
    if guard_enabled() and is_protected(path):
        raise RuntimeError(
            f"Write-Guard aktiv ({GUARD_ENV}=1): Schreibzugriff auf Produktionspfad "
            f"blockiert: {path}. Tests muessen PLANS_DIR/ARCHIVE_DIR/ROADMAPS_DIR/"
            f"SHARED_DIR auf ein temporaeres Verzeichnis umbiegen."
        )


def protected_roots() -> tuple[Path, ...]:
    """Die eingefrorenen Produktionswurzeln (fuer Diagnose/Health-Check)."""
    return _PROTECTED_ROOTS


__all__ = [
    "GUARD_ENV",
    "assert_writable",
    "guard_enabled",
    "is_protected",
    "protected_roots",
]
