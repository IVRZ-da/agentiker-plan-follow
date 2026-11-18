#!/usr/bin/env python3
"""Gate fuer ``hermes plugins validate`` (Hermes-Plugin-Katalog) — plan_follow.

Warum: Der Validator ist das CI-Gate des Katalogs, aber ein einzelner roter Check
soll nicht stillschweigend durchgehen. Dieses Skript

* prueft, dass alle erwarteten Checks tatsaechlich existieren (Schutz gegen Umbenennung),
* schlaegt fehl, sobald ein Check rot ist und nicht in der Allowlist steht,
* schlaegt fehl, wenn die Allowlist einen inzwischen gruenen Check nennt
  (veralteter Eintrag → Allowlist leeren).

Einziger bewusst erlaubter roter Check ist ``no core override``: es gibt keine
Plugin-API, die ein Tool eager macht — der Rebind von ``toolsets._HERMES_CORE_TOOLS``
ist der einzige Hebel. Wirkungsnachweis: ``references/core-override-analysis.md``.

Allowlist-Datei: ``references/core_override_allowlist.txt``, eine Zeile je Check:
    check_name: Begruendung
Kommentare mit '#'.

Aufruf
------
    env -u PYTHONPATH <venv>/bin/python scripts/validate_gate.py
    env -u PYTHONPATH <venv>/bin/python scripts/validate_gate.py --self-test
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
ALLOWLIST = PLUGIN_DIR / "references" / "core_override_allowlist.txt"

# Checks, deren Existenz das Gate voraussetzt. Ein Hermes-Update, das sie umbenennt,
# muss hier nachgezogen werden — sonst prueft das Gate ins Leere.
REQUIRED_CHECKS = (
    "declared tools",
    "declared hooks",
    "no core override",
    "security scan",
    "capability probe",
)


def read_allowlist(path: Path | None = None) -> dict[str, str]:
    path = path or ALLOWLIST
    if not path.is_file():
        return {}
    allowed: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition(":")
        allowed[name.strip()] = reason.strip()
    return allowed


def evaluate(checks: list[dict], allowed: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """(fehlende_checks, failures, stale) — reine Logik, ohne Hermes."""
    by_name = {c.get("name"): c for c in checks}
    missing = [n for n in REQUIRED_CHECKS if n not in by_name]
    failures: list[str] = []
    stale: list[str] = []
    for name, check in by_name.items():
        ok = bool(check.get("ok"))
        if not ok and name not in allowed:
            detail = str(check.get("detail") or "").replace("\n", " ")[:240]
            failures.append(f"{name}: {detail}")
        if ok and name in allowed:
            stale.append(name)
    return missing, failures, stale


def run_validator() -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # sonst erbt der Validator fremde site-packages
    proc = subprocess.run(
        ["hermes", "plugins", "validate", "--json", str(PLUGIN_DIR)],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(
            f"✗ validate lieferte kein JSON (exit {proc.returncode})\n"
            f"stdout: {proc.stdout[-500:]}\nstderr: {proc.stderr[-500:]}"
        )


def self_test() -> int:
    """Negativprobe: das Gate MUSS rot werden koennen. Ohne diese Probe waere ein
    immer-gruenes Gate von einem funktionierenden nicht zu unterscheiden."""

    def base() -> list[dict]:
        """Report mit allen Pflicht-Checks gruen — die Faelle variieren daraus."""
        return [{"name": n, "ok": True, "detail": ""} for n in REQUIRED_CHECKS]

    def with_check(name: str, ok: bool) -> list[dict]:
        checks = base()
        for c in checks:
            if c["name"] == name:
                c["ok"] = ok
                c["detail"] = "" if ok else "simulierter Fehler"
        return checks

    cases: list[tuple[str, list[dict], dict[str, str], bool]] = [
        # (beschreibung, checks, allowlist, soll_fehler_ausloesen)
        ("roter Check ohne Allowlist", with_check("security scan", False), {}, True),
        ("roter Check MIT Allowlist", with_check("no core override", False),
         {"no core override": "bewusst"}, False),
        ("gruener Check in Allowlist (stale)", with_check("no core override", True),
         {"no core override": "veraltet"}, True),
    ]
    problems: list[str] = []
    for label, checks, allowed, should_fail in cases:
        missing, failures, stale = evaluate(checks, allowed)
        failed = bool(missing or failures or stale)
        if failed != should_fail:
            problems.append(f"{label}: erwartet {'rot' if should_fail else 'gruen'}, war {'rot' if failed else 'gruen'}")

    # Pflicht-Checks muessen existieren — ein Report ohne sie ist ebenfalls rot.
    missing, _failures, _stale = evaluate([], {})
    if not missing:
        problems.append("leerer Report ohne fehlende Pflicht-Checks erkannt")

    if problems:
        print("✗ Gate-Selbsttest fehlgeschlagen:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"✅ Gate-Selbsttest: {len(cases)} Faelle + Pflicht-Check-Pruefung korrekt")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()

    report = run_validator()
    checks = report.get("checks") or []
    if not checks:
        sys.exit("✗ validate lieferte keine Checks (Crash?)")

    allowed = read_allowlist()
    missing, failures, stale = evaluate(checks, allowed)

    if missing:
        print(f"✗ erwartete Checks fehlen (Hermes-Update?): {missing}")
        return 1
    if stale:
        print(f"✗ Allowlist nennt inzwischen gruene Checks: {', '.join(stale)}")
        print(f"  → Eintrag in {ALLOWLIST.relative_to(PLUGIN_DIR)} entfernen")
        return 1
    if failures:
        print("✗ validate-Gate fehlgeschlagen:")
        for f in failures:
            print(f"  - {f}")
        return 1

    by_name = {c.get("name"): c for c in checks}
    green = sum(1 for c in by_name.values() if c.get("ok"))
    print(
        f"✅ validate-Gate: {green}/{len(by_name)} Checks gruen"
        + (f" (Allowlist: {', '.join(allowed)})" if allowed else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
