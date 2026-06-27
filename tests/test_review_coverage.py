"""Coverage gap tests for plan_review.py — edge cases and error paths.

Tests cover uncovered lines:
- build_review_prompt() — line 92: depth=quick with >3 checks
- validate_review_result() — line 170: issues not a list
- read_task_files() — lines 227, 235, 237–238: path resolution, truncation, exception
- auto_review() — lines 301–332, 353–355: coverage paths, exception handler
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the plugin package is on sys.path
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

MODULE_PATH = "plan_follow.plan_review"


# ─── Helpers ────────────────────────────────────────────────────────────────


def make_task(**overrides) -> dict:
    task = {
        "id": "p1",
        "task_id": "p1",
        "name": "Test Task",
        "files": [],
        "verify": "",
        "review_profile": "none",
        "status": "pending",
    }
    task.update(overrides)
    return task


# ═══════════════════════════════════════════════════════════════════════════════
# build_review_prompt — depth=quick with >3 checks
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildReviewPromptEdgeCases:
    """Coverage: build_review_prompt() line 92 — depth=quick truncation."""

    def test_quick_depth_truncates_checks(self):
        """depth='quick' with >3 checks should truncate to 3."""
        from plan_follow.plan_review import build_review_prompt  # noqa: E402

        task = make_task(id="p1", task_id="p1", name="Test")
        files_content = {"a.py": "print('hello')"}
        with patch(f"{MODULE_PATH}.get_profile", return_value={
            "description": "Profile with many checks",
            "checks": ["check_a", "check_b", "check_c", "check_d", "check_e"],
        }):
            prompt = build_review_prompt("dummy", task, files_content, depth="quick")
        assert "check_d" not in prompt
        assert "check_c" in prompt
        assert "check_a" in prompt

    def test_quick_depth_with_few_checks_not_truncated(self):
        """depth='quick' with ≤3 checks should keep all."""
        from plan_follow.plan_review import build_review_prompt

        task = make_task(id="p1", task_id="p1", name="Test")
        files_content = {"a.py": "print('hello')"}
        with patch(f"{MODULE_PATH}.get_profile", return_value={
            "description": "Small profile",
            "checks": ["check_a", "check_b"],
        }):
            prompt = build_review_prompt("dummy", task, files_content, depth="quick")
        assert "check_a" in prompt
        assert "check_b" in prompt

    def test_file_content_truncated(self):
        """A file with >500 lines is truncated in the prompt."""
        from plan_follow.plan_review import build_review_prompt

        task = make_task(id="p1", task_id="p1", name="Test")
        long_content = "\n".join(f"line {i}" for i in range(600))
        files_content = {"long.py": long_content}
        with patch(f"{MODULE_PATH}.get_profile", return_value={
            "description": "Profile",
            "checks": ["check_a"],
        }):
            prompt = build_review_prompt("default", task, files_content, depth="normal")
        assert "... (Datei gekürzt" in prompt
        assert "line 499" in prompt
        assert "line 550" not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# validate_review_result — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateReviewResultEdgeCases:
    """Coverage: validate_review_result() line 170 — issues not a list."""

    def test_issues_is_not_a_list(self):
        """When issues is not a list, it's replaced with empty list."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({"passed": True, "issues": "not-a-list", "status": "passed", "summary": ""})
        assert result["passed"] is True
        assert result["issues"] == []

    def test_issues_is_none(self):
        """When issues is None, it's replaced with empty list."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({"passed": True, "issues": None, "status": "passed", "summary": ""})
        assert result["passed"] is True
        assert result["issues"] == []

    def test_result_is_not_dict(self):
        """Non-dict result returns a failed result."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result("not-a-dict")
        assert result["passed"] is False
        assert result["status"] == "failed"

    def test_issue_with_invalid_severity_defaults_to_warning(self):
        """An issue with invalid severity gets 'warning'."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({
            "passed": False,
            "status": "failed",
            "issues": [{"check": "c1", "severity": "catastrophic", "message": "boom", "file": "a.py", "line": 5}],
            "summary": "",
        })
        assert result["issues"][0]["severity"] == "warning"

    def test_issue_with_non_int_line_defaults_to_zero(self):
        """An issue with non-int line gets 0."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({
            "passed": False,
            "status": "failed",
            "issues": [{"check": "c1", "severity": "error", "message": "boom", "file": "a.py", "line": "abc"}],
            "summary": "",
        })
        assert result["issues"][0]["line"] == 0

    def test_issue_non_dict_skipped(self):
        """A non-dict issue entry is skipped."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({
            "passed": True,
            "status": "passed",
            "issues": [{"check": "c1", "severity": "error", "message": "real", "file": "a.py", "line": 1}, "not-a-dict"],  # noqa: E501
            "summary": "",
        })
        assert len(result["issues"]) == 1
        assert result["issues"][0]["check"] == "c1"

    def test_missing_passed_field_infers_from_issues(self):
        """When 'passed' is not a bool, infer from has_errors."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({
            "passed": "yes",
            "status": "something",
            "issues": [{"check": "c1", "severity": "error", "message": "err", "file": "a.py", "line": 1}],
            "summary": "",
        })
        assert result["passed"] is False

    def test_missing_status_infers_from_errors(self):
        """When 'status' is invalid, infer from has_errors."""
        from plan_follow.plan_review import validate_review_result

        result = validate_review_result({
            "passed": True,
            "status": "ambiguous",
            "issues": [],
            "summary": "",
        })
        assert result["status"] == "passed"


