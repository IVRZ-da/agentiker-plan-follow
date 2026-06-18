"""
plan_review.py — Review-Dispatch-Logik für das plan_follow Plugin.

Stellt die Verbindung zwischen Review-Profilen und der unabhängigen
Code-Review-Prüfung her. Enthält:
  - dispatch_review(): Bereitet Review-Daten auf (task, files, profile)
  - build_review_prompt(): Baut den Prompt für den delegate_task Reviewer
  - validate_review_result(): Validiert das JSON-Verdict des Reviewers
"""

from __future__ import annotations

from typing import Any

from .review_profiles import get_profile


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
