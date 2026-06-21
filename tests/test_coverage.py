"""Tests for plan_coverage.py — Coverage measurement & mutation testing."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Helper: side_effect for two-step subprocess calls ──────────────────────
# All measure_coverage tests now need TWO subprocess calls:
#   1. pytest --cov --version check (must succeed)
#   2. Actual coverage measurement

_COV_CHECK_OK = MagicMock(returncode=0, stdout="pytest-cov 4.1.0\n", stderr="")
_COV_CHECK_FAIL = MagicMock(returncode=1, stdout="", stderr="usage: pytest [options] ...")


def _with_cov_check(second_result, check_ok=True):
    """Build side_effect list: [cov_check, second_call_result]."""
    return [_COV_CHECK_OK if check_ok else _COV_CHECK_FAIL, second_result]


# ─── get_project_from_files ───────────────────────────────────────────────────

class TestGetProjectFromFiles:
    def test_empty_files(self):
        from plan_follow.plan_coverage import get_project_from_files
        assert get_project_from_files([]) is None

    def test_nonexistent_path(self):
        from plan_follow.plan_coverage import get_project_from_files
        result = get_project_from_files(["/nonexistent_dir_xyz/file.py"])
        assert result is None

    def test_finds_marker_in_parent(self, tmp_path):
        from plan_follow.plan_coverage import get_project_from_files
        subdir = tmp_path / "src" / "lib"
        subdir.mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text("")
        test_file = subdir / "module.py"
        test_file.write_text("x = 1")
        result = get_project_from_files([str(test_file)])
        assert result == str(tmp_path)

    def test_finds_git_marker(self, tmp_path):
        from plan_follow.plan_coverage import get_project_from_files
        (tmp_path / ".git").mkdir()
        test_file = tmp_path / "code.py"
        test_file.write_text("")
        result = get_project_from_files([str(test_file)])
        assert result == str(tmp_path)

    def test_first_existing_parent(self, tmp_path):
        from plan_follow.plan_coverage import get_project_from_files
        subdir = tmp_path / "app"
        subdir.mkdir()
        (tmp_path / "package.json").write_text("{}")
        result = get_project_from_files([str(subdir / "missing.py")])
        assert result == str(tmp_path)


# ─── get_project_path ─────────────────────────────────────────────────────────

class TestGetProjectPath:
    def test_from_coverage_path(self, tmp_path):
        from plan_follow.plan_coverage import get_project_path
        task = {"coverage_path": str(tmp_path)}
        result = get_project_path(task)
        assert result == str(tmp_path.resolve())

    def test_from_project_field(self, tmp_path):
        from plan_follow.plan_coverage import get_project_path
        task = {"project": str(tmp_path)}
        result = get_project_path(task)
        assert result == str(tmp_path.resolve())

    def test_from_plan_repo(self, tmp_path):
        from plan_follow.plan_coverage import get_project_path
        (tmp_path / "code.py").write_text("")
        (tmp_path / "pyproject.toml").write_text("")
        task = {"files": [str(tmp_path / "code.py")]}
        plan = {"repo": str(tmp_path)}
        result = get_project_path(task, plan)
        assert result == str(tmp_path.resolve())

    def test_from_plan_repos(self, tmp_path):
        from plan_follow.plan_coverage import get_project_path
        (tmp_path / "code.py").write_text("")
        (tmp_path / "pyproject.toml").write_text("")
        task = {"files": [str(tmp_path / "code.py")]}
        plan = {"repos": [str(tmp_path)]}
        result = get_project_path(task, plan)
        assert result == str(tmp_path.resolve())

    def test_from_files(self, tmp_path):
        from plan_follow.plan_coverage import get_project_path
        subdir = tmp_path / "src"
        subdir.mkdir()
        (tmp_path / "pyproject.toml").write_text("")
        f = subdir / "mod.py"
        f.write_text("")
        task = {"files": [str(f)]}
        result = get_project_path(task)
        assert result == str(tmp_path.resolve())

    def test_coverage_path_not_exists(self):
        from plan_follow.plan_coverage import get_project_path
        task = {"coverage_path": "/nonexistent"}
        result = get_project_path(task)
        assert result is not None


# ─── measure_coverage ─────────────────────────────────────────────────────────

class TestMeasureCoverage:
    def test_project_path_not_exists(self):
        from plan_follow.plan_coverage import measure_coverage
        result = measure_coverage("/nonexistent_project", threshold=80.0)
        assert result["success"] is False
        assert "does not exist" in result["error"]
        assert result["pct"] == 0.0

    def test_no_test_dir(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        project = tmp_path / "project"
        project.mkdir()
        (project / "pyproject.toml").write_text("")
        result = measure_coverage(str(project), threshold=80.0)
        assert result["success"] is False
        assert "No test directory found" in result["error"]

    def test_test_dir_not_exists(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        result = measure_coverage(str(tmp_path), test_path="/nonexistent/tests", threshold=80.0)
        assert result["success"] is False
        assert "does not exist" in result["error"]

    def test_subprocess_success_with_json(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("")

        fake_cov_data = {
            "totals": {"percent_covered": 87.5, "covered_lines": 42, "num_statements": 48},
            "files": {
                "src/main.py": {"summary": {"percent_covered": 75.0, "missing_lines": 4}},
                "src/utils.py": {"summary": {"percent_covered": 100.0, "missing_lines": 0}},
            },
        }

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir") as mock_chdir, \
             patch("plan_follow.plan_coverage.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/cov_test.json"
            mock_run.side_effect = _with_cov_check(
                MagicMock(returncode=0, stdout="OK", stderr="")
            )

            def fake_chdir(path):
                cov_file = os.path.join(path, "coverage.json")
                with open(cov_file, "w") as f:
                    json.dump(fake_cov_data, f)

            mock_chdir.side_effect = fake_chdir

            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is True
        assert result["pct"] == 87.5
        assert result["passed"] is True
        assert result["total"] == 48

    def test_subprocess_below_threshold(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("")

        fake_cov_data = {
            "totals": {"percent_covered": 45.0, "covered_lines": 20, "num_statements": 50},
            "files": {},
        }

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir") as mock_chdir, \
             patch("plan_follow.plan_coverage.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/cov_test.json"
            mock_run.side_effect = _with_cov_check(
                MagicMock(returncode=0, stdout="OK", stderr="")
            )

            def fake_chdir(path):
                cov_file = os.path.join(path, "coverage.json")
                with open(cov_file, "w") as f:
                    json.dump(fake_cov_data, f)

            mock_chdir.side_effect = fake_chdir

            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is True
        assert result["passed"] is False
        assert result["pct"] == 45.0

    def test_subprocess_timeout(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()
        subprocess_mod = __import__("subprocess")

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            mock_run.side_effect = _with_cov_check(
                subprocess_mod.TimeoutExpired("cmd", 120)
            )
            result = measure_coverage(str(tmp_path), timeout=120)

        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_subprocess_exception(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            mock_run.side_effect = _with_cov_check(
                RuntimeError("Unexpected error")
            )
            result = measure_coverage(str(tmp_path), timeout=120)

        assert result["success"] is False
        assert "Unexpected error" in result["error"]

    def test_stdout_parse_fallback(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("")

        stdout_output = (
            "tests/test_main.py ..                                                  [100%]\n"
            "\n"
            "---------- coverage: platform linux, python 3.13.5-final-0 -----------\n"
            "Name                  Stmts   Miss  Cover   Missing\n"
            "---------------------------------------------------\n"
            "src/main.py              20      5    75%   10-15\n"
            "src/utils.py             10      0   100%\n"
            "---------------------------------------------------\n"
            "TOTAL                    30      5    25     83%\n"
        )

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"), \
             patch("plan_follow.plan_coverage.tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("plan_follow.plan_coverage.os.path.exists") as mock_exists:
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/cov_test.json"
            mock_run.side_effect = _with_cov_check(
                MagicMock(returncode=0, stdout=stdout_output, stderr="")
            )
            mock_exists.side_effect = lambda p: p == os.path.join(str(tmp_path), "coverage.json") and False or \
                                                p == os.path.join(str(tmp_path), ".coverage") and False

            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is True
        assert result["pct"] == 83.0
        assert result["passed"] is True

    def test_no_data_parse_possible(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"), \
             patch("plan_follow.plan_coverage.tempfile.NamedTemporaryFile") as mock_tmp, \
             patch("plan_follow.plan_coverage.os.path.exists") as mock_exists:
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/cov_test.json"
            mock_run.side_effect = _with_cov_check(
                MagicMock(returncode=0, stdout="No tests collected", stderr="")
            )
            mock_exists.return_value = False
            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is False
        assert "Could not parse" in result["error"]

    def test_corrupt_coverage_json(self, tmp_path):
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir") as mock_chdir:
            mock_run.side_effect = _with_cov_check(
                MagicMock(returncode=0, stdout="OK", stderr="")
            )

            def fake_chdir(path):
                cov_file = os.path.join(path, "coverage.json")
                with open(cov_file, "w") as f:
                    f.write("{corrupt json")

            mock_chdir.side_effect = fake_chdir

            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is False

    # ─── New: pytest-cov fallback tests ──────────────────────────────────────

    def test_pytest_cov_not_installed(self, tmp_path):
        """pytest-cov check fails → graceful error."""
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            mock_run.side_effect = _with_cov_check(
                MagicMock(returncode=0, stdout="OK", stderr=""),
                check_ok=False,  # cov check fails
            )
            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is False
        assert "pytest-cov" in result.get("error", "")
        assert result["pct"] == 0.0

    def test_pytest_cov_check_timeout(self, tmp_path):
        """pytest-cov version check times out."""
        from plan_follow.plan_coverage import measure_coverage
        (tmp_path / "tests").mkdir()
        subprocess_mod = __import__("subprocess")

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            # First call (cov check) times out
            mock_run.side_effect = [
                subprocess_mod.TimeoutExpired("pytest --cov --version", 10),
            ]
            result = measure_coverage(str(tmp_path), threshold=80.0)

        assert result["success"] is False
        assert "nicht verfügbar" in result.get("error", "")


# ─── run_mutation_testing ─────────────────────────────────────────────────────

class TestRunMutationTesting:
    def test_mutmut_not_available(self):
        from plan_follow.plan_coverage import run_mutation_testing
        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            result = run_mutation_testing("/tmp")
        assert result["available"] is False
        assert "nicht installiert" in result["error"]

    def test_mutmut_bad_returncode(self):
        from plan_follow.plan_coverage import run_mutation_testing
        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = run_mutation_testing("/tmp")
        assert result["available"] is False
        assert "nicht installiert" in result["error"]

    def test_mutmut_success(self, tmp_path):
        from plan_follow.plan_coverage import run_mutation_testing
        mutmut_output = (
            "mutmut 3.2.0\n"
            "- Mutation: 'killed' by test_foo\n"
            "- Mutation: 'survived'\n"
            "- Mutation: 'killed' by test_bar\n"
            "Results: 2 killed, 1 survived\n"
        )
        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="mutmut 3.2.0\n", stderr=""),
                MagicMock(returncode=0, stdout=mutmut_output, stderr=""),
            ]
            result = run_mutation_testing(str(tmp_path))
        assert result["available"] is True
        assert result["success"] is True
        assert result["killed"] >= 1

    def test_mutmut_timeout(self, tmp_path):
        from plan_follow.plan_coverage import run_mutation_testing
        subprocess_mod = __import__("subprocess")
        mock_version = MagicMock(returncode=0, stdout="mutmut 3.2.0\n", stderr="")

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            mock_run.side_effect = [
                mock_version,
                subprocess_mod.TimeoutExpired("cmd", 300),
            ]
            result = run_mutation_testing(str(tmp_path))
        assert result["available"] is True
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_mutmut_exception(self, tmp_path):
        from plan_follow.plan_coverage import run_mutation_testing
        mock_version = MagicMock(returncode=0, stdout="mutmut 3.2.0\n", stderr="")

        with patch("plan_follow.plan_coverage.subprocess.run") as mock_run, \
             patch("plan_follow.plan_coverage.os.chdir"):
            mock_run.side_effect = [
                mock_version,
                RuntimeError("Something broke"),
            ]
            result = run_mutation_testing(str(tmp_path))
        assert result["available"] is True
        assert result["success"] is False
        assert "Something broke" in result["error"]
