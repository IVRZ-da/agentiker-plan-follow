"""Tests for tools/validation.py — Plan-Validierung."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plan_follow.tools.validation import validate_plan


def _make_plan(overrides: dict = None) -> dict:
    """Basis-Plan mit gueltigen Tasks."""
    plan = {
        "plan_id": "p-test",
        "goal": "Test Plan",
        "tasks": {
            "T001": {"depends_on": [], "verify": "echo ok", "review_profile": "none", "status": "pending"},
            "T002": {"depends_on": ["T001"], "verify": "echo ok2", "review_profile": "unit-test", "status": "pending"},
        },
    }
    if overrides:
        plan.update(overrides)
    return plan


# ─── Basis-Tests ──────────────────────────────────────────────────────────────


class TestValidatePlanBasics:
    """Grundlegende Validierungs-Tests."""

    def test_valid_plan(self):
        """Gueltiger Plan -> valid."""
        with patch("plan_follow.tools.validation._get_active_plan", return_value=_make_plan()):
            result = validate_plan()
        assert result["status"] == "valid"
        assert "summary" in result

    def test_plan_by_id(self):
        """Plan via ID laden."""
        with patch("plan_follow.tools.validation._load_plan", return_value=_make_plan({"plan_id": "p123"})):
            result = validate_plan("p123")
        assert result["status"] == "valid"
        assert result["plan_id"] == "p123"

    def test_plan_by_id_not_found(self):
        """Unbekannte Plan-ID -> error."""
        with patch("plan_follow.tools.validation._load_plan", return_value=None):
            result = validate_plan("unknown")
        assert result["status"] == "error"
        assert "not found" in result["errors"][0]

    def test_no_active_plan(self):
        """Kein aktiver Plan -> error."""
        with patch("plan_follow.tools.validation._get_active_plan", return_value=None):
            result = validate_plan()
        assert result["status"] == "error"
        assert "No active plan" in result["errors"][0]

    def test_depends_on_unknown_task(self):
        """depends_on verweist auf nicht-existente Task -> error."""
        plan = _make_plan()
        plan["tasks"]["T001"]["depends_on"] = ["T999"]
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert result["status"] == "invalid"
        errors_str = " ".join(result.get("errors", []))
        assert "T999" in errors_str

    def test_invalid_status(self):
        """Ungueltiger Status -> error."""
        plan = _make_plan()
        plan["tasks"]["T001"]["status"] = "unknown"
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert result["status"] == "invalid"
        assert any("invalid status" in e for e in result["errors"])


# ─── Verify-Command ───────────────────────────────────────────────────────────


class TestVerifyCommandValidation:
    """Zu kurze verify-Commands -> warning (Coverage Zeile 61)."""

    def test_verify_too_short(self):
        """verify-Command mit < 3 Zeichen -> warning."""
        plan = _make_plan()
        plan["tasks"]["T001"]["verify"] = "ok"
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert "warnings" in result
        assert any("too short" in w for w in result["warnings"])

    def test_empty_verify_is_ok(self):
        """Leerer verify-Command -> keine Warning (wird ignoriert)."""
        plan = _make_plan()
        plan["tasks"]["T001"]["verify"] = ""
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        # Keine Warning wegen verify
        verify_warnings = [w for w in result.get("warnings", []) if "too short" in w]
        assert len(verify_warnings) == 0


# ─── Review-Profile ───────────────────────────────────────────────────────────


class TestReviewProfileValidation:
    """Ungueltige review_profile -> warning (Coverage Zeile 66)."""

    def test_invalid_review_profile(self):
        """review_profile ist weder None noch in valid_profiles -> warning."""
        plan = _make_plan()
        plan["tasks"]["T001"]["review_profile"] = "invalid-profile"
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert "warnings" in result
        assert any("not a valid profile" in w for w in result["warnings"])


# ─── Circular Dependencies ────────────────────────────────────────────────────


class TestCircularDependency:
    """Zyklische Abhaengigkeiten -> error."""

    def test_circular_dep_detected(self):
        """T001->T002, T002->T001 -> circular."""
        plan = _make_plan()
        plan["tasks"]["T001"]["depends_on"] = ["T002"]
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert result["status"] == "invalid"
        assert any("Circular" in e for e in result["errors"])


# ─── Parallel Groups ──────────────────────────────────────────────────────────


class TestParallelGroups:
    """parallel_groups Konsistenz (Coverage Zeile 122-127)."""

    def test_group_task_not_in_tasks(self):
        """parallel_group verweist auf nicht-existente Task -> error."""
        plan = _make_plan()
        plan["parallel_groups"] = {
            "g1": {"tasks": ["T001", "T999"]},
        }
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert result["status"] == "invalid"
        errors_str = " ".join(result.get("errors", []))
        assert "T999" in errors_str

    def test_valid_parallel_groups(self):
        """Alle group-Tasks existieren -> valid."""
        plan = _make_plan()
        plan["parallel_groups"] = {
            "g1": {"tasks": ["T001", "T002"]},
        }
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert result["status"] == "valid"


# ─── Git Branch Convention ────────────────────────────────────────────────────


class TestGitBranchCheck:
    """Git-Branch-Naming Convention Check (Coverage Zeile 142-165)."""

    def _git_mock(self, branch_name: str, returncode: int = 0):
        """Helfer: git rev-parse Mock."""
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = branch_name
        return proc

    def test_branch_ok_on_main(self):
        """main branch -> kein warning."""
        plan = _make_plan({"repo": "/tmp"})
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            with patch("subprocess.run", return_value=self._git_mock("main")):
                with patch("os.path.isdir", return_value=True):
                    result = validate_plan()
        branch_warnings = [w for w in result.get("warnings", []) if "Branch" in w]
        assert len(branch_warnings) == 0

    def test_branch_ok_on_feature(self):
        """feat/xyz branch -> kein warning."""
        plan = _make_plan({"repo": "/tmp"})
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            with patch("subprocess.run", return_value=self._git_mock("feat/new-feature")):
                with patch("os.path.isdir", return_value=True):
                    result = validate_plan()
        branch_warnings = [w for w in result.get("warnings", []) if "Branch" in w]
        assert len(branch_warnings) == 0

    def test_branch_invalid_convention(self):
        """branch ohne Prefix -> warning (Coverage Zeile 158-161)."""
        plan = _make_plan({"repo": "/tmp"})
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            with patch("subprocess.run", return_value=self._git_mock("random-branch")):
                with patch("os.path.isdir", return_value=True):
                    result = validate_plan()
        assert "warnings" in result
        assert any("doesn't follow convention" in w for w in result["warnings"])

    def test_branch_check_uses_repos_list(self):
        """repos Liste wird statt single repo verwendet (Coverage Zeile 142)."""
        plan = _make_plan({"repos": ["/tmp/a", "/tmp/b"], "repo": "/single"})
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            with patch("subprocess.run", return_value=self._git_mock("main")):
                with patch("os.path.isdir", return_value=True):
                    result = validate_plan()
        assert result["status"] == "valid"

    def test_branch_check_skips_non_git_dir(self):
        """Verzeichnis ohne .git -> skipped (Coverage Zeile 147-148)."""
        plan = _make_plan({"repo": "/not-a-repo"})
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            with patch("os.path.isdir", return_value=False):
                result = validate_plan()
        assert result["status"] == "valid"

    def test_branch_check_exception(self):
        """subprocess.run wirft Exception -> non-blocking (Coverage Zeile 163-164)."""
        plan = _make_plan({"repo": "/tmp"})
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            with patch("subprocess.run", side_effect=OSError("git failed")):
                with patch("os.path.isdir", return_value=True):
                    result = validate_plan()
        assert result["status"] == "valid"
        assert result["status"] == "valid"


# ─── Warnings ohne Errors ─────────────────────────────────────────────────────


class TestWarningsWithoutErrors:
    """Warnings existieren, aber keine Errors -> status bleibt valid (Coverage Zeile 170)."""

    def test_warnings_without_errors(self):
        """Warning wegen kurzem verify-Command, keine Errors -> valid."""
        plan = _make_plan()
        plan["tasks"]["T001"]["verify"] = "ok"
        with patch("plan_follow.tools.validation._get_active_plan", return_value=plan):
            result = validate_plan()
        assert result["status"] == "valid"
        assert "warnings" in result
