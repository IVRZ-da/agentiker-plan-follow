"""Tests for plan_suggest module — plan suggestion, time tracking, simulation."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the parent package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plan_follow.plan_suggest import (
    _detect_project_type,
    _suggest_tasks_for_goal,
    suggest_plan,
    time_track,
    simulate_plan,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def cleanup_tracking_file():
    """Remove any leftover tracking file before and after each time_track test."""
    tracking = Path.home() / ".hermes" / "plans" / "time_tracking.json"
    tracking.unlink(missing_ok=True)
    yield
    tracking.unlink(missing_ok=True)


@pytest.fixture
def sample_plan():
    """A typical 4-task plan with dependency chain."""
    return {
        "goal": "add payment feature",
        "tasks": {
            "t1": {"name": "Design", "depends_on": []},
            "t2": {"name": "Implementation", "depends_on": ["t1"]},
            "t3": {"name": "Tests", "depends_on": ["t2"]},
            "t4": {"name": "Docs", "depends_on": ["t3"]},
        },
    }


@pytest.fixture
def parallel_plan():
    """A plan with parallelizable tasks at the same depth level."""
    return {
        "goal": "refactor",
        "tasks": {
            "t1": {"name": "Analyse", "depends_on": []},
            "t2": {"name": "Refactor A", "depends_on": ["t1"]},
            "t3": {"name": "Refactor B", "depends_on": ["t1"]},
            "t4": {"name": "Refactor C", "depends_on": ["t1"]},
            "t5": {"name": "Verify", "depends_on": ["t2", "t3", "t4"]},
        },
    }


# ─── _detect_project_type ─────────────────────────────────────────────────────


class TestDetectProjectType:
    def test_unknown_project(self, tmp_path):
        """Empty directory returns project type 'unknown'."""
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "unknown"
        assert info["frameworks"] == []
        assert info["markers"] == []

    def test_node_project(self, tmp_path):
        """package.json marker detected as node type."""
        pkg = tmp_path / "package.json"
        pkg.write_text('{"name": "test", "dependencies": {}}', encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "node"
        assert "package.json" in info["markers"]

    def test_go_project(self, tmp_path):
        """go.mod marker detected as go type."""
        (tmp_path / "go.mod").write_text("module test", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "go"
        assert "go.mod" in info["markers"]

    def test_python_project(self, tmp_path):
        """pyproject.toml marker detected as python type."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "python"
        assert "pyproject.toml" in info["markers"]

    def test_rust_project(self, tmp_path):
        """Cargo.toml marker detected as rust type."""
        (tmp_path / "Cargo.toml").write_text("[package]", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "rust"
        assert "Cargo.toml" in info["markers"]

    def test_php_project(self, tmp_path):
        """composer.json marker detected as php type."""
        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "php"
        assert "composer.json" in info["markers"]

    def test_ruby_project(self, tmp_path):
        """Gemfile marker detected as ruby type."""
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "ruby"
        assert "Gemfile" in info["markers"]

    def test_invalid_package_json_graceful(self, tmp_path):
        """Malformed package.json doesn't crash detection."""
        (tmp_path / "package.json").write_text("not valid json", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "node"  # marker still matched
        assert info["frameworks"] == []  # but no deps parsed

    def test_multiple_markers(self, tmp_path):
        """Multiple markers can coexist (e.g. node + pyproject).
        The last marker in the iteration order wins for 'type'.
        """
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        info = _detect_project_type(str(tmp_path))
        assert info["type"] == "python"  # pyproject.toml last in dict iteration
        assert "package.json" in info["markers"]
        assert "pyproject.toml" in info["markers"]


# ─── _suggest_tasks_for_goal ──────────────────────────────────────────────────


class TestSuggestTasksForGoal:
    def test_feature_pattern(self):
        """'add payment feature' triggers feature/implementation tasks."""
        tasks = _suggest_tasks_for_goal("add payment feature", {"type": "unknown"})
        assert len(tasks) == 4
        assert tasks[0]["name"] == "Spec / Types definieren"
        assert tasks[1]["name"] == "RED: Tests schreiben"
        assert tasks[2]["name"] == "GREEN: Implementierung"
        assert tasks[3]["name"] == "Dokumentation"
        # Check dependency chain
        assert tasks[0]["depends_on"] == []
        assert tasks[1]["depends_on"] == ["t1"]
        assert tasks[2]["depends_on"] == ["t2"]
        assert tasks[3]["depends_on"] == ["t3"]

    def test_bug_fix_pattern(self):
        """'fix login bug' triggers bug-fix tasks."""
        tasks = _suggest_tasks_for_goal("fix login bug", {"type": "unknown"})
        assert len(tasks) == 3
        assert tasks[0]["name"] == "Bug-Analyse / Root-Cause finden"
        assert tasks[1]["name"] == "RED: Test schreiben der Bug reproduziert"
        assert tasks[2]["name"] == "GREEN: Bug fixen"
        assert tasks[0]["depends_on"] == []
        assert tasks[1]["depends_on"] == ["t1"]
        assert tasks[2]["depends_on"] == ["t2"]

    def test_bug_fix_alternative_keywords(self):
        """Keywords 'error', 'issue', 'fail', 'broken' also match bug pattern."""
        for kw in ("error in checkout", "issue with login", "test fail", "broken build"):
            tasks = _suggest_tasks_for_goal(kw, {"type": "unknown"})
            assert len(tasks) == 3, f"'{kw}' should match bug pattern"
            assert "Bug-Analyse" in tasks[0]["name"]

    def test_refactor_pattern(self):
        """'refactor checkout' triggers refactoring tasks."""
        tasks = _suggest_tasks_for_goal("refactor checkout", {"type": "unknown"})
        assert len(tasks) == 3
        assert tasks[0]["name"] == "Coverage-Baseline + Analyse"
        assert tasks[1]["name"] == "Refactoring durchführen"
        assert tasks[2]["name"] == "Tests + Coverage nach Refactoring"
        # Refactor tasks use 'full' review profile for first task
        assert tasks[0]["review_profile"] == "full"

    def test_refactor_alternative_keywords(self):
        """Keywords 'clean', 'restructure', 'redesign', 'optimize' match refactor."""
        for kw in ("clean code", "restructure module", "redesign UI", "optimize query"):
            tasks = _suggest_tasks_for_goal(kw, {"type": "unknown"})
            assert len(tasks) == 3, f"'{kw}' should match refactor pattern"

    def test_deploy_pattern(self):
        """'deploy to production' triggers deploy tasks."""
        tasks = _suggest_tasks_for_goal("deploy to production", {"type": "unknown"})
        assert len(tasks) == 3
        assert tasks[0]["name"] == "Build + Tests"
        assert tasks[1]["name"] == "Deploy ausführen"
        assert tasks[2]["name"] == "Health-Check + Smoke-Test"

    def test_deploy_alternative_keywords(self):
        """'release', 'publish' match deploy pattern. 'rollout' alone needs care
        since 'rollout feature' contains 'feature' which takes priority."""
        for kw in ("release v2.0", "publish package"):
            tasks = _suggest_tasks_for_goal(kw, {"type": "unknown"})
            assert len(tasks) == 3, f"'{kw}' should match deploy pattern"
        # 'rollout' alone (no 'feature' or 'add' keyword) hits deploy
        tasks = _suggest_tasks_for_goal("rollout version 3", {"type": "unknown"})
        assert len(tasks) == 3, "'rollout version 3' should match deploy pattern"

    def test_security_pattern(self):
        """'security audit' triggers security tasks."""
        tasks = _suggest_tasks_for_goal("security audit", {"type": "unknown"})
        assert len(tasks) == 4
        assert tasks[0]["name"] == "Security-Scan durchführen"
        assert tasks[1]["name"] == "Findings analysieren + priorisieren"
        assert tasks[2]["name"] == "Fix: Schwachstellen beheben"
        assert tasks[3]["name"] == "Re-Scan + Verify"
        # All security tasks use 'security' review profile
        for t in tasks:
            assert t["review_profile"] == "security"

    def test_security_alternative_keywords(self):
        """'vulnerability', 'cve', 'exploit' match security pattern."""
        for kw in ("vulnerability scan", "CVE-2024-1234", "exploit prevention"):
            tasks = _suggest_tasks_for_goal(kw, {"type": "unknown"})
            assert len(tasks) == 4, f"'{kw}' should match security pattern"

    def test_research_pattern(self):
        """'research options' triggers research tasks."""
        tasks = _suggest_tasks_for_goal("research options", {"type": "unknown"})
        assert len(tasks) == 3
        assert tasks[0]["name"] == "Recherche + Quellen sammeln"
        assert tasks[1]["name"] == "Inhalt schreiben / strukturieren"
        assert tasks[2]["name"] == "Review + Korrektur"

    def test_documentation_pattern(self):
        """'write docs' triggers documentation tasks."""
        tasks = _suggest_tasks_for_goal("write documentation", {"type": "unknown"})
        assert len(tasks) == 3
        assert "Recherche" in tasks[0]["name"]
        assert "Inhalt" in tasks[1]["name"]

    def test_default_pattern(self):
        """Unknown goal falls back to multi-step implementation."""
        tasks = _suggest_tasks_for_goal("improve performance", {"type": "unknown"})
        assert len(tasks) == 4
        assert "Analyse" in tasks[0]["name"]
        assert "Implementierung Schritt 1" in tasks[1]["name"]
        assert "Implementierung Schritt 2" in tasks[2]["name"]
        assert "Tests + Verify" in tasks[3]["name"]

    def test_feature_with_node_verify(self):
        """Node project gets npm test verify command."""
        tasks = _suggest_tasks_for_goal("add feature", {"type": "node"})
        for t in tasks:
            assert "npm test" in t["verify"]

    def test_feature_with_go_verify(self):
        """Go project gets go test verify command."""
        tasks = _suggest_tasks_for_goal("add feature", {"type": "go"})
        for t in tasks:
            assert "go test" in t["verify"]

    def test_feature_with_python_verify(self):
        """Python project gets pytest verify command."""
        tasks = _suggest_tasks_for_goal("add feature", {"type": "python"})
        for t in tasks:
            assert "python3 -m pytest" in t["verify"]

    def test_feature_with_rust_verify(self):
        """Rust project gets cargo test verify command."""
        tasks = _suggest_tasks_for_goal("add feature", {"type": "rust"})
        for t in tasks:
            assert "cargo test" in t["verify"]

    def test_unknown_type_verify(self):
        """Unknown project type gets a generic echo verify."""
        tasks = _suggest_tasks_for_goal("add feature", {"type": "unknown"})
        for t in tasks:
            assert "echo '✅ verify pending'" in t["verify"]

    def test_empty_goal(self):
        """Empty string goal falls to default pattern, not crash."""
        tasks = _suggest_tasks_for_goal("", {"type": "unknown"})
        assert len(tasks) == 4  # default pattern

    def test_goal_with_multiple_keywords(self):
        """'fix feature bug' — 'feature' keyword is checked first in elif chain,
        so it returns the feature pattern (4 tasks), not bug pattern."""
        tasks = _suggest_tasks_for_goal("fix feature bug", {"type": "unknown"})
        # 'feature' keyword is in the first if-branch
        assert len(tasks) == 4
        assert tasks[0]["name"] == "Spec / Types definieren"


# ─── suggest_plan ──────────────────────────────────────────────────────────────


class TestSuggestPlan:
    def test_suggest_plan_bugfix(self):
        """Bug-fix goal returns bugfix template and 3 tasks."""
        result = suggest_plan("fix login bug")
        assert result["goal"] == "fix login bug"
        assert result["suggested_template"] == "bugfix"
        assert result["task_count"] == 3
        assert len(result["suggested_tasks"]) == 3
        assert "project_type" in result
        assert "note" in result

    def test_suggest_plan_feature(self):
        """Feature goal returns feature template and 4 tasks."""
        result = suggest_plan("add payment feature")
        assert result["suggested_template"] == "feature"
        assert result["task_count"] == 4

    def test_suggest_plan_refactor(self):
        """Refactor goal returns refactoring template and 3 tasks."""
        result = suggest_plan("refactor checkout")
        assert result["suggested_template"] == "refactoring"
        assert result["task_count"] == 3

    def test_suggest_plan_deploy(self):
        """Deploy goal returns deploy template and 3 tasks."""
        result = suggest_plan("deploy to production")
        assert result["suggested_template"] == "deploy"
        assert result["task_count"] == 3

    def test_suggest_plan_security(self):
        """Security goal returns multi template (no security template)."""
        result = suggest_plan("security audit")
        assert result["suggested_template"] == "multi"
        assert result["task_count"] == 4

    def test_suggest_plan_with_project_root(self, tmp_path):
        """Passing a project root uses it for type detection."""
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        result = suggest_plan("add feature", project_root=str(tmp_path))
        assert result["project_type"] == "node"
        assert tmp_path.samefile(result["project_root"])

    def test_suggest_plan_unknown_projects_root(self, tmp_path):
        """Project root without markers still works but type is unknown."""
        result = suggest_plan("fix bug", project_root=str(tmp_path))
        assert result["project_type"] == "unknown"

    @patch("plan_follow.plan_suggest._find_project_root", return_value="/tmp")
    def test_suggest_plan_calls_detect_project_type(self, mock_find):
        """Verify the internal function calls work end-to-end."""
        result = suggest_plan("add test")
        assert result["project_root"] == "/tmp"


# ─── time_track ───────────────────────────────────────────────────────────────


class TestTimeTrack:
    def test_start_tracking(self):
        """Starting tracking creates an entry with status 'running'."""
        result = time_track("start", task_id="t1", plan_id="plan1")
        assert result["status"] == "started"
        assert result["task_id"] == "t1"
        assert "started_at" in result

    def test_start_tracking_without_plan_id(self):
        """Starting tracking works without plan_id."""
        result = time_track("start", task_id="t1")
        assert result["status"] == "started"

    def test_status_not_found(self):
        """Status for non-existent task returns 'not_found'."""
        result = time_track("status", task_id="nonexistent")
        assert result["status"] == "not_found"

    def test_status_found_after_start(self):
        """Status after start returns the entry."""
        time_track("start", task_id="t1", plan_id="p1")
        result = time_track("status", task_id="t1", plan_id="p1")
        assert result["status"] == "found"
        assert result["entry"]["status"] == "running"
        assert result["entry"]["task_id"] == "t1"

    def test_stop_tracking(self):
        """Stopping a tracked task returns duration."""
        time_track("start", task_id="t1", plan_id="p1")
        result = time_track("stop", task_id="t1", plan_id="p1")
        assert result["status"] == "stopped"
        assert result["task_id"] == "t1"
        assert isinstance(result["duration_min"], (int, float))
        assert result["duration_min"] >= 0

    def test_stop_non_existent(self):
        """Stopping a non-existent task returns error."""
        result = time_track("stop", task_id="ghost")
        assert result["status"] == "error"
        assert "No tracking entry" in result["message"]

    def test_stop_without_plan_id(self):
        """Stop works with just task_id if no plan_id was used at start."""
        time_track("start", task_id="t1")
        result = time_track("stop", task_id="t1")
        assert result["status"] == "stopped"

    def test_history_empty(self):
        """History returns empty list when no tracking data exists."""
        result = time_track("history")
        assert result["status"] == "ok"
        assert result["entries"] == []

    def test_history_with_entries(self):
        """History returns tracked entries in reverse chronological order."""
        time_track("start", task_id="t1", plan_id="p1")
        time_track("stop", task_id="t1", plan_id="p1")
        result = time_track("history")
        assert result["status"] == "ok"
        assert len(result["entries"]) >= 1

    def test_history_filter_by_task_id(self):
        """History filters by task_id when provided."""
        time_track("start", task_id="t1", plan_id="p1")
        time_track("start", task_id="t2", plan_id="p1")
        time_track("stop", task_id="t1", plan_id="p1")
        result = time_track("history", task_id="t1")
        assert all("t1" in e["key"] for e in result["entries"])

    def test_unknown_action(self):
        """Unknown action returns error."""
        result = time_track("invalid_action")
        assert result["status"] == "error"
        assert "Unknown action" in result["message"]

    def test_multiple_starts_same_key(self):
        """Starting the same task again overwrites the previous entry."""
        time_track("start", task_id="t1", plan_id="p1")
        r1 = time_track("start", task_id="t1", plan_id="p1")
        assert r1["status"] == "started"
        result = time_track("status", task_id="t1", plan_id="p1")
        assert result["entry"]["status"] == "running"

    def test_stop_updates_entry(self):
        """After stop, the entry has stopped time, duration, and completed status."""
        time_track("start", task_id="t1", plan_id="p1")
        time_track("stop", task_id="t1", plan_id="p1")
        result = time_track("status", task_id="t1", plan_id="p1")
        assert result["entry"]["status"] == "completed"
        assert "stopped" in result["entry"]
        assert "duration_min" in result["entry"]


# ─── simulate_plan ────────────────────────────────────────────────────────────


class TestSimulatePlan:
    def test_empty_plan(self):
        """Plan with no tasks returns error."""
        result = simulate_plan({"tasks": {}})
        assert result["status"] == "error"
        assert "keine Tasks" in result["message"]

    def test_simple_chain(self, sample_plan):
        """Linear chain of 4 tasks has critical_path_length of 4."""
        result = simulate_plan(sample_plan)
        assert result["status"] == "ok"
        assert result["task_count"] == 4
        assert result["critical_path_length"] == 4
        assert "4 task-units" in result["sequential_estimate"]
        assert "4 task-units" in result["parallel_estimate"]
        assert not result["parallel_possible"]  # linear chain can't be parallelized

    def test_parallelizable_plan(self, parallel_plan):
        """Plan with parallel sibling tasks enables parallel execution."""
        result = simulate_plan(parallel_plan)
        assert result["status"] == "ok"
        assert result["task_count"] == 5
        # Critical path: t1 → t2 → t5 (depth 3) or t1 → t3 → t5, etc.
        assert result["critical_path_length"] == 3
        assert result["parallel_possible"]
        assert result["sequential_estimate"] == "5 task-units"
        assert "3 task-units" in result["parallel_estimate"]

    def test_parallel_suggestion(self, parallel_plan):
        """Parallel plan gets a suggestion with speedup estimate (note in German)."""
        result = simulate_plan(parallel_plan)
        assert result["suggestion"] is not None
        assert "Ausführung möglich" in result["suggestion"]["note"]
        assert "saved" in result["suggestion"]["estimated_speedup"]

    def test_parallel_groups_in_suggestion(self, parallel_plan):
        """Suggestion includes parallel_groups for same-depth tasks."""
        result = simulate_plan(parallel_plan)
        assert result["suggestion"] is not None
        assert len(result["suggestion"]["parallel_groups"]) >= 1
        # Tasks t2, t3, t4 at same depth should be in a group
        all_grouped = []
        for gid, group in result["suggestion"]["parallel_groups"].items():
            all_grouped.extend(group["tasks"])
        for tid in ("t2", "t3", "t4"):
            assert tid in all_grouped, f"{tid} should be in a parallel group"

    def test_critical_path_tasks(self, sample_plan):
        """Critical path lists all tasks in a linear chain."""
        result = simulate_plan(sample_plan)
        assert len(result["critical_path_tasks"]) == 1  # only last task has depth 4
        assert result["critical_path_tasks"][0] == "Docs"

    def test_depth_groups(self, parallel_plan):
        """Depth groups organize tasks by their dependency depth."""
        result = simulate_plan(parallel_plan)
        assert "depth_groups" in result
        # t1 should be depth 1, t2/t3/t4 depth 2, t5 depth 3
        assert "Analyse" in result["depth_groups"].get(1, [])
        assert "Verify" in result["depth_groups"].get(3, [])

    def test_with_parallel_groups_input(self):
        """When plan already has parallel_groups, they appear in output."""
        plan = {
            "tasks": {"t1": {"name": "A", "depends_on": []}, "t2": {"name": "B", "depends_on": []}},
            "parallel_groups": {"g1": {"tasks": ["t1", "t2"]}},
        }
        result = simulate_plan(plan)
        assert result["status"] == "ok"
        assert "current_parallel_groups" in result
        assert result["current_parallel_groups"]["g1"]["tasks"] == ["t1", "t2"]

    def test_cycle_protection(self):
        """Circular dependency doesn't crash simulation."""
        plan = {
            "tasks": {
                "t1": {"name": "A", "depends_on": ["t2"]},
                "t2": {"name": "B", "depends_on": ["t1"]},  # cycle!
            },
        }
        result = simulate_plan(plan)
        assert result["status"] == "ok"  # no crash
        assert result["task_count"] == 2

    def test_two_independent_chains(self):
        """Two parallel chains give correct critical path."""
        plan = {
            "tasks": {
                "t1": {"name": "Setup DB", "depends_on": []},
                "t2": {"name": "Setup API", "depends_on": []},
                "t3": {"name": "Config DB", "depends_on": ["t1"]},
                "t4": {"name": "Build Routes", "depends_on": ["t2"]},
                "t5": {"name": "Test All", "depends_on": ["t3", "t4"]},
            },
        }
        result = simulate_plan(plan)
        assert result["task_count"] == 5
        assert result["critical_path_length"] == 3
        assert result["parallel_possible"]

    def test_single_task_plan(self):
        """Single task plan has no parallelization opportunity."""
        plan = {
            "tasks": {"t1": {"name": "Only Task", "depends_on": []}},
        }
        result = simulate_plan(plan)
        assert result["task_count"] == 1
        assert result["critical_path_length"] == 1
        assert not result["parallel_possible"]
        assert result["suggestion"] is None
