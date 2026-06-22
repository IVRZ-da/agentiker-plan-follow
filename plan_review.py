"""
plan_review.py — Review-Dispatch-Logik für das plan_follow Plugin.

Stellt die Verbindung zwischen Review-Profilen und der unabhängigen
Code-Review-Prüfung her. Enthält:
  - dispatch_review(): Bereitet Review-Daten auf (task, files, profile)
  - build_review_prompt(): Baut den Prompt für den delegate_task Reviewer
  - validate_review_result(): Validiert das JSON-Verdict des Reviewers
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .review_profiles import get_profile

logger = logging.getLogger("plan_review")


def dispatch_review(
    profile_name: str, task: dict, depth: str = "normal"
) -> dict[str, Any]:
    """Prepare review data for a task.

    This does NOT execute the review — it prepares the data that the Agent
    uses to call delegate_task. The actual review dispatch happens via the
    [REVIEW_PENDING] marker in the pre_llm_call hook.

    Args:
        profile_name: Review profile name (unit-test, api-route, etc.)
        task: Task dict from the plan (must include 'files', 'id', 'name')
        depth: Review depth ('quick', 'normal', 'deep')

    Returns:
        Dict with 'status' key:
          - 'ready' — review can proceed
          - 'skipped' — no profile or no files
          - 'error' — invalid state
    """
    profile = get_profile(profile_name)
    if profile_name == "none" or not profile["checks"]:
        return {
            "status": "skipped",
            "message": "No checks in profile 'none'.",
        }
    if not task.get("files"):
        return {
            "status": "skipped",
            "message": f"Task '{task.get('id') or task.get('task_id', '?')}' has no files to review.",
        }

    # Depth adjustment: quick = nur top-3 checks
    checks = profile["checks"]
    if depth == "quick" and len(checks) > 3:
        checks = checks[:3]

    return {
        "status": "ready",
        "profile": profile_name,
        "description": profile["description"],
        "checks": checks,
        "task_id": task.get("id") or task.get("task_id", "?"),
        "depth": depth,
    }


def build_review_prompt(
    profile_name: str,
    task: dict,
    files_content: dict[str, str],
    depth: str = "normal",
) -> str:
    """Build the prompt for the delegate_task reviewer subagent.

    The prompt instructs the reviewer to examine the task's files against
    the profile's checks and return a structured JSON verdict.

    Args:
        profile_name: Review profile name
        task: Task dict (must have 'id', 'name')
        files_content: Dict mapping file paths to their content
        depth: Review depth

    Returns:
        String prompt ready for delegate_task().
    """
    profile = get_profile(profile_name)
    checks = profile["checks"]
    if depth == "quick" and len(checks) > 3:
        checks = checks[:3]

    checks_list = "\n".join(f"- [ ] {c}" for c in checks)

    files_section_parts = []
    for path, content in files_content.items():
        if content:
            # Begrenze grosse Dateien auf 500 Zeilen
            lines = content.split("\n")
            if len(lines) > 500:
                content = "\n".join(lines[:500]) + f"\n... (Datei gekürzt, {len(lines)} Zeilen)"
            files_section_parts.append(f"### {path}\n```\n{content}\n```")
    files_section = "\n\n".join(files_section_parts) if files_section_parts else "No files to review."

    task_id = task.get("id") or task.get("task_id", "?")
    return f"""You are an independent code reviewer for task '{task_id}: {task['name']}'.

Review Profile: {profile_name}
Description: {profile['description']}
Depth: {depth}

## Checklist
{checks_list}

## Files to Review
{files_section}

Review each file against the checklist above. For each issue found:
- Identify which check it violates
- Rate severity as 'error' (must fix), 'warning' (should fix), or 'suggestion' (nice to have)
- Provide a specific, actionable description

Return ONLY valid JSON (no markdown, no explanation):
{{
  "passed": true/false,
  "status": "passed"|"failed"|"skipped",
  "issues": [
    {{
      "check": "check_name",
      "severity": "error"|"warning"|"suggestion",
      "message": "Specific description of the issue",
      "file": "path/to/file.ts",
      "line": 42
    }}
  ],
  "summary": "one-sentence verdict of the review"
}}