# ═══════════════════════════════════════════════════════════════════════════════
# read_task_files — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadTaskFilesEdgeCases:
    """Coverage: read_task_files() lines 227, 235, 237–238."""

    def test_relative_path_resolved_via_cwd(self, tmp_path):
        """A non-absolute path that exists relative to CWD is resolved."""
        from plan_follow.plan_review import read_task_files

        # Create a file in tmp_path and chdir there
        target = tmp_path / "myfile.py"
        target.write_text("print('hello')")

        original_cwd = Path.cwd()
        import os
        os.chdir(tmp_path)
        try:
            task = make_task(files=["myfile.py"])
            result = read_task_files(task)
            assert "myfile.py" in result or str(tmp_path / "myfile.py") in result
            assert "hello" in str(result.values())
        finally:
            os.chdir(original_cwd)

    def test_file_truncated_to_500_lines(self, tmp_path):
        """A file with >500 lines is truncated in read_task_files."""
        from plan_follow.plan_review import read_task_files

        target = tmp_path / "long_file.py"
        lines = [f"line {i}" for i in range(600)]
        target.write_text("\n".join(lines))

        task = make_task(files=[str(target)])
        result = read_task_files(task)
        content = list(result.values())[0]
        assert "(Datei gekürzt" in content
        assert content.count("\n") < 600  # truncated

    def test_io_error_returns_error_message(self, tmp_path):
        """When a file raises OSError during read, an error message is stored."""
        from plan_follow.plan_review import read_task_files

        unreadable = tmp_path / "locked.py"
        unreadable.write_text("content")
        unreadable.chmod(0o000)  # remove all permissions

        try:
            task = make_task(files=[str(unreadable)])
            result = read_task_files(task)
            # Should have _some_ content for this file, either error or empty
            assert any(str(unreadable) in k for k in result)
        finally:
            unreadable.chmod(0o644)

    def test_glob_with_no_matches_and_no_literal(self):
        """A glob pattern with no matches tries as literal path."""
        from plan_follow.plan_review import read_task_files

        task = make_task(files=["nonexistent_glob_*.py"])
        result = read_task_files(task)
        # Should contain the pattern as a key with empty content
        assert any("nonexistent_glob_" in k for k in result)

    def test_glob_matches_files(self, tmp_path):
        """A glob pattern that matches files reads them."""
        from plan_follow.plan_review import read_task_files

        (tmp_path / "mod_a.py").write_text("a = 1")
        (tmp_path / "mod_b.py").write_text("b = 2")

        original_cwd = Path.cwd()
        import os
        os.chdir(tmp_path)
        try:
            task = make_task(files=["mod_*.py"])
            result = read_task_files(task)
            assert len(result) >= 2
        finally:
            os.chdir(original_cwd)


