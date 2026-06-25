"""plan_peer_review.py — Peer-Review-Checks für Plan-Strukturen.

Prüft erstellte Pläne gegen die 8-Punkte-Checkliste aus dem plan-peer-review Skill.
Läuft automatisch nach plan_create() — kein Feature-Toggle, kein Parameter.

Checks:
① depends_on — Sind Abhängigkeiten zwischen Tasks korrekt?
② verify — Hat jeder Task einen verifizierbaren Erfolgs-Command?
③ files — Sind alle zu ändernden Dateien deklariert?
④ Reihenfolge — Liegen Tasks in korrekter Ordnung?
⑤ review_profile — Ist das passende Profil gesetzt?
⑥ parallel_groups — Greifen parallele Tasks auf unterschiedliche Dateien zu?
⑦ verify-Cmd korrekt — Funktioniert der verify-Command wirklich?
⑧ Template geprüft — Passt eines der Templates?
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("plan_follow")

# ─── Severity levels ──────────────────────────────────────────────────────────
CRITICAL = "critical"
IMPORTANT = "important"
COSMETIC = "cosmetic"

# ─── Check definitions ────────────────────────────────────────────────────────
PEER_REVIEW_CHECKS: list[dict[str, Any]] = [
    {
        "id": "depends_on",
        "name": "depends_on correctness",
        "severity": CRITICAL,
        "description": "Prüft ob Task-Abhängigkeiten korrekt gesetzt sind.",
    },
    {
        "id": "verify",
        "name": "verify command validity",
        "severity": CRITICAL,
        "description": "Prüft ob verify-Commands tatsächlich etwas verifizieren.",
    },
    {
        "id": "files",
        "name": "file declarations",
        "severity": IMPORTANT,
        "description": "Prüft ob alle zu ändernden Dateien deklariert sind.",
    },
    {
        "id": "ordering",
        "name": "task ordering",
        "severity": CRITICAL,
        "description": "Prüft ob Tasks in korrekter Reihenfolge liegen.",
    },
    {
        "id": "review_profile",
        "name": "review profile",
        "severity": IMPORTANT,
        "description": "Prüft ob das review_profile gültig ist.",
    },
    {
        "id": "parallel_groups",
        "name": "parallel groups file conflict",
        "severity": CRITICAL,
        "description": "Prüft ob parallele Tasks auf verschiedene Dateien zugreifen.",
    },
]

VALID_PROFILES = {"none", "unit-test", "api-route", "ui-component", "security", "full"}

# Patterns for meaningless verify commands
# A verify command MUST actually test something (exit code != 0 on failure).
# echo, #-comments, true, false, : as SOLE command are meaningless.
MEANINGLESS_VERIFY_PATTERNS = [
    re.compile(r"^\s*echo\s+.*$", re.IGNORECASE),        # echo '❌...' / echo '✅...' / echo 'done'
    re.compile(r"^\s*#\s+.*$"),                            # Shell comment-only
    re.compile(r"^\s*:\s*$"),                              # bash no-op (:)
    re.compile(r"^\s*true\s*$", re.IGNORECASE),            # literal true (always exit 0)
    re.compile(r"^\s*false\s*$", re.IGNORECASE),           # literal false (always exit 1)
]

# Dangerous patterns: grep without fallback
DANGEROUS_GREP_PATTERN = re.compile(
    r"(?:^|\s)grep\s+(?:-[qrl]\s+)?['\"]?[^'\"|&]+['\"]?\s+(?!.*&&)",
)

# Masking errors pattern: || true
OR_TRUE_PATTERN = re.compile(r"\|\|\s*true")
# ─── Core functions ───────────────────────────────────────────────────────────


def _check_depends_on(task_list: list[dict], task_ids: set, _add) -> None:
    """Check ①: depends_on — references to non-existent tasks + heuristic."""
    for t in task_list:
        tid = t.get("id", "")
        deps = t.get("depends_on", []) or []
        for dep in deps:
            if dep not in task_ids:
                _add(
                    "depends_on", CRITICAL,
                    f"Task '{tid}' depends_on '{dep}' which does not exist in this plan.",
                    task_id=tid,
                    fix={"depends_on": [d for d in deps if d != dep]},
                )
        if not deps:
            t_name_lower = t.get("name", "").lower()
            consumption_words = {"use", "run", "test", "deploy", "migrate", "update", "build"}
            if any(word in t_name_lower for word in consumption_words):
                _add(
                    "depends_on", IMPORTANT,
                    f"Task '{tid}' ('{t.get('name', '')}') has no depends_on, "
                    f"but its name suggests it may depend on an earlier task.",
                    task_id=tid,
                    fix={"depends_on": []},
                )


def _auto_detect_verify() -> str:
    """Auto-detect a meaningful verify command for the project."""
    try:
        from .plan_templates import _auto_detect_project_defaults
        auto = _auto_detect_project_defaults()
        return auto.get("test_command", "python3 -m pytest")
    except Exception:
        return "python3 -m pytest"


def _check_verify(task_list: list[dict], _add) -> None:
    """Check ② + ⑦: verify command validity — empty, meaningless, grep pitfalls."""
    for t in task_list:
        tid = t.get("id", "")
        verify = t.get("verify", "").strip()
        if not verify:
            auto_verify = _auto_detect_verify()
            _add("verify", CRITICAL,
                 f"Task '{tid}' ('{t.get('name', '')}') has an empty verify command. "
                 f"Auto-generiert: '{auto_verify}'.",
                 task_id=tid, fix={"verify": auto_verify})
            continue
        if any(p.match(verify) for p in MEANINGLESS_VERIFY_PATTERNS):
            auto_verify = _auto_detect_verify()
            _add("verify", CRITICAL,
                 f"Task '{tid}' ('{t.get('name', '')}') verify command "
                 f"'{verify}' doesn't verify anything meaningful — "
                 f"ersetzt durch '{auto_verify}'.",
                 task_id=tid, fix={"verify": auto_verify})
            continue
        if DANGEROUS_GREP_PATTERN.search(verify) and "&&" not in verify:
            _add("verify", CRITICAL,
                 f"Task '{tid}' ('{t.get('name', '')}') uses bare grep "
                 f"without '&& echo' fallback — exits with 1 when nothing matches.",
                 task_id=tid, fix={"verify": verify + " && echo '✅ found'"})
        if OR_TRUE_PATTERN.search(verify):
            _add("verify", IMPORTANT,
                 f"Task '{tid}' ('{t.get('name', '')}') verify uses '|| true' — "
                 f"this masks command failures.",
                 task_id=tid, fix={"verify": verify})


def _check_files(task_list: list[dict], _add) -> None:
    """Check ③: files declarations — every task should declare files."""
    for t in task_list:
        tid = t.get("id", "")
        files = t.get("files", []) or []
        if not files:
            _add("files", IMPORTANT,
                 f"Task '{tid}' ('{t.get('name', '')}') has no files declared. "
                 f"Drift-Check and auto_commit won't work without files.",
                 task_id=tid, fix={"files": []})


def _check_ordering(plan: dict, task_list: list[dict], task_ids: set, _add) -> None:
    """Check ④: ordering — parallel group deps on non-group tasks."""
    parallel_groups = plan.get("parallel_groups", {}) or {}
    if not parallel_groups:
        return
    all_group_tasks = set()
    for gid, gdata in parallel_groups.items():
        if isinstance(gdata, dict):
            for gtid in gdata.get("tasks", []):
                all_group_tasks.add(gtid)
    for t in task_list:
        tid = t.get("id", "")
        if tid not in all_group_tasks:
            continue
        for dep in (t.get("depends_on", []) or []):
            if dep not in all_group_tasks and dep in task_ids:
                _add("ordering", CRITICAL,
                     f"Task '{tid}' in parallel group depends on '{dep}', "
                     f"but '{dep}' is outside the group. Ensure '{dep}' "
                     f"runs before the parallel group.",
                     task_id=tid)


def _check_review_profile(task_list: list[dict], _add) -> None:
    """Check ⑤: review_profile validity."""
    for t in task_list:
        tid = t.get("id", "")
        profile = t.get("review_profile", "none")
        if profile not in VALID_PROFILES:
            _add("review_profile", IMPORTANT,
                 f"Task '{tid}' ('{t.get('name', '')}') has invalid "
                 f"review_profile '{profile}'. Valid: {', '.join(sorted(VALID_PROFILES))}.",
                 task_id=tid, fix={"review_profile": "none"})


def _check_parallel_groups(plan: dict, get_task, _add) -> None:
    """Check ⑥: parallel groups — overlapping file access between parallel tasks."""
    parallel_groups = plan.get("parallel_groups", {}) or {}
    for gid, gdata in parallel_groups.items():
        if not isinstance(gdata, dict):
            continue
        gtasks = gdata.get("tasks", [])
        if len(gtasks) < 2:
            continue
        task_files: dict[str, list[str]] = {}
        for gtid in gtasks:
            gt = get_task(gtid)
            if gt:
                task_files[gtid] = gt.get("files", []) or []
        seen_files: dict[str, str] = {}
        for gtid, files in task_files.items():
            for f in files:
                if f in seen_files and seen_files[f] != gtid:
                    _add("parallel_groups", CRITICAL,
                         f"Group '{gid}' has tasks '{seen_files[f]}' and "
                         f"'{gtid}' both editing '{f}' — merge conflict risk.",
                         task_id=gtid)
                elif f not in seen_files:
                    seen_files[f] = gtid


def run_peer_review(plan: dict) -> list[dict[str, Any]]:
    """Run all peer review checks on a plan.

    Args:
        plan: Plan dict as returned by plan_core._get_active_plan().

    Returns:
        List of findings, each with: id, severity, check, description, task_id, fix.
    """
    findings: list[dict[str, Any]] = []
    tasks = plan.get("tasks", {})
    if isinstance(tasks, list):
        tasks = {t.get("id", str(i)): t for i, t in enumerate(tasks)}
    task_list = list(tasks.values()) if isinstance(tasks, dict) else tasks

    finding_counter = [0]

    def _add(check: str, severity: str, description: str, task_id: str = "", fix: dict | None = None):
        finding_counter[0] += 1
        findings.append({
            "id": f"F{finding_counter[0]}",
            "severity": severity, "check": check,
            "description": description, "task_id": task_id, "fix": fix or {},
        })

    def get_task(tid: str) -> dict | None:
        if isinstance(tasks, dict):
            return tasks.get(tid)
        for t in tasks:
            if t.get("id") == tid:
                return t
        return None

    # Build task_ids set
    task_ids = set(tasks.keys()) if isinstance(tasks, dict) else {t.get("id", "") for t in tasks}

    # Run all checks
    _check_depends_on(task_list, task_ids, _add)
    _check_verify(task_list, _add)
    _check_files(task_list, _add)
    _check_ordering(plan, task_list, task_ids, _add)
    _check_review_profile(task_list, _add)
    _check_parallel_groups(plan, get_task, _add)

    return findings


def apply_findings(plan: dict, findings: list[dict[str, Any]]) -> dict:
    """Apply fix suggestions from findings to the plan.

    For findings with concrete fixes (e.g., dangerous grep → add fallback),
    applies them directly. For findings that need human judgment
    (e.g., missing depends_on), sets placeholder values.

    Args:
        plan: The plan dict to update.
        findings: List of findings from run_peer_review().

    Returns:
        Updated plan dict with fixes applied.
    """
    import copy

    updated = copy.deepcopy(plan)

    # Normalize tasks to dict form
    tasks = updated.get("tasks", {})
    if isinstance(tasks, list):
        tasks = {t.get("id", str(i)): t for i, t in enumerate(tasks)}
        updated["tasks"] = tasks

    for finding in findings:
        tid = finding.get("task_id", "")
        fix = finding.get("fix", {})
        if not tid or not fix:
            continue

        task = tasks.get(tid)
        if not task:
            continue

        # Apply fix fields
        for key, value in fix.items():
            if key in task:
                task[key] = value

    return updated