RULES:
- passed MUST be false if any 'error'-severity issues exist
- passed MUST be false if you cannot parse the files
- An empty issues array with passed=true means clean review
- Be specific: 'missing edge case for empty input on line 15' not 'needs work'
- If files have no issues, return passed=true with an empty issues array"""


def validate_review_result(result: dict) -> dict[str, Any]:
    """Validate a review result dict and normalize it.

    Ensures all required fields are present and types are correct.
    Returns the validated (and possibly cleaned) result.

    Args:
        result: Raw dict from the reviewer (potentially malformed)

    Returns:
        Normalized result with guaranteed fields.
    """
    if not isinstance(result, dict):
        return {
            "passed": False,
            "status": "failed",
            "issues": [{"check": "parse", "severity": "error", "message": "Review result is not a dict"}],
            "summary": "Invalid review result format.",
        }

    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = []

    # Normalize each issue
    normalized_issues = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        normalized_issues.append({
            "check": issue.get("check", "unknown"),
            "severity": issue.get("severity", "warning") if issue.get("severity") in ("error", "warning", "suggestion") else "warning",
            "message": issue.get("message", ""),
            "file": issue.get("file", ""),
            "line": issue.get("line", 0) if isinstance(issue.get("line"), int) else 0,
        })

    has_errors = any(i["severity"] == "error" for i in normalized_issues)

    return {
        "passed": result.get("passed", False) if isinstance(result.get("passed"), bool) else not has_errors,
        "status": result.get("status", "failed") if result.get("status") in ("passed", "failed", "skipped") else ("passed" if not has_errors else "failed"),
        "issues": normalized_issues,
        "summary": str(result.get("summary", "")),
    }

# ─── Auto-Review (gebündelte Vorbereitung) ─────────────────────────────────


def read_task_files(task: dict) -> dict[str, str]:
    """Read all files from a task's file list.

    Supports glob patterns (*.ts, src/**/*.py) and plain paths.
    Non-existent files return empty content silently.

    Args:
        task: Task dict with 'files' list.

    Returns:
        Dict mapping file path → file content (empty string if unreadable).
    """
    import glob as glob_mod

    files_content: dict[str, str] = {}
    for file_pattern in task.get("files", []):
        # Expand glob pattern
        matches = glob_mod.glob(file_pattern, recursive=True)
        if not matches:
            # Try relative to CWD
            matches = glob_mod.glob(str(Path.cwd() / file_pattern), recursive=True)
        if not matches:
            # No matches — try as literal path
            matches = [file_pattern]

        for file_path in matches:
            path = Path(file_path)
            if not path.is_absolute():
                alt = Path.cwd() / file_path
                if alt.exists():
                    path = alt
            if not path.exists():
                files_content[file_path] = ""
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                lines = content.split("\n")
                if len(lines) > 500:
                    content = "\n".join(lines[:500]) + f"\n... (Datei gekürzt, {len(lines)} Zeilen)"
                files_content[str(path)] = content
            except (OSError, IOError) as e:
                files_content[file_path] = f"<Error reading: {e}>"
    return files_content


def has_coverage_checks(profile_name: str) -> bool:
    """Check if a review profile includes coverage-related checks."""
    from .review_profiles import get_profile
    profile = get_profile(profile_name)
    for check in profile.get("checks", []):
        if check.startswith("test_coverage"):
            return True
    return False


def auto_review(
    task: dict,
    plan: Optional[dict] = None,
    profile_name: str = "auto",
    depth: str = "normal",
) -> dict:
    """Bereitet einen kompletten Review in einem Aufruf vor.

    Führt in einem Durchlauf aus:
    1. Profil auflösen (auto → aus task.review_profile)
    2. Task-Dateien lesen
    3. Coverage messen (wenn Profil Coverage-Checks enthält)
    4. Review-Prompt bauen (mit Coverage-Daten als Kontext)

    Args:
        task: Aktueller Task-Dict (mit task_id, files, review_profile, etc.)
        plan: Optional der gesamte Plan (für repo-Infos)
        profile_name: Review-Profil ('auto' = aus Task)
        depth: Review-Tiefe ('quick', 'normal', 'deep')

    Returns:
        Dict mit:
          - status: 'ready', 'coverage_failed', 'skipped', 'error'
          - prompt: fertiger Prompt für delegate_task (nur bei 'ready')
          - coverage: Coverage-Messung (nur bei Profilen mit Coverage-Checks)
          - message: Beschreibung
    """
    try:
        # Profil auflösen
        if profile_name == "auto":
            profile_name = task.get("review_profile", "none")

        if profile_name == "none":
            return {
                "status": "skipped",
                "message": "No review profile set — no review needed.",
            }

        # Task-Dateien lesen
        files_content = read_task_files(task)
        if not files_content:
            return {
                "status": "skipped",
                "message": f"Task '{task.get('task_id', '?')}' has no readable files.",
            }

        # Coverage messen (wenn Profil Coverage-Checks enthält)
        coverage_result = None
        if has_coverage_checks(profile_name):
            from .plan_coverage import get_project_path, measure_coverage

            project_path = get_project_path(task, plan)
            if project_path:
                try:
                    coverage_result = measure_coverage(project_path)
                except Exception as e:
                    coverage_result = {
                        "success": False,
                        "error": f"Coverage measurement error: {e}",
                        "pct": 0.0,
                        "passed": False,
                    }

                if coverage_result and coverage_result.get("success") and not coverage_result["passed"]:
                    return {
                        "status": "coverage_failed",
                        "coverage": coverage_result,
                        "message": (
                            f"Test-Coverage beträgt nur {coverage_result['pct']}%. "
                            f"Benötigt: ≥ {coverage_result['threshold']}%. "
                            "Schreibe mehr Tests bevor der Review fortgesetzt werden kann."
                        ),
                        "suggestion": (
                            "Füge Tests hinzu bis die Coverage ≥ "
                            f"{coverage_result['threshold']}% erreicht. "
                            "Dann erneut plan_auto_review() aufrufen."
                        ),
                        "profile": profile_name,
                    }
            else:
                coverage_result = {
                    "success": False,
                    "error": "Could not determine project path for coverage measurement",
                    "pct": 0.0,
                    "passed": False,
                }

        # Review-Prompt bauen (mit Coverage-Daten als Kontext)
        prompt = build_review_prompt(profile_name, task, files_content, depth)

        return {
            "status": "ready",
            "profile": profile_name,
            "depth": depth,
            "prompt": prompt,
            "files_content": {k: v[:200] for k, v in files_content.items()},
            "coverage": coverage_result,
            "message": "Review bereit. Führe delegate_task(goal=prompt) aus, "
                       "dann save_review_result(task_id, result) für plan_complete().",
        }

    except Exception as e:
        logger.error(f"auto_review failed: {e}")
        return {
            "status": "error",
            "message": f"Auto-review failed: {e}",
        }