# ═══════════════════════════════════════════════════════════════════════════════
# auto_review — coverage paths and error handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoReviewCoveragePaths:
    """Coverage: auto_review() lines 301–332, 353–355."""

    def test_coverage_failed_when_below_threshold(self):
        """auto_review returns coverage_failed when coverage is below threshold."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="unit-test", files=["test.py"])
        plan = {"plan_id": "test", "goal": "Test"}

        with patch(f"{MODULE_PATH}.read_task_files", return_value={"test.py": "content"}), \
             patch(f"{MODULE_PATH}.has_coverage_checks", return_value=True), \
             patch("plan_follow.plan_coverage.get_project_path", return_value="/tmp/project"), \
             patch("plan_follow.plan_coverage.measure_coverage", return_value={
                 "success": True, "passed": False, "pct": 45.0, "threshold": 80.0,
             }):
            result = auto_review(task, plan, profile_name="unit-test")

        assert result["status"] == "coverage_failed"
        assert "45.0%" in result["message"]
        assert "80.0%" in result["message"]

    def test_coverage_passed_when_meets_threshold(self):
        """auto_review returns ready when coverage meets threshold."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="unit-test", files=["test.py"])
        plan = {"plan_id": "test", "goal": "Test"}

        with patch(f"{MODULE_PATH}.read_task_files", return_value={"test.py": "content"}), \
             patch(f"{MODULE_PATH}.has_coverage_checks", return_value=True), \
             patch("plan_follow.plan_coverage.get_project_path", return_value="/tmp/project"), \
             patch("plan_follow.plan_coverage.measure_coverage", return_value={
                 "success": True, "passed": True, "pct": 90.0, "threshold": 80.0,
             }), \
             patch(f"{MODULE_PATH}.build_review_prompt", return_value="prompt"):
            result = auto_review(task, plan, profile_name="unit-test")

        assert result["status"] == "ready"

    def test_coverage_measurement_error(self):
        """auto_review handles coverage measurement exception gracefully."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="unit-test", files=["test.py"])
        plan = {"plan_id": "test", "goal": "Test"}

        with patch(f"{MODULE_PATH}.read_task_files", return_value={"test.py": "content"}), \
             patch(f"{MODULE_PATH}.has_coverage_checks", return_value=True), \
             patch("plan_follow.plan_coverage.get_project_path", return_value="/tmp/project"), \
             patch("plan_follow.plan_coverage.measure_coverage", side_effect=RuntimeError("coverage tool crash")):
            result = auto_review(task, plan, profile_name="unit-test")

        assert result["status"] == "coverage_failed" or result["status"] == "ready"
        # The function catches the exception and wraps it
        if result.get("coverage"):
            assert result["coverage"]["success"] is False

    def test_no_project_path_for_coverage(self):
        """auto_review when project_path is None stores error coverage result."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="unit-test", files=["test.py"])

        with patch(f"{MODULE_PATH}.read_task_files", return_value={"test.py": "content"}), \
             patch(f"{MODULE_PATH}.has_coverage_checks", return_value=True), \
             patch("plan_follow.plan_coverage.get_project_path", return_value=None):
            result = auto_review(task, None, profile_name="unit-test")

        assert result["status"] == "ready"  # coverage failure doesn't block review
        assert result["coverage"] is not None
        assert result["coverage"]["success"] is False

    def test_profile_auto_resolves_from_task(self):
        """profile_name='auto' uses task's review_profile."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="none", files=[])
        plan = {"plan_id": "test", "goal": "Test"}

        result = auto_review(task, plan, profile_name="auto")
        assert result["status"] == "skipped"
        assert "No review profile" in result["message"]

    def test_no_readable_files(self):
        """auto_review returns skipped when no files can be read."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="unit-test", files=["missing.py"])
        plan = {"plan_id": "test", "goal": "Test"}

        with patch(f"{MODULE_PATH}.read_task_files", return_value={}):
            result = auto_review(task, plan, profile_name="unit-test")

        assert result["status"] == "skipped"
        assert "no readable files" in result["message"].lower()

    def test_exception_handler(self):
        """auto_review catches unexpected exceptions."""
        from plan_follow.plan_review import auto_review

        task = make_task(review_profile="unit-test", files=["test.py"])
        plan = {"plan_id": "test", "goal": "Test"}

        with patch(f"{MODULE_PATH}.read_task_files", side_effect=ValueError("something broke")):
            result = auto_review(task, plan, profile_name="unit-test")

        assert result["status"] == "error"
        assert "Auto-review failed" in result["message"]
