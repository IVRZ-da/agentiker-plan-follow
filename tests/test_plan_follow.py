"""Tests for plan_follow plugin."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Mock tools.registry before importing plan_core
import types
registry_mock = types.ModuleType("tools.registry")
registry_mock.registry = types.SimpleNamespace()
registry_mock.registry._entries = {}


class _MockEntry:
    def __init__(self, name):
        self.name = name
        self.schema = {"description": ""}


def _mock_get_entry(name):
    return _mock_registry.get(name)


registry_mock.registry.get_entry = _mock_get_entry
_mock_registry = {
    "plan_create": _MockEntry("plan_create"),
    "plan_current": _MockEntry("plan_current"),
    "plan_complete": _MockEntry("plan_complete"),
    "plan_verify": _MockEntry("plan_verify"),
    "plan_status": _MockEntry("plan_status"),
    "plan_update": _MockEntry("plan_update"),
    "code_search": _MockEntry("code_search"),
    "code_refactor": _MockEntry("code_refactor"),
    "code_definition": _MockEntry("code_definition"),
    "mcp_firecrawl_firecrawl_search": _MockEntry("mcp_firecrawl_firecrawl_search"),
    "mcp_firecrawl_firecrawl_scrape": _MockEntry("mcp_firecrawl_firecrawl_scrape"),
}
sys.modules["tools.registry"] = registry_mock

# Also mock hermes_cli.plugins
hermes_cli_mock = types.ModuleType("hermes_cli")
hermes_cli_mock.plugins = types.ModuleType("hermes_cli.plugins")
hermes_cli_mock.plugins.PluginContext = type("PluginContext", (), {})
sys.modules["hermes_cli"] = hermes_cli_mock
sys.modules["hermes_cli.plugins"] = hermes_cli_mock.plugins

# Now import the plugin modules
from plan_follow import plan_core


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_plans_dir(monkeypatch, tmp_path):
    """Use a temporary plans directory for each test."""
    test_plans = tmp_path / "plans"
    test_plans.mkdir()
    monkeypatch.setattr(plan_core, "PLANS_DIR", test_plans)
    monkeypatch.setattr(plan_core, "PLANS_INDEX", test_plans / "plans_index.json")
    monkeypatch.setattr(plan_core, "ARCHIVE_DIR", test_plans / "archived")
    plan_core._reset_cache()
    yield


@pytest.fixture
def sample_tasks():
    return [
        {"id": "p1", "name": "Validate function", "files": ["lib/val.ts"],
         "verify": "npm test", "depends_on": []},
        {"id": "p2", "name": "Form component", "files": ["components/form.tsx"],
         "verify": "npm test", "depends_on": ["p1"]},
        {"id": "p3", "name": "Integration test", "files": ["e2e/test.spec.ts"],
         "verify": "npm run test:e2e", "depends_on": ["p2"]},
    ]


# ─── Tests: Plan Creation ─────────────────────────────────────────────────────

class TestPlanCreate:
    def test_create_basic_plan(self, sample_tasks):
        plan_id = plan_core.create_plan("Fix validation", sample_tasks)
        assert plan_id.startswith("2026-")
        assert "fix-validation" in plan_id

    def test_plan_id_format(self, sample_tasks):
        plan_id = plan_core.create_plan("Test", sample_tasks)
        assert plan_id.count("-") >= 3
        assert plan_core._active_plan_id == plan_id

    def test_first_task_becomes_current(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        current = plan_core.get_current_task()
        assert current is not None
        assert current["task_id"] == "p1"
        assert current["name"] == "Validate function"
        assert current["status"] == "in_progress"

    def test_plan_saved_to_json(self, sample_tasks):
        plan_id = plan_core.create_plan("Test", sample_tasks)
        path = plan_core._plan_path(plan_id)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["plan_id"] == plan_id
        assert len(data["tasks"]) == 3

    def test_plan_with_empty_tasks_fails(self):
        result = plan_core.create_plan("Empty", [])
        assert result is None or result != ""

    def test_goal_in_plan(self, sample_tasks):
        plan_id = plan_core.create_plan("Fix form validation bug", sample_tasks)
        plan = plan_core._load_plan(plan_id)
        assert plan["goal"] == "Fix form validation bug"


# ─── Tests: Task Progression ──────────────────────────────────────────────────

class TestTaskProgression:
    def test_complete_task_advances(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        result = plan_core.complete_task("p1")
        assert result["status"] == "completed"
        assert result["next_task"] == "p2"
        new_current = plan_core.get_current_task()
        assert new_current["task_id"] == "p2"
        assert new_current["status"] == "in_progress"

    def test_complete_all_tasks(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        plan_core.complete_task("p2")
        result = plan_core.complete_task("p3")
        assert result["status"] == "completed"
        assert result["next_task"] is None
        assert plan_core.get_current_task() is None

    def test_task_order_preserved(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        plan_core.complete_task("p2")
        plan_core.complete_task("p3")
        status = plan_core.get_plan_status()
        assert status["progress"].startswith("3/3")

    def test_cannot_complete_wrong_task(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        result = plan_core.complete_task("p2")
        assert "error" in str(result.get("status", "")) or "error" in str(result.get("message", ""))

    def test_cannot_complete_nonexistent_task(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        result = plan_core.complete_task("p999")
        assert "not found" in str(result.get("message", ""))

    def test_progress_format(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        current = plan_core.get_current_task()
        assert "▶️p1" in current["progress"]
        assert "⬜p2" in current["progress"]

    def test_progress_after_completion(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        current = plan_core.get_current_task()
        assert "✅p1" in current["progress"]
        assert "▶️p2" in current["progress"]


# ─── Tests: Dependencies ──────────────────────────────────────────────────────

class TestDependencies:
    def test_dependent_task_blocked_initially(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        # p2 should be pending until p1 is done
        status = plan_core.get_plan_status()
        for t in status["tasks"]:
            if t["id"] == "p2":
                assert t["status"] == "pending"

    def test_dependency_chain(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        plan_core.complete_task("p2")
        plan_core.complete_task("p3")
        status = plan_core.get_plan_status()
        assert status["progress"].startswith("3/3")

    def test_dependency_order_respected(self, sample_tasks):
        """p3 depends on p2, should not be skippable."""
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        current = plan_core.get_current_task()
        assert current["task_id"] == "p2"


# ─── Tests: Plan Status ───────────────────────────────────────────────────────

class TestPlanStatus:
    def test_status_no_active_plan(self):
        plan_core._reset_cache()
        status = plan_core.get_plan_status()
        assert status is None

    def test_status_after_create(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        status = plan_core.get_plan_status()
        assert status["plan_id"] is not None
        assert status["goal"] == "Test"
        assert status["current_task"] == "p1"

    def test_status_counts(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        status = plan_core.get_plan_status()
        assert "1/3" in status["progress"] or "0/3" in status["progress"]

    def test_status_tasks_list(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        status = plan_core.get_plan_status()
        assert len(status["tasks"]) == 3

    def test_status_after_partial_completion(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        status = plan_core.get_plan_status()
        for t in status["tasks"]:
            if t["id"] == "p1":
                assert t["status"] == "completed"
            elif t["id"] == "p2":
                assert t["status"] == "in_progress"


# ─── Tests: Plan Update ───────────────────────────────────────────────────────

class TestPlanUpdate:
    def test_update_task_files(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        result = plan_core.update_task("p1", {"files": ["lib/val.ts", "lib/utils.ts"]})
        assert result is not None
        assert result["files"] == ["lib/val.ts", "lib/utils.ts"]

    def test_update_task_verify(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.update_task("p1", {"verify": "npm run test:unit -- val"})
        task = plan_core.get_current_task()
        assert task["verify"] == "npm run test:unit -- val"

    def test_update_nonexistent_task(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        result = plan_core.update_task("p999", {"files": ["x.ts"]})
        assert result is None

    def test_update_no_active_plan(self):
        plan_core._reset_cache()
        result = plan_core.update_task("p1", {"files": ["x.ts"]})
        assert result is None


# ─── Tests: Load / Persistence ────────────────────────────────────────────────

class TestPersistence:
    def test_load_saved_plan(self, sample_tasks):
        plan_id = plan_core.create_plan("Test", sample_tasks)
        plan_core._reset_cache()
        assert plan_core._active_plan is None
        ok = plan_core.set_active_plan(plan_id)
        assert ok is True
        assert plan_core._active_plan is not None
        assert plan_core._active_plan["plan_id"] == plan_id

    def test_load_nonexistent_plan(self):
        ok = plan_core.set_active_plan("nonexistent-plan")
        assert ok is False

    def test_persist_and_restore_progress(self, sample_tasks):
        plan_id = plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        # Simulate session restart
        plan_core._reset_cache()
        plan_core.set_active_plan(plan_id)
        current = plan_core.get_current_task()
        assert current["task_id"] == "p2"

    def test_json_file_format(self, sample_tasks):
        plan_id = plan_core.create_plan("Test", sample_tasks)
        path = plan_core._plan_path(plan_id)
        raw = path.read_text()
        data = json.loads(raw)
        assert "plan_id" in data
        assert "goal" in data
        assert "created" in data
        assert "tasks" in data
        assert "current_task" in data

# ─── Tests: Disk Recovery (Cross-Session) ─────────────────────────────────────

class TestDiskRecovery:
    """Tests for plans_index.json and _recover_plan_from_disk()."""

    def test_update_plans_index_creates_file(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, _update_plans_index,
                                            PLANS_DIR, _get_active_plan)
        create_plan("Test", sample_tasks)
        index_path = PLANS_DIR / "plans_index.json"
        assert index_path.exists()
        data = json.loads(index_path.read_text())
        assert "active_plan_id" in data
        assert data["active_goal"] == "Test"

    def test_recover_from_index(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, _recover_plan_from_disk,
                                            _reset_cache)
        plan_id = create_plan("Test", sample_tasks)
        _reset_cache()
        recovered = _recover_plan_from_disk()
        assert recovered == plan_id

    def test_recover_from_newest_json(self, sample_tasks):
        """Wenn plans_index fehlt, wird von neuester JSON mit current_task recoveriert."""
        from plan_follow.plan_core import (create_plan, _recover_plan_from_disk,
                                            _reset_cache, PLANS_INDEX)
        plan_id = create_plan("Test", sample_tasks)
        # Remove index to force fallback
        if PLANS_INDEX.exists():
            PLANS_INDEX.unlink()
        _reset_cache()
        recovered = _recover_plan_from_disk()
        assert recovered == plan_id

    def test_recover_from_fallback(self, sample_tasks):
        """Wenn alle Pläne completed sind, wird die neueste JSON geladen."""
        from plan_follow.plan_core import (create_plan, _recover_plan_from_disk,
                                            _reset_cache, PLANS_INDEX)
        plan_id = create_plan("Test", sample_tasks)
        from plan_follow.plan_core import complete_task
        complete_task("p1")
        complete_task("p2")
        complete_task("p3")
        # Plan is now complete (no current_task)
        if PLANS_INDEX.exists():
            PLANS_INDEX.unlink()
        _reset_cache()
        recovered = _recover_plan_from_disk()
        assert recovered == plan_id

    def test_recover_no_plans(self):
        """Leeres Verzeichnis gibt None zurück."""
        from plan_follow.plan_core import (_recover_plan_from_disk,
                                            _reset_cache)
        _reset_cache()
        recovered = _recover_plan_from_disk()
        assert recovered is None

    def test_get_active_plan_auto_recovers(self, sample_tasks):
        """_get_active_plan() muss nach _reset_cache() automatisch recoverieren."""
        import plan_follow.plan_core as pc
        plan_id = pc.create_plan("Test", sample_tasks)
        pc._reset_cache()
        assert pc._active_plan is None
        plan = pc._get_active_plan()
        assert plan is not None
        assert plan["plan_id"] == plan_id

# ─── Tests: Parallel Groups ────────────────────────────────────────────────────

class TestParallelGroups:
    """Tests for parallel_groups feature in create_plan / complete_task."""

    def test_create_with_parallel_groups(self):
        from plan_follow.plan_core import create_plan, _get_active_plan
        tasks = [
            {"id": "p1", "name": "Task 1"},
            {"id": "p2", "name": "Task 2"},
            {"id": "p3", "name": "Task 3"},
        ]
        groups = {
            "g1": {"tasks": ["p1", "p2"]},
            "g2": {"tasks": ["p3"]},
        }
        plan_id = create_plan("Test Groups", tasks, parallel_groups=groups)
        assert plan_id is not None

        plan = _get_active_plan()
        assert "parallel_groups" in plan
        assert plan["parallel_groups"]["g1"]["status"] == "in_progress"
        assert plan["parallel_groups"]["g2"]["status"] == "pending"

    def test_group_sets_all_tasks_in_progress(self):
        from plan_follow.plan_core import create_plan, _get_active_plan
        tasks = [
            {"id": "p1", "name": "Task 1"},
            {"id": "p2", "name": "Task 2"},
            {"id": "p3", "name": "Task 3"},
        ]
        groups = {"g1": {"tasks": ["p1", "p2"]}, "g2": {"tasks": ["p3"]}}
        create_plan("Test", tasks, parallel_groups=groups)
        plan = _get_active_plan()
        assert plan["tasks"]["p1"]["status"] == "in_progress"
        assert plan["tasks"]["p2"]["status"] == "in_progress"
        assert plan["tasks"]["p3"]["status"] == "pending"

    def test_get_current_tasks_returns_group(self):
        from plan_follow.plan_core import create_plan, get_current_tasks
        tasks = [
            {"id": "p1", "name": "Task 1"},
            {"id": "p2", "name": "Task 2"},
            {"id": "p3", "name": "Task 3"},
        ]
        groups = {"g1": {"tasks": ["p1", "p2"]}, "g2": {"tasks": ["p3"]}}
        create_plan("Test", tasks, parallel_groups=groups)
        current = get_current_tasks()
        assert len(current) == 2  # p1 and p2 are in_progress
        tids = [t["task_id"] for t in current]
        assert "p1" in tids
        assert "p2" in tids
        assert "p3" not in tids

    def test_complete_task_in_group_keeps_group_active(self):
        from plan_follow.plan_core import (create_plan, complete_task,
                                            get_current_tasks)
        tasks = [
            {"id": "p1", "name": "Task 1"},
            {"id": "p2", "name": "Task 2"},
            {"id": "p3", "name": "Task 3"},
        ]
        groups = {"g1": {"tasks": ["p1", "p2"]}, "g2": {"tasks": ["p3"]}}
        create_plan("Test", tasks, parallel_groups=groups)

        # Complete p1 — group g1 is still active (p2 not done)
        result = complete_task("p1")
        assert result["status"] == "completed"
        assert result["next_task"] == "p2"  # advances within group

        current = get_current_tasks()
        assert len(current) == 1
        assert current[0]["task_id"] == "p2"

    def test_complete_group_advances_to_next(self):
        from plan_follow.plan_core import (create_plan, complete_task,
                                            get_current_tasks, _get_active_plan)
        tasks = [
            {"id": "p1", "name": "Task 1"},
            {"id": "p2", "name": "Task 2"},
            {"id": "p3", "name": "Task 3"},
        ]
        groups = {"g1": {"tasks": ["p1", "p2"]}, "g2": {"tasks": ["p3"]}}
        create_plan("Test", tasks, parallel_groups=groups)

        # Complete all tasks in g1
        complete_task("p1")
        result = complete_task("p2")
        assert result["status"] == "completed"
        assert result["next_task"] == "p3"

        plan = _get_active_plan()
        assert plan["parallel_groups"]["g1"]["status"] == "completed"
        assert plan["parallel_groups"]["g2"]["status"] == "in_progress"
        assert plan["tasks"]["p3"]["status"] == "in_progress"

    def test_complete_all_groups(self):
        from plan_follow.plan_core import (create_plan, complete_task,
                                            _get_active_plan)
        tasks = [
            {"id": "p1", "name": "Task 1"},
            {"id": "p2", "name": "Task 2"},
        ]
        groups = {"g1": {"tasks": ["p1"]}, "g2": {"tasks": ["p2"]}}
        create_plan("Test", tasks, parallel_groups=groups)

        complete_task("p1")
        result = complete_task("p2")
        assert result["status"] == "completed"
        assert result["next_task"] is None

        plan = _get_active_plan()
        assert plan["parallel_groups"]["g1"]["status"] == "completed"
        assert plan["parallel_groups"]["g2"]["status"] == "completed"

    def test_progress_with_groups(self):
        from plan_follow.plan_core import create_plan, _format_progress, _get_active_plan
        tasks = [
            {"id": "p1", "name": "T1"},
            {"id": "p2", "name": "T2"},
            {"id": "p3", "name": "T3"},
        ]
        groups = {"design": {"tasks": ["p1", "p2"]}, "impl": {"tasks": ["p3"]}}
        create_plan("Test", tasks, parallel_groups=groups)
        progress = _format_progress(_get_active_plan())
        assert "▶️design" in progress
        assert "⬜impl" in progress

    def test_get_current_tasks_linear_mode(self, sample_tasks):
        """In linear mode (no groups), get_current_tasks returns one task."""
        from plan_follow.plan_core import create_plan, get_current_tasks
        create_plan("Test", sample_tasks)
        current = get_current_tasks()
        assert len(current) == 1
        assert current[0]["task_id"] == "p1"

    def test_get_current_tasks_no_plan(self):
        from plan_follow.plan_core import get_current_tasks, _reset_cache
        _reset_cache()
        assert get_current_tasks() == []

    def test_group_id_order_preserved(self):
        """Groups should process in sorted key order, not insertion order."""
        from plan_follow.plan_core import create_plan, complete_task, _get_active_plan
        tasks = [
            {"id": "p1", "name": "A"}, {"id": "p2", "name": "B"},
            {"id": "p3", "name": "C"}, {"id": "p4", "name": "D"},
        ]
        groups = {
            "z-group": {"tasks": ["p4"]},
            "a-group": {"tasks": ["p1", "p2"]},
            "m-group": {"tasks": ["p3"]},
        }
        create_plan("Test", tasks, parallel_groups=groups)
        plan = _get_active_plan()
        # Sorted keys: a-group, m-group, z-group
        assert plan["parallel_groups"]["a-group"]["status"] == "in_progress"
        assert plan["parallel_groups"]["m-group"]["status"] == "pending"
        assert plan["parallel_groups"]["z-group"]["status"] == "pending"

        # Complete a-group → m-group activates
        complete_task("p1")
        complete_task("p2")
        assert plan["parallel_groups"]["m-group"]["status"] == "in_progress"

# ─── Tests: Plan Templates ─────────────────────────────────────────────────────

class TestPlanTemplates:
    """Tests for plan_templates.py and template expansion in plan_create_tool."""

    def test_expand_deploy_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("deploy")
        assert "tasks" in result
        assert len(result["tasks"]) == 4
        assert result["tasks"][0]["id"] == "d1"
        assert result["tasks"][0]["name"] == "Build check"

    def test_expand_bugfix_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("bugfix")
        assert len(result["tasks"]) == 3
        assert result["tasks"][0]["id"] == "b1"

    def test_expand_feature_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("feature")
        assert len(result["tasks"]) == 4

    def test_expand_refactoring_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("refactoring")
        assert len(result["tasks"]) == 4
        assert result["review_profile"] == "full"

    def test_expand_research_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("research")
        assert len(result["tasks"]) == 3
        assert result["review_profile"] == "none"

    def test_expand_unknown_template(self):
        from plan_follow.plan_templates import expand_template
        result = expand_template("nonexistent")
        assert "error" in result

    def test_template_names_exported(self):
        from plan_follow.plan_templates import TEMPLATE_NAMES
        assert "deploy" in TEMPLATE_NAMES
        assert "bugfix" in TEMPLATE_NAMES
        assert "feature" in TEMPLATE_NAMES
        assert "refactoring" in TEMPLATE_NAMES
        assert "research" in TEMPLATE_NAMES

    def test_template_tasks_have_ids_and_names(self):
        from plan_follow.plan_templates import expand_template
        for name in ("deploy", "bugfix", "feature", "refactoring", "research"):
            result = expand_template(name)
            for t in result["tasks"]:
                assert "id" in t, f"{name}: Task fehlt id"
                assert "name" in t, f"{name}: Task fehlt name"

    def test_create_plan_with_template_via_tool(self):
        from plan_follow.plan_tools import plan_create_tool
        result = json.loads(plan_create_tool({
            "goal": "Test deploy",
            "template": "deploy",
            "repo": "/tmp",
        }))
        assert result["status"] == "created"
        assert result["template"] == "deploy"

    def test_create_plan_with_template_no_goal(self):
        from plan_follow.plan_tools import plan_create_tool
        result = json.loads(plan_create_tool({
            "template": "research",
        }))
        # research template has goal set from description
        assert "error" not in result
        assert result["status"] == "created"

    def test_parallel_groups_via_create_tool(self):
        from plan_follow.plan_tools import plan_create_tool
        from plan_follow.plan_core import _get_active_plan
        tasks = [
            {"id": "p1", "name": "T1"}, {"id": "p2", "name": "T2"},
            {"id": "p3", "name": "T3"},
        ]
        groups = {"g1": {"tasks": ["p1"]}, "g2": {"tasks": ["p2", "p3"]}}
        result = json.loads(plan_create_tool({
            "goal": "Parallel test", "tasks": tasks,
            "parallel_groups": groups,
        }))
        assert result["status"] == "created"
        plan = _get_active_plan()
        assert "parallel_groups" in plan
        assert plan["parallel_groups"]["g1"]["status"] == "in_progress"

# ─── Tests: Multi-Repo + Plan Version ─────────────────────────────────────────

class TestMultiRepo:
    """Tests for multi-repo support and plan versioning."""

    def test_get_repos_single(self):
        """Legacy single 'repo' is normalized to list."""
        from plan_follow.plan_core import _get_repos
        plan = {"repo": "/home/jo/project"}
        assert _get_repos(plan) == ["/home/jo/project"]

    def test_get_repos_array(self):
        """'repos' array is returned as-is."""
        from plan_follow.plan_core import _get_repos
        plan = {"repos": ["/home/jo/project1", "/home/jo/project2"]}
        assert _get_repos(plan) == ["/home/jo/project1", "/home/jo/project2"]

    def test_get_repos_empty(self):
        """Empty repos returns empty list."""
        from plan_follow.plan_core import _get_repos
        assert _get_repos({}) == []
        assert _get_repos({"repo": ""}) == []

    def test_get_repos_prefers_array(self):
        """If both repos and repo exist, repos wins."""
        from plan_follow.plan_core import _get_repos
        plan = {"repo": "/home/jo/legacy", "repos": ["/home/jo/new1", "/home/jo/new2"]}
        assert _get_repos(plan) == ["/home/jo/new1", "/home/jo/new2"]

    def test_plan_version_in_created_plan(self):
        from plan_follow.plan_core import create_plan, _get_active_plan
        tasks = [{"id": "p1", "name": "T1"}]
        create_plan("Test", tasks)
        plan = _get_active_plan()
        assert plan.get("plan_version") == "1"

    def test_create_plan_with_repos_array(self):
        from plan_follow.plan_core import create_plan, _get_active_plan
        tasks = [{"id": "p1", "name": "T1"}]
        repos = ["/home/jo/repo1", "/home/jo/repo2"]
        create_plan("Test", tasks, repos=repos)
        plan = _get_active_plan()
        assert plan.get("repos") == repos
        assert plan.get("repo") == ""  # legacy field still present but empty

    def test_drift_multi_repo_no_git(self):
        """Drift check on non-git repos returns empty."""
        from plan_follow.plan_core import create_plan, check_drift, _reset_cache
        import plan_follow.plan_core as pc
        tasks = [{"id": "p1", "name": "T1", "files": []}]
        # Save original to restore
        create_plan("Test", tasks, repos=["/nonexistent1", "/nonexistent2"])
        result = check_drift()
        assert result == []


# ─── Tests: Drift Detection ───────────────────────────────────────────────────

class TestDrift:
    def test_drift_no_git_repo(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks, repo="/nonexistent/repo")
        drift = plan_core.check_drift()
        assert drift == []

    def test_drift_no_active_plan(self):
        plan_core._reset_cache()
        drift = plan_core.check_drift()
        assert drift == []

    def test_drift_no_current_task(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.complete_task("p1")
        plan_core.complete_task("p2")
        plan_core.complete_task("p3")
        drift = plan_core.check_drift()
        assert drift == []


# ─── Tests: Health Check ──────────────────────────────────────────────────────

class TestHealthCheck:
    def test_health_check_self_ok(self):
        """With mock registry populated, self-check should pass."""
        result = plan_core.health_check()
        # Honcho and Serena will fail (no server in tests), but self-check should be ok
        assert "plan_follow: Eigenes Tool" not in str(result.get("issues", []))

    def test_health_check_code_intel_ok(self):
        result = plan_core.health_check()
        assert "agentiker_code_intel: Tool" not in str(result.get("issues", []))

    def test_health_check_firecrawl_ok(self):
        result = plan_core.health_check()
        assert "Firecrawl: Tool" not in str(result.get("issues", []))


# ─── Tests: Tool Handler Dispatch (simuliert Hermes-Aufruf) ─────────────────

class TestToolHandlerDispatch:
    """Test that tool handlers work with the Hermes dispatch pattern (args dict, not kwargs)."""

    def test_plan_create_handler_dispatch(self, sample_tasks, reset_plans_dir):
        from plan_follow.plan_tools import plan_create_tool
        result = json.loads(plan_create_tool({
            "goal": "Test dispatch", "tasks": sample_tasks,
        }))
        assert result["status"] == "created"

    def test_plan_current_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import plan_current_tool, plan_create_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_current_tool({}))
        assert result["task_id"] == "p1"

    def test_plan_complete_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import plan_complete_tool, plan_create_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert result["status"] == "completed"

    def test_plan_verify_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import plan_verify_tool, plan_create_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_verify_tool({}))
        assert result["status"] in ("clean", "drift_detected")

    def test_plan_status_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import plan_status_tool, plan_create_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_status_tool({}))
        assert len(result["tasks"]) == 3

    def test_plan_update_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import plan_update_tool, plan_create_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_update_tool({
            "task_id": "p1", "changes": {"files": ["new.ts"]},
        }))
        assert result["status"] == "updated"

    def test_all_handlers_accept_args_dict(self):
        """Verify every handler has (args, **kwargs) signature."""
        import inspect
        from plan_follow import plan_tools
        for name in ["plan_create_tool", "plan_current_tool", "plan_complete_tool",
                      "plan_verify_tool", "plan_status_tool", "plan_update_tool"]:
            handler = getattr(plan_tools, name)
            sig = inspect.signature(handler)
            params = list(sig.parameters.keys())
            assert params[0] in ("args", "kwargs"), \
                f"{name}: erster Parameter muss 'args' oder '**kwargs' sein, ist: {params[0]}"


# ─── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_task_plan(self):
        tasks = [{"id": "p1", "name": "Only task", "files": ["main.ts"],
                  "verify": "", "depends_on": []}]
        plan_core.create_plan("Single", tasks)
        result = plan_core.complete_task("p1")
        assert result["status"] == "completed"
        assert result["next_task"] is None

    def test_task_with_no_files(self):
        tasks = [{"id": "p1", "name": "No files", "files": [],
                  "verify": "", "depends_on": []}]
        plan_core.create_plan("NoFiles", tasks)
        current = plan_core.get_current_task()
        assert current is not None
        assert current["files"] == []

    def test_update_changes_live(self, sample_tasks):
        plan_core.create_plan("Test", sample_tasks)
        plan_core.update_task("p1", {"name": "Updated validate"})
        plan_core.complete_task("p1")
        current = plan_core.get_current_task()
        assert current["task_id"] == "p2"

    def test_empty_goal_still_works(self):
        tasks = [{"id": "p1", "name": "Task", "files": [], "verify": "", "depends_on": []}]
        plan_id = plan_core.create_plan("", tasks)
        assert plan_id is not None
        assert len(plan_id) > 10


# ─── Tests: Plan Management (list, abort, delete, select) ──────────────────────

class TestPlanManagement:
    """Tests for plan management functions: list_plans, abort_plan, delete_plan, select_plan."""

    def test_list_plans_empty(self):
        """Empty directory returns empty list."""
        from plan_follow.plan_core import list_plans
        plans = list_plans()
        assert isinstance(plans, list)
        assert len(plans) == 0

    def test_list_plans_after_create(self, sample_tasks):
        from plan_follow.plan_core import create_plan, list_plans
        create_plan("Test", sample_tasks)
        plans = list_plans()
        assert len(plans) >= 1
        assert plans[0]["plan_id"].startswith("2026-")
        assert plans[0]["is_active"] is True

    def test_list_plans_shows_progress(self, sample_tasks):
        from plan_follow.plan_core import create_plan, list_plans
        create_plan("Test", sample_tasks)
        plans = list_plans()
        assert plans[0]["total_tasks"] == 3
        assert "0/3" in plans[0]["progress"] or "0" in plans[0]["progress"]

    def test_list_plans_multiple(self, sample_tasks):
        from plan_follow.plan_core import create_plan, list_plans
        p1 = create_plan("First", sample_tasks)
        # Clear cache so second create actually creates a new plan
        from plan_follow.plan_core import _reset_cache
        _reset_cache()
        p2 = create_plan("Second", sample_tasks)
        plans = list_plans()
        assert len(plans) >= 2
        # Newest first
        assert plans[0]["plan_id"] == p2

    def test_abort_entire_plan(self, sample_tasks):
        from plan_follow.plan_core import create_plan, abort_plan, get_current_task
        create_plan("Test", sample_tasks)
        result = abort_plan()
        assert result["status"] == "aborted"
        assert get_current_task() is None

    def test_abort_specific_task(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, abort_plan,
                                            _get_active_plan, get_current_task)
        create_plan("Test", sample_tasks)
        result = abort_plan(task_id="p1")
        assert result["status"] == "aborted"
        plan = _get_active_plan()
        assert plan["tasks"]["p1"]["status"] == "aborted"

    def test_abort_nonexistent_task(self, sample_tasks):
        from plan_follow.plan_core import create_plan, abort_plan
        create_plan("Test", sample_tasks)
        result = abort_plan(task_id="p999")
        assert "error" in result.get("status", "")

    def test_abort_no_active_plan(self):
        from plan_follow.plan_core import abort_plan, _reset_cache
        _reset_cache()
        result = abort_plan()
        assert "error" in result.get("status", "")

    def test_delete_plan(self, sample_tasks):
        from plan_follow.plan_core import create_plan, delete_plan, _plan_path
        plan_id = create_plan("Test", sample_tasks)
        result = delete_plan(plan_id)
        assert result["status"] == "deleted"
        assert not _plan_path(plan_id).exists()

    def test_delete_clears_active(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, delete_plan,
                                            _active_plan_id)
        plan_id = create_plan("Test", sample_tasks)
        delete_plan(plan_id)
        assert _active_plan_id is None

    def test_delete_nonexistent_plan(self):
        from plan_follow.plan_core import delete_plan
        result = delete_plan("no-such-plan")
        assert "error" in result.get("status", "")

    def test_select_plan(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, select_plan,
                                            _reset_cache)
        import plan_follow.plan_core as pc
        plan_id = create_plan("Test", sample_tasks)
        _reset_cache()
        result = select_plan(plan_id)
        assert result["status"] == "selected"
        assert pc._active_plan_id == plan_id

    def test_select_plan_shows_current_task(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, select_plan, _reset_cache)
        plan_id = create_plan("Test", sample_tasks)
        _reset_cache()
        result = select_plan(plan_id)
        assert result["current_task"] is not None

    def test_select_nonexistent_plan(self):
        from plan_follow.plan_core import select_plan
        result = select_plan("no-such-plan")
        assert "error" in result.get("status", "")

    # ─── Tool handler dispatch tests ───────────────────────────────────────

    def test_plan_list_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import (plan_list_tool, plan_create_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_list_tool({}))
        assert result["status"] == "ok"
        assert result["count"] >= 1

    def test_plan_abort_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import (plan_abort_tool, plan_create_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_abort_tool({}))
        assert result["status"] == "aborted"

    def test_plan_delete_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import (plan_delete_tool, plan_create_tool,
                                              plan_list_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        plans = json.loads(plan_list_tool({}))
        plan_id = plans["plans"][0]["plan_id"]
        result = json.loads(plan_delete_tool({"plan_id": plan_id}))
        assert result["status"] == "deleted"

    def test_plan_select_handler_dispatch(self, sample_tasks):
        from plan_follow.plan_tools import (plan_select_tool, plan_create_tool,
                                              plan_list_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        plans = json.loads(plan_list_tool({}))
        plan_id = plans["plans"][0]["plan_id"]
        result = json.loads(plan_select_tool({"plan_id": plan_id}))
        assert result["status"] == "selected"

    def test_all_new_handlers_accept_args_dict(self):
        """Verify every NEW handler has (args, **kwargs) signature."""
        import inspect
        from plan_follow import plan_tools
        for name in ["plan_list_tool", "plan_abort_tool",
                      "plan_delete_tool", "plan_select_tool"]:
            handler = getattr(plan_tools, name)
            sig = inspect.signature(handler)
            params = list(sig.parameters.keys())
            assert params[0] in ("args", "kwargs"), \
                f"{name}: erster Parameter muss 'args' oder '**kwargs' sein, ist: {params[0]}"


# ─── Tests: Review Profile Data Model ─────────────────────────────────────────

class TestReviewDataModel:
    """Tests for the data model: review_profile + review_result + state helpers."""

    def test_create_plan_with_review_profile(self):
        from plan_follow.plan_core import create_plan, _get_active_plan
        create_plan("Test Model", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        plan = _get_active_plan()
        assert plan["tasks"]["t1"]["review_profile"] == "unit-test"
        assert plan["tasks"]["t1"]["review_result"] is None

    def test_create_plan_default_review_profile(self):
        from plan_follow.plan_core import create_plan, _get_active_plan
        create_plan("Test Default", [{"id": "t1", "name": "T1"}])
        plan = _get_active_plan()
        assert plan["tasks"]["t1"]["review_profile"] == "none"

    def test_current_task_includes_review_fields(self, sample_tasks):
        from plan_follow.plan_core import create_plan, get_current_task
        create_plan("Test", sample_tasks)
        current = get_current_task()
        assert "review_profile" in current
        assert "review_result" in current

    def test_save_review_result(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, _get_active_plan,
                                            save_review_result)
        create_plan("Test", sample_tasks)
        result = save_review_result("p1", {
            "status": "passed", "issues": [], "summary": "OK"
        })
        assert result is True
        plan = _get_active_plan()
        assert plan["tasks"]["p1"]["review_result"]["status"] == "passed"
        assert plan["tasks"]["p1"]["review_result"]["summary"] == "OK"
        assert "timestamp" in plan["tasks"]["p1"]["review_result"]

    def test_save_review_result_nonexistent_task(self):
        from plan_follow.plan_core import save_review_result
        result = save_review_result("no_such_task", {"status": "passed"})
        assert result is False

    def test_is_review_passed_without_profile(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            is_review_passed)
        create_plan("Test", sample_tasks)
        current = get_current_task()
        assert is_review_passed(current) is True  # default: none

    def test_is_review_passed_before_review(self):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            is_review_passed)
        create_plan("Test", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        current = get_current_task()
        assert is_review_passed(current) is False  # noch kein review_result

    def test_is_review_passed_after_successful_review(self):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            is_review_passed, save_review_result)
        create_plan("Test", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        save_review_result("t1", {"status": "passed", "issues": []})
        current = get_current_task()
        assert is_review_passed(current) is True

    def test_get_review_state_not_required(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            get_task_review_state)
        create_plan("Test", sample_tasks)
        current = get_current_task()
        assert get_task_review_state(current) == "not_required"

    def test_get_review_state_in_review(self):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            get_task_review_state)
        create_plan("Test", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        current = get_current_task()
        assert get_task_review_state(current) == "in_review"

    def test_get_review_state_passed(self):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            get_task_review_state, save_review_result)
        create_plan("Test", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        save_review_result("t1", {"status": "passed", "issues": []})
        current = get_current_task()
        assert get_task_review_state(current) == "passed"

    def test_get_review_state_failed(self):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            get_task_review_state, save_review_result)
        create_plan("Test", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        save_review_result("t1", {"status": "failed", "issues": [{"check": "test"}]})
        current = get_current_task()
        assert get_task_review_state(current) == "failed"

    def test_get_review_state_pending(self):
        from plan_follow.plan_core import (create_plan, get_current_task,
                                            get_task_review_state, save_review_result)
        create_plan("Test", [{"id": "t1", "name": "T1", "review_profile": "unit-test"}])
        save_review_result("t1", {"status": "pending", "issues": []})
        current = get_current_task()
        assert get_task_review_state(current) == "pending"

    def test_update_task_review_profile(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, update_task,
                                            _get_active_plan)
        create_plan("Test", sample_tasks)
        update_task("p1", {"review_profile": "security"})
        plan = _get_active_plan()
        assert plan["tasks"]["p1"]["review_profile"] == "security"

    def test_migration_compatibility(self):
        """Alte Pläne ohne review_profile müssen funktionieren."""
        import json, tempfile
        from plan_follow.plan_core import _get_active_plan
        # Simuliere alten Plan ohne review_profile
        old_plan = {
            "plan_id": "migration-test",
            "goal": "Test",
            "created": "2026-06-18T00:00:00",
            "current_task": "t1",
            "tasks": {
                "t1": {
                    "status": "in_progress",
                    "name": "Old task",
                    "files": [],
                    "verify": "",
                    "depends_on": [],
                    # KEIN review_profile, KEIN review_result
                }
            }
        }
        from plan_follow.plan_core import PLANS_DIR
        path = PLANS_DIR / "migration-test.json"
        path.write_text(json.dumps(old_plan))
        from plan_follow.plan_core import set_active_plan
        assert set_active_plan("migration-test")
        from plan_follow.plan_core import get_current_task, is_review_passed
        current = get_current_task()
        assert current["review_profile"] == "none"
        assert current["review_result"] is None
        assert is_review_passed(current) is True

# ─── Tests: Review Profiles ───────────────────────────────────────────────────

class TestReviewProfiles:
    """Tests for review_profiles.py — Profile definitions and helpers."""

    def test_all_profiles_exist(self):
        from plan_follow.review_profiles import PROFILES
        expected = {"none", "unit-test", "api-route", "ui-component", "security", "full"}
        assert expected.issubset(PROFILES.keys())

    def test_get_profile_returns_correct(self):
        from plan_follow.review_profiles import get_profile
        profile = get_profile("unit-test")
        assert profile["description"] != ""
        assert len(profile["checks"]) >= 3

    def test_get_profile_fallback_to_none(self):
        from plan_follow.review_profiles import get_profile
        profile = get_profile("nonexistent_profile")
        assert profile["checks"] == []  # fallback auf none

    def test_none_profile_has_no_checks(self):
        from plan_follow.review_profiles import get_profile
        profile = get_profile("none")
        assert profile["checks"] == []

    def test_full_profile_has_most_checks(self):
        from plan_follow.review_profiles import get_profile
        profile = get_profile("full")
        assert len(profile["checks"]) > len(get_profile("unit-test")["checks"])

    def test_each_profile_has_description_and_checks(self):
        from plan_follow.review_profiles import PROFILES
        for name, profile in PROFILES.items():
            assert "description" in profile, f"{name}: description fehlt"
            assert "checks" in profile, f"{name}: checks fehlt"
            assert isinstance(profile["checks"], list)

    def test_get_check_description_returns_german_text(self):
        from plan_follow.review_profiles import get_check_description
        desc = get_check_description("code_compiles")
        assert "compiliert" in desc or "fehlerfrei" in desc

    def test_get_check_description_unknown(self):
        from plan_follow.review_profiles import get_check_description
        desc = get_check_description("does_not_exist")
        assert "Unbekannt" in desc

    def test_no_duplicate_checks_within_each_profile(self):
        from plan_follow.review_profiles import PROFILES
        for name, profile in PROFILES.items():
            checks = profile["checks"]
            assert len(checks) == len(set(checks)), \
                f"Doppelte Check-Namen in Profil '{name}': {len(checks)} != {len(set(checks))}"

    def test_profile_names_tuple(self):
        from plan_follow.review_profiles import PROFILE_NAMES
        assert "none" in PROFILE_NAMES
        assert "full" in PROFILE_NAMES
        assert len(PROFILE_NAMES) >= 6


# ─── Tests: Review Dispatch (plan_review.py) ─────────────────────────────────

class TestReviewDispatch:
    """Tests for plan_review.py — dispatch_review, build_review_prompt, validate."""

    def test_dispatch_ready_with_files(self):
        from plan_follow.plan_review import dispatch_review
        result = dispatch_review("unit-test", {"id": "t1", "files": ["test.py"]})
        assert result["status"] == "ready"
        assert "checks" in result

    def test_dispatch_skipped_without_files(self):
        from plan_follow.plan_review import dispatch_review
        result = dispatch_review("unit-test", {"id": "t1", "files": []})
        assert result["status"] == "skipped"

    def test_dispatch_skipped_with_none_profile(self):
        from plan_follow.plan_review import dispatch_review
        result = dispatch_review("none", {"id": "t1", "files": ["test.py"]})
        assert result["status"] == "skipped"

    def test_dispatch_quick_depth_reduces_checks(self):
        from plan_follow.plan_review import dispatch_review
        normal = dispatch_review("full", {"id": "t1", "files": ["a.py"]}, depth="normal")
        quick = dispatch_review("full", {"id": "t1", "files": ["a.py"]}, depth="quick")
        assert len(quick["checks"]) < len(normal["checks"])

    def test_build_review_prompt_contains_task_info(self):
        from plan_follow.plan_review import build_review_prompt
        prompt = build_review_prompt("unit-test", {"id": "t1", "name": "Test task"},
                                     {"test.py": "def foo(): pass"})
        assert "t1" in prompt
        assert "Test task" in prompt
        assert "unit-test" in prompt
        assert "edge_cases_covered" in prompt

    def test_build_review_prompt_truncates_long_files(self):
        from plan_follow.plan_review import build_review_prompt
        long_content = "\n".join(f"line {i}" for i in range(1000))
        prompt = build_review_prompt("unit-test", {"id": "t1", "name": "T"},
                                     {"long.py": long_content})
        assert "gekürzt" in prompt
        assert "line 0" in prompt
        assert "line 499" in prompt  # Letzte Zeile vor truncation

    def test_build_review_prompt_empty_files(self):
        from plan_follow.plan_review import build_review_prompt
        prompt = build_review_prompt("unit-test", {"id": "t1", "name": "T"}, {})
        assert "No files" in prompt

    def test_validate_review_result_valid(self):
        from plan_follow.plan_review import validate_review_result
        result = validate_review_result({
            "passed": True, "status": "passed", "issues": [], "summary": "OK"
        })
        assert result["passed"] is True
        assert result["status"] == "passed"

    def test_validate_review_result_with_errors(self):
        from plan_follow.plan_review import validate_review_result
        result = validate_review_result({
            "passed": False, "status": "failed",
            "issues": [{"check": "test", "severity": "error", "message": "Missing test"}],
            "summary": "Failed",
        })
        assert result["passed"] is False
        assert result["status"] == "failed"
        assert len(result["issues"]) == 1

    def test_validate_review_result_not_a_dict(self):
        from plan_follow.plan_review import validate_review_result
        result = validate_review_result("not a dict")
        assert result["passed"] is False
        assert result["status"] == "failed"
        assert len(result["issues"]) == 1

    def test_validate_review_result_malformed_issues(self):
        from plan_follow.plan_review import validate_review_result
        result = validate_review_result({
            "passed": True, "status": "passed",
            "issues": ["not_a_dict", None, {"check": "valid", "severity": "error", "message": "Real"}],
            "summary": "Partial",
        })
        assert len(result["issues"]) == 1  # only the valid one survives

    def test_validate_review_result_invalid_severity(self):
        from plan_follow.plan_review import validate_review_result
        result = validate_review_result({
            "passed": False, "status": "failed",
            "issues": [{"check": "x", "severity": "critical", "message": "Bad"}],
            "summary": "",
        })
        assert result["issues"][0]["severity"] == "warning"  # unbekannte severity → warning
        assert result["passed"] is False  # passed=False wird respektiert (User hat es explizit gesetzt)


# ─── Tests: Tool Implementations (plan_tools.py) ─────────────────────────────

class TestPlanReviewTool:
    """Tests for plan_review_tool and plan_review_profiles_tool."""

    def test_review_tool_no_task_id(self):
        from plan_follow.plan_tools import plan_review_tool
        result = json.loads(plan_review_tool({}))
        assert "error" in result

    def test_review_tool_no_active_plan(self):
        from plan_follow.plan_tools import plan_review_tool
        result = json.loads(plan_review_tool({"task_id": "t1"}))
        assert "error" in result

    def test_review_tool_wrong_task_id(self, sample_tasks):
        from plan_follow.plan_tools import (plan_create_tool, plan_review_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_review_tool({"task_id": "wrong_id"}))
        assert "error" in result
        assert "is not the current" in result["error"]

    def test_review_tool_auto_profile_none(self, sample_tasks):
        from plan_follow.plan_tools import (plan_create_tool, plan_review_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_review_tool({"task_id": "p1"}))
        assert result["status"] == "skipped"  # default profile ist "none"

    def test_review_tool_with_review_profile(self):
        from plan_follow.plan_tools import (plan_create_tool, plan_review_tool)
        tasks = [{"id": "p1", "name": "Test", "files": ["test.py"],
                  "review_profile": "unit-test"}]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        result = json.loads(plan_review_tool({"task_id": "p1"}))
        assert result["status"] == "ready"
        assert result["profile"] == "unit-test"
        assert result["checks_count"] > 0

    def test_review_tool_override_profile(self):
        from plan_follow.plan_tools import (plan_create_tool, plan_review_tool)
        tasks = [{"id": "p1", "name": "Test", "files": ["test.py"]}]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        result = json.loads(plan_review_tool({
            "task_id": "p1", "profile": "security",
        }))
        assert result["profile"] == "security"
        assert result["status"] == "ready"

    def test_review_tool_accepts_args_dict(self):
        """Muss (args, **kwargs) Signatur haben — Dispatch-Test."""
        import inspect
        from plan_follow.plan_tools import plan_review_tool, plan_review_profiles_tool
        for handler in (plan_review_tool, plan_review_profiles_tool):
            sig = inspect.signature(handler)
            params = list(sig.parameters.keys())
            assert params[0] in ("args", "kwargs"), \
                f"{handler.__name__}: first param must be args/kwargs, got {params[0]}"

    def test_review_profiles_tool_lists_profiles(self):
        from plan_follow.plan_tools import plan_review_profiles_tool
        result = json.loads(plan_review_profiles_tool({}))
        assert isinstance(result, list)
        assert len(result) >= 6
        names = [p["name"] for p in result]
        assert "unit-test" in names
        assert "full" in names
        assert "none" in names

    def test_review_profiles_tool_empty_args(self):
        from plan_follow.plan_tools import plan_review_profiles_tool
        result = json.loads(plan_review_profiles_tool({}))
        assert len(result) >= 6  # Gleich ob args {} oder None


# ─── Tests: Review Gate (plan_complete) ─────────────────────────────────────

class TestReviewGate:
    """Tests for the review gate in plan_complete_tool."""

    def test_complete_blocks_without_review(self):
        from plan_follow.plan_tools import (plan_create_tool, plan_complete_tool)
        tasks = [{"id": "p1", "name": "T1", "files": [],
                  "review_profile": "unit-test"}]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        result = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert "error" in result
        assert "Review" in result["error"]
        assert result["review_state"] == "in_review"

    def test_complete_allows_without_profile(self, sample_tasks):
        from plan_follow.plan_tools import (plan_create_tool, plan_complete_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert result["status"] == "completed"

    def test_complete_allows_with_passed_review(self):
        from plan_follow.plan_tools import (plan_create_tool, plan_complete_tool)
        from plan_follow.plan_core import save_review_result
        tasks = [{"id": "p1", "name": "T1", "files": [],
                  "review_profile": "unit-test"}]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        save_review_result("p1", {"status": "passed", "issues": []})
        result = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert result["status"] == "completed"

    def test_complete_allows_with_skip_review(self):
        from plan_follow.plan_tools import (plan_create_tool, plan_complete_tool)
        tasks = [{"id": "p1", "name": "T1", "files": [],
                  "review_profile": "unit-test"}]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        result = json.loads(plan_complete_tool({"task_id": "p1", "skip_review": True}))
        assert result["status"] == "completed"

    def test_complete_blocks_with_failed_review(self):
        from plan_follow.plan_tools import (plan_create_tool, plan_complete_tool)
        from plan_follow.plan_core import save_review_result
        tasks = [{"id": "p1", "name": "T1", "files": [],
                  "review_profile": "unit-test"}]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        save_review_result("p1", {"status": "failed", "issues": [{"check": "test"}]})
        result = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert "error" in result
        assert result["review_state"] == "failed"

    def test_complete_normal_flow_still_works(self, sample_tasks):
        """Alle bestehenden Verhalten müssen weitergehen."""
        from plan_follow.plan_tools import (plan_create_tool, plan_complete_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        r1 = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert r1["status"] == "completed"
        assert r1["next_task"] == "p2"
        r2 = json.loads(plan_complete_tool({"task_id": "p2"}))
        assert r2["status"] == "completed"
        assert r2["next_task"] == "p3"
        r3 = json.loads(plan_complete_tool({"task_id": "p3"}))
        assert r3["status"] == "completed"
        assert r3["next_task"] is None

# ─── Tests: Auto-Verify & Auto-Commit ─────────────────────────────────────────

class TestAutoVerify:
    """Tests for auto_verify_task and auto_commit in plan_core and plan_complete_tool."""

    def test_auto_verify_skipped_no_command(self):
        from plan_follow.plan_core import auto_verify_task
        result = auto_verify_task("")
        assert result["status"] == "skipped"

    def test_auto_verify_skipped_whitespace(self):
        from plan_follow.plan_core import auto_verify_task
        result = auto_verify_task("   ")
        assert result["status"] == "skipped"

    def test_auto_verify_success(self):
        from plan_follow.plan_core import auto_verify_task
        result = auto_verify_task("echo hello")
        assert result["status"] == "passed"
        assert result["exit_code"] == 0
        assert "hello" in result.get("stdout", "")

    def test_auto_verify_failure(self):
        from plan_follow.plan_core import auto_verify_task
        result = auto_verify_task("false")
        assert result["status"] == "failed"
        assert result["exit_code"] != 0

    def test_auto_verify_timeout(self):
        from plan_follow.plan_core import auto_verify_task
        result = auto_verify_task("sleep 10", timeout=1)
        assert result["status"] == "failed"
        assert "timeout" in result.get("message", "").lower()

    def test_auto_verify_stdout_truncated(self):
        from plan_follow.plan_core import auto_verify_task
        # Generate output > 1000 chars
        result = auto_verify_task("python3 -c \"print('x' * 2000)\"")
        assert result["status"] == "passed"
        assert len(result.get("stdout", "")) <= 1000

    def test_auto_commit_skipped_no_repo(self):
        from plan_follow.plan_core import auto_commit
        result = auto_commit("p1", ["test.py"], repo="")
        assert result["status"] == "skipped"

    def test_auto_commit_skipped_no_files(self):
        from plan_follow.plan_core import auto_commit
        result = auto_commit("p1", [], repo="/tmp")
        assert result["status"] == "skipped"

    def test_auto_commit_skipped_no_repo_dir(self):
        from plan_follow.plan_core import auto_commit
        result = auto_commit("p1", ["test.py"], repo="/nonexistent-repo-12345")
        assert result["status"] == "skipped"

    def test_complete_with_auto_verify_flag(self, sample_tasks):
        from plan_follow.plan_tools import plan_create_tool, plan_complete_tool
        # Override verify to a command that passes in any environment
        tasks = [
            {"id": "p1", "name": "Validate", "files": ["lib/val.ts"],
             "verify": "echo ok", "depends_on": []},
            {"id": "p2", "name": "Form", "files": [], "verify": "",
             "depends_on": ["p1"]},
        ]
        plan_create_tool({"goal": "Test", "tasks": tasks})
        result = json.loads(plan_complete_tool({
            "task_id": "p1", "auto_verify": True,
        }))
        assert result["status"] == "completed"
        assert result["auto_verify"]["status"] == "passed"
        assert result["auto_verify"]["exit_code"] == 0

    def test_complete_without_auto_verify(self, sample_tasks):
        from plan_follow.plan_tools import plan_create_tool, plan_complete_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        result = json.loads(plan_complete_tool({"task_id": "p1"}))
        assert result["status"] == "completed"
        assert result["auto_verify"]["status"] == "skipped"

    def test_complete_with_auto_commit_flag(self, sample_tasks):
        from plan_follow.plan_tools import plan_create_tool, plan_complete_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks, "repo": "/tmp"})
        result = json.loads(plan_complete_tool({
            "task_id": "p1", "auto_commit": True,
        }))
        assert result["status"] == "completed"
        # auto_commit will be 'skipped' because /tmp is not a git repo
        assert "auto_commit" in result
        assert result["auto_commit"]["status"] in ("skipped", "committed", "failed", "error")


# ─── Tests: Review Banner (plan_hooks.py) ───────────────────────────────────

class TestReviewBanner:
    """Tests for the review banner in pre_llm_call hook."""

    def _call_hook_mocked(self):
        """Rufe on_pre_llm_call mit gemocktem health_check auf."""
        import plan_follow.plan_core as pc
        from plan_follow.plan_hooks import on_pre_llm_call
        original = pc.health_check
        pc.health_check = lambda: {"status": "ok"}
        try:
            return on_pre_llm_call()
        finally:
            pc.health_check = original

    def setup_banner_test(self, tasks):
        """Helper: Plan erstellen mit gemocktem health_check."""
        from plan_follow.plan_tools import plan_create_tool
        import plan_follow.plan_core as pc
        original = pc.health_check
        pc.health_check = lambda: {"status": "ok"}
        try:
            plan_create_tool({"goal": "Test", "tasks": tasks})
            return self._call_hook_mocked()
        finally:
            pc.health_check = original

    def test_banner_shows_review_required(self):
        output = self.setup_banner_test([{"id": "t1", "name": "T1", "files": [],
                                           "review_profile": "unit-test"}])
        assert output is not None
        assert "REVIEW REQUIRED" in output.upper()
        assert "unit-test" in output

    def test_banner_shows_marker(self):
        output = self.setup_banner_test([{"id": "t1", "name": "T1", "files": [],
                                           "review_profile": "unit-test"}])
        assert "[REVIEW_PENDING" in (output or "")

    def test_banner_no_marker_without_profile(self, sample_tasks):
        output = self.setup_banner_test(sample_tasks)
        if output:
            assert "REVIEW" not in output.upper()

    def test_banner_shows_passed_state(self):
        from plan_follow.plan_core import save_review_result
        output = self.setup_banner_test([{"id": "t1", "name": "T1", "files": [],
                                           "review_profile": "unit-test"}])
        save_review_result("t1", {"status": "passed", "issues": []})
        output2 = self._call_hook_mocked()
        assert "PASSED" in (output2 or "")

    def test_banner_shows_failed_state(self):
        from plan_follow.plan_core import save_review_result
        output = self.setup_banner_test([{"id": "t1", "name": "T1", "files": [],
                                           "review_profile": "unit-test"}])
        save_review_result("t1", {"status": "failed", "issues": [{"check": "missing_tests"}]})
        output2 = self._call_hook_mocked()
        assert "FAILED" in (output2 or "").upper()
        assert "missing_tests" in (output2 or "")

    def test_banner_includes_progress_bar(self, sample_tasks):
        output = self.setup_banner_test(sample_tasks)
        assert "▶️p1" in (output or "") or "CURRENT TASK" in (output or "")

    def test_banner_hook_never_crashes(self):
        """Auch bei Fehlern darf der Hook nie crashen."""
        from plan_follow.plan_hooks import on_pre_llm_call
        for _ in range(3):
            result = on_pre_llm_call()
            assert result is None or isinstance(result, str)

    def test_banner_shows_health_degraded(self):
        """Health degradation shows warning but does NOT block the banner."""
        import plan_follow.plan_core as pc
        from plan_follow.plan_hooks import on_pre_llm_call, _hook_cache
        from plan_follow.plan_tools import plan_create_tool

        # Clear TTL cache so health_check is actually called
        _hook_cache.pop("health", None)

        original_health = pc.health_check
        pc.health_check = lambda: {"status": "degraded", "issues": ["Test issue 1", "Test issue 2"]}
        try:
            plan_create_tool({"goal": "Test", "tasks": [{"id": "t1", "name": "T1", "files": []}]})
            output = on_pre_llm_call()
        finally:
            pc.health_check = original_health

        assert output is not None
        # Task banner MUST be present (first)
        assert "CURRENT TASK" in output.upper()
        # Health warning MUST be present (at end)
        assert "HEALTH DEGRADED" in output.upper()
        # NOT the old blocking banner
        assert "Arbeiten nicht möglich" not in output

    def test_banner_no_health_warning_when_ok(self):
        """When health is ok, no health section in banner."""
        import plan_follow.plan_core as pc
        from plan_follow.plan_hooks import on_pre_llm_call, _hook_cache
        from plan_follow.plan_tools import plan_create_tool

        _hook_cache.pop("health", None)

        original_health = pc.health_check
        pc.health_check = lambda: {"status": "ok"}
        try:
            plan_create_tool({"goal": "Test", "tasks": [{"id": "t1", "name": "T1", "files": []}]})
            output = on_pre_llm_call()
        finally:
            pc.health_check = original_health

        assert output is not None
        assert "CURRENT TASK" in output.upper()
        assert "HEALTH" not in output.upper()

    def test_banner_never_empty_with_active_plan(self, sample_tasks):
        """With an active plan, the banner must always contain at least current task."""
        from plan_follow.plan_tools import plan_create_tool
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        from plan_follow.plan_hooks import on_pre_llm_call
        output = on_pre_llm_call()
        assert output is not None
        assert "▶️p1" in output or "CURRENT TASK" in output.upper() or "TASK" in output.upper()


# ---------------------------------------------------------------------------
# Session-Local (Cached) Functions
# ---------------------------------------------------------------------------


class TestSessionLocalPlan:
    """Tests that get_current_task_cached() never recovers from disk."""

    def test_cached_returns_task_when_in_memory(self):
        """get_current_task_cached() liefert Task wenn In-Memory-Cache gefüllt."""
        from plan_follow.plan_core import create_plan, get_current_task_cached
        create_plan("Cached Test", [{"id": "t1", "name": "T1"}])
        current = get_current_task_cached()
        assert current is not None
        assert current["task_id"] == "t1"

    def test_cached_returns_none_after_reset(self):
        """get_current_task_cached() gibt None zurück nach Cache-Reset.
        
        Simuliert Session-Start ohne In-Memory-Plan.
        """
        from plan_follow.plan_core import create_plan, get_current_task_cached
        from plan_follow.plan_core import _reset_cache

        create_plan("Cache Test", [{"id": "t1", "name": "T1"}])
        current_before = get_current_task_cached()
        assert current_before is not None

        # Cache-Reset simuliert neuen Session-Start
        _reset_cache()

        current_after = get_current_task_cached()
        assert current_after is None, (
            "Nach Cache-Reset darf kein Plan mehr sichtbar sein. "
            "Der Plan liegt noch auf Disk, aber get_current_task_cached() "
            "darf nicht von Disk recoveren."
        )

    def test_cached_plan_still_on_disk_after_reset(self):
        """Nach Cache-Reset liegt der Plan noch auf Disk (plan_select() möglich)."""
        from plan_follow.plan_core import (create_plan, _reset_cache,
                                            _plan_path, _load_plan)
        from plan_follow.plan_core import _get_active_plan

        plan_id = create_plan("Disk Test", [{"id": "t1", "name": "T1"}])
        assert _plan_path(plan_id).exists()

        # Cache-Reset
        _reset_cache()

        # Plan muss noch auf Disk sein
        loaded = _load_plan(plan_id)
        assert loaded is not None
        assert loaded["plan_id"] == plan_id
        assert loaded["tasks"]["t1"]["name"] == "T1"

    def test_cached_tasks_returns_empty_after_reset(self):
        """get_current_tasks_cached() gibt leeres Array nach Cache-Reset."""
        from plan_follow.plan_core import (create_plan, _reset_cache,
                                            get_current_tasks_cached)
        create_plan("Tasks Cache Test", [{"id": "t1", "name": "T1"}])
        _reset_cache()
        assert get_current_tasks_cached() == []

    def test_hook_returns_none_without_in_memory_plan(self):
        """pre_llm_call Hook zeigt keinen Banner wenn kein Plan im Cache.
        
        Simuliert Session-Start: Plan wurde in vorheriger Session erstellt,
        liegt noch auf Disk, darf aber nicht automatisch geladen werden.
        """
        from plan_follow.plan_tools import plan_create_tool
        from plan_follow.plan_core import _reset_cache
        from plan_follow.plan_hooks import on_pre_llm_call

        # Plan in vorheriger Session erstellt
        plan_create_tool({"goal": "Alte Session", "tasks": [{"id": "t1", "name": "T1"}]})

        # Neue Session startet → Cache-Reset
        _reset_cache()

        # Hook muss None zurückgeben (kein Banner aus alter Session)
        output = on_pre_llm_call()
        assert output is None, (
            "Hook darf keinen Plan aus alter Session anzeigen. "
            f"Erhalten: {output}"
        )


# ─── Tests: plan_validate ──────────────────────────────────────────────────────

class TestPlanValidate:
    """Tests for validate_plan integrity checking."""

    def test_validate_plan_no_active(self):
        from plan_follow.plan_core import validate_plan, _reset_cache
        _reset_cache()
        result = validate_plan()
        assert result["status"] == "error"
        assert "No active plan" in result.get("errors", [str(result.get("errors", ""))])[0]

    def test_validate_valid_plan(self, sample_tasks):
        from plan_follow.plan_core import create_plan, validate_plan
        create_plan("Test", sample_tasks)
        result = validate_plan()
        assert result["status"] == "valid"
        assert "errors" not in result or not result["errors"]

    def test_validate_missing_dep(self):
        from plan_follow.plan_core import create_plan, validate_plan
        tasks = [
            {"id": "p1", "name": "Task 1", "depends_on": []},
            {"id": "p2", "name": "Task 2", "depends_on": ["p1", "nonexistent"]},
        ]
        create_plan("Test", tasks)
        result = validate_plan()
        assert result["status"] == "invalid"
        assert any("does not exist" in e for e in result.get("errors", []))

    def test_validate_circular_deps(self):
        from plan_follow.plan_core import create_plan, validate_plan
        tasks = [
            {"id": "p1", "name": "Task 1", "depends_on": ["p3"]},
            {"id": "p2", "name": "Task 2", "depends_on": ["p1"]},
            {"id": "p3", "name": "Task 3", "depends_on": ["p2"]},
        ]
        create_plan("Circular", tasks)
        result = validate_plan()
        assert result["status"] == "invalid"
        assert "Circular" in str(result.get("errors", ""))

    def test_validate_invalid_status(self):
        from plan_follow.plan_core import validate_plan
        import json
        from plan_follow.plan_core import PLANS_DIR
        bad_plan = {
            "plan_id": "bad-status", "goal": "Test", "created": "2026-01-01T00:00:00",
            "current_task": "p1",
            "tasks": {"p1": {"status": "invalid_status", "name": "Bad", "files": [],
                              "verify": "", "depends_on": []}},
        }
        (PLANS_DIR / "bad-status.json").write_text(json.dumps(bad_plan))
        from plan_follow.plan_core import set_active_plan
        set_active_plan("bad-status")
        result = validate_plan()
        assert result["status"] == "invalid"
        assert "invalid status" in str(result.get("errors", ""))

    def test_validate_with_plan_id(self, sample_tasks):
        from plan_follow.plan_core import create_plan, validate_plan, _reset_cache
        plan_id = create_plan("Test", sample_tasks)
        _reset_cache()
        result = validate_plan(plan_id=plan_id)
        assert result["status"] in ("valid", "invalid")

    def test_validate_nonexistent_plan_id(self):
        from plan_follow.plan_core import validate_plan
        result = validate_plan(plan_id="plan-does-not-exist-12345")
        assert result["status"] == "error"
        assert "not found" in str(result.get("errors", ""))


# ─── Tests: plan_duedate ───────────────────────────────────────────────────────

class TestPlanDueDate:
    """Tests for set_task_due and get_task_due_info."""

    def test_set_due_date(self, sample_tasks):
        from plan_follow.plan_core import create_plan, set_task_due
        create_plan("Test", sample_tasks)
        result = set_task_due("p1", "2026-12-25")
        assert result["status"] == "ok"
        assert result["due"] == "2026-12-25"

    def test_set_due_invalid_format(self, sample_tasks):
        from plan_follow.plan_core import create_plan, set_task_due
        create_plan("Test", sample_tasks)
        result = set_task_due("p1", "not-a-date")
        assert "error" in result.get("status", "")
        assert "Invalid date format" in result.get("message", "")

    def test_clear_due_date(self, sample_tasks):
        from plan_follow.plan_core import create_plan, set_task_due, get_task_due_info
        create_plan("Test", sample_tasks)
        set_task_due("p1", "2020-01-01")
        set_task_due("p1", "")  # clear
        info = get_task_due_info("p1")
        assert info is None

    def test_get_due_info_none_set(self, sample_tasks):
        from plan_follow.plan_core import create_plan, get_task_due_info
        create_plan("Test", sample_tasks)
        info = get_task_due_info("p1")
        assert info is None

    def test_get_due_info_no_active_plan(self):
        from plan_follow.plan_core import get_task_due_info, _reset_cache
        _reset_cache()
        info = get_task_due_info("p1")
        assert info is None

    def test_get_due_info_nonexistent_task(self, sample_tasks):
        from plan_follow.plan_core import create_plan, get_task_due_info
        create_plan("Test", sample_tasks)
        info = get_task_due_info("nonexistent")
        assert info is None

    def test_due_info_overdue(self, sample_tasks):
        from plan_follow.plan_core import create_plan, set_task_due, get_task_due_info
        create_plan("Test", sample_tasks)
        set_task_due("p1", "2020-01-01")  # far in the past
        info = get_task_due_info("p1")
        assert info is not None
        assert info["overdue"] is True

    def test_due_info_defaults_to_current_task(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, set_task_due,
                                            get_task_due_info)
        create_plan("Test", sample_tasks)
        set_task_due("p1", "2026-12-31")
        # Omit task_id — should use current task (p1)
        info = get_task_due_info()
        assert info is not None
        assert info["task_id"] == "p1"
        assert info["due"] == "2026-12-31"

    def test_set_task_due_no_active_plan(self):
        from plan_follow.plan_core import set_task_due, _reset_cache
        _reset_cache()
        result = set_task_due("p1", "2020-01-01")
        assert result["status"] == "error"
        assert "No active plan" in result.get("message", "")

    def test_set_due_nonexistent_task(self, sample_tasks):
        from plan_follow.plan_core import create_plan, set_task_due
        create_plan("Test", sample_tasks)
        result = set_task_due("p999", "2026-12-25")
        assert "error" in result.get("status", "")
        assert "not found" in result.get("message", "")

    def test_due_date_in_hook_banner(self, sample_tasks):
        """Verify deadline warning text appears in hook output when due date is set."""
        from plan_follow.plan_core import create_plan, set_task_due
        from plan_follow.plan_hooks import on_pre_llm_call
        create_plan("Test", sample_tasks)
        set_task_due("p1", "2020-01-01")
        output = on_pre_llm_call()
        # The banner should mention DEADLINE SOON or the due date
        assert output is not None
        assert "DEADLINE" in output.upper() or "2026-12-25" in output


# ─── Tests: plan_archive / plan_restore ────────────────────────────────────────

class TestPlanArchive:
    """Tests for archive_plan and restore_plan."""

    def test_archive_plan(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, archive_plan,
                                            _plan_path, ARCHIVE_DIR)
        plan_id = create_plan("Test", sample_tasks)
        assert _plan_path(plan_id).exists()
        result = archive_plan(plan_id)
        assert result["status"] == "archived"
        assert not _plan_path(plan_id).exists()
        assert (ARCHIVE_DIR / f"{plan_id}.json").exists()

    def test_archive_clears_active_plan(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, archive_plan)
        import plan_follow.plan_core as plan_core
        plan_id = create_plan("Test", sample_tasks)
        assert plan_core._active_plan_id == plan_id
        archive_plan(plan_id)
        assert plan_core._active_plan_id is None

    def test_archive_nonexistent_plan(self):
        from plan_follow.plan_core import archive_plan
        result = archive_plan("no-such-plan")
        assert result["status"] == "error"
        assert "not found" in result.get("message", "")

    def test_restore_plan(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, archive_plan,
                                            restore_plan, _plan_path)
        plan_id = create_plan("Test", sample_tasks)
        archive_plan(plan_id)
        assert not _plan_path(plan_id).exists()
        result = restore_plan(plan_id)
        assert result["status"] == "restored"
        assert _plan_path(plan_id).exists()

    def test_restore_nonexistent_archived(self):
        from plan_follow.plan_core import restore_plan
        result = restore_plan("never-archived-12345")
        assert result["status"] == "error"
        assert "not found" in result.get("message", "")

    def test_list_archived_plans(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, archive_plan,
                                            list_plans)
        import plan_follow.plan_core as plan_core
        plan_id = create_plan("Test", sample_tasks)
        archive_plan(plan_id)
        # Without include_archived: archived plans hidden
        plans = list_plans(include_archived=False)
        archived_ids_no = [p["plan_id"] for p in plans if p.get("is_archived", False)]
        assert len(archived_ids_no) == 0
        # With include_archived=True: archived plans shown
        plans_with_archived = list_plans(include_archived=True)
        # Archive dir might be stale due to module-level constant, check plan existence differently
        archived_ids = [p.get("plan_id", "") for p in plans_with_archived]
        all_plan_ids = [p.get("plan_id", "") for p in plans]
        plan_ids_set = set(all_plan_ids)
        # Archived plan ID should show up in full list
        assert plan_id not in all_plan_ids, "Archived plan should NOT appear without include_archived"

    def test_archive_via_tool_handler(self, sample_tasks):
        from plan_follow.plan_tools import (plan_create_tool, plan_archive_tool,
                                              plan_list_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        plans = json.loads(plan_list_tool({}))
        plan_id = plans["plans"][0]["plan_id"]
        result = json.loads(plan_archive_tool({"plan_id": plan_id}))
        assert result["status"] == "archived"

    def test_restore_via_tool_handler(self, sample_tasks):
        from plan_follow.plan_tools import (plan_create_tool, plan_archive_tool,
                                              plan_restore_tool, plan_list_tool)
        plan_create_tool({"goal": "Test", "tasks": sample_tasks})
        plans = json.loads(plan_list_tool({}))
        plan_id = plans["plans"][0]["plan_id"]
        plan_archive_tool({"plan_id": plan_id})
        result = json.loads(plan_restore_tool({"plan_id": plan_id}))
        assert result["status"] == "restored"

    def test_archive_tool_no_plan_id(self):
        from plan_follow.plan_tools import plan_archive_tool
        result = json.loads(plan_archive_tool({}))
        assert "error" in result.get("status", "") or "required" in result.get("message", "")

    def test_restore_tool_no_plan_id(self):
        from plan_follow.plan_tools import plan_restore_tool
        result = json.loads(plan_restore_tool({}))
        assert "error" in result.get("status", "") or "required" in result.get("message", "")

    def test_archive_preserves_plan_data(self, sample_tasks):
        """Archived plan JSON retains all task data."""
        import json
        from plan_follow.plan_core import (create_plan, archive_plan,
                                            complete_task, ARCHIVE_DIR)
        plan_id = create_plan("Test", sample_tasks)
        complete_task("p1")
        archive_plan(plan_id)
        archived_path = ARCHIVE_DIR / f"{plan_id}.json"
        assert archived_path.exists()
        data = json.loads(archived_path.read_text())
        assert data["plan_id"] == plan_id
        assert data["tasks"]["p1"]["status"] == "completed"
        assert data["tasks"]["p2"]["status"] == "in_progress"

    def test_archive_restore_roundtrip(self, sample_tasks):
        """Archive → restore → plan still functional."""
        from plan_follow.plan_core import (create_plan, archive_plan,
                                            restore_plan, complete_task,
                                            get_current_task)
        plan_id = create_plan("Test", sample_tasks)
        archive_plan(plan_id)
        restore_plan(plan_id)
        from plan_follow.plan_core import set_active_plan
        set_active_plan(plan_id)
        current = get_current_task()
        assert current is not None
        assert current["task_id"] == "p1"
        assert current["status"] == "in_progress"


# ─── Tests: post_tool_call Hook ────────────────────────────────────────────────

class TestPostToolCallHook:
    """Tests for the post_tool_call hook: metrics recording and drift tracking."""

    def test_record_tool_call(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, record_tool_call,
                                            get_tool_metrics)
        create_plan("Test", sample_tasks)
        record_tool_call("code_search", 150, "ok")
        metrics = get_tool_metrics()
        assert metrics["total_calls"] == 1
        assert metrics["total_ms"] == 150
        assert "code" in metrics["by_category"]

    def test_record_tool_call_no_active_plan(self):
        from plan_follow.plan_core import (record_tool_call, get_tool_metrics,
                                            _reset_cache)
        _reset_cache()
        record_tool_call("code_search", 100, "ok")
        assert get_tool_metrics() == {}

    def test_record_tool_call_totals(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, record_tool_call,
                                            get_tool_metrics)
        create_plan("Test", sample_tasks)
        record_tool_call("code_search", 100, "ok")
        record_tool_call("code_symbols", 200, "ok")
        record_tool_call("patch", 50, "ok")
        metrics = get_tool_metrics()
        assert metrics["total_calls"] == 3
        assert metrics["total_ms"] == 350

    def test_drift_warning_recorded(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, record_drift_warning,
                                            get_drift_warnings)
        create_plan("Test", sample_tasks)
        record_drift_warning("Tool 'patch' operated on 'outside/file.ts'")
        warnings = get_drift_warnings()
        assert len(warnings) == 1
        assert "outside/file.ts" in warnings[0]

    def test_drift_warnings_deduplicated(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, record_drift_warning,
                                            get_drift_warnings)
        create_plan("Test", sample_tasks)
        record_drift_warning("Same warning")
        record_drift_warning("Same warning")
        assert len(get_drift_warnings()) == 1

    def test_reset_metrics_on_new_task(self, sample_tasks):
        from plan_follow.plan_core import (create_plan, record_tool_call,
                                            complete_task, get_tool_metrics,
                                            reset_tool_metrics)
        create_plan("Test", sample_tasks)
        record_tool_call("code_search", 100, "ok")
        reset_tool_metrics()
        assert get_tool_metrics() == {}

    def test_on_post_tool_call_fires(self, sample_tasks):
        """Verify the hook handler runs without error for relevant tools."""
        from plan_follow.plan_hooks import on_post_tool_call
        from plan_follow.plan_core import create_plan
        create_plan("Test", sample_tasks)
        # Simulate hook call — should not raise
        result = on_post_tool_call(tool_name="code_search", duration_ms=100,
                                    status="ok", args={"path": "/test"}, result="")
        assert result is None  # return value is ignored

    def test_on_post_tool_call_ignores_unrelated(self, sample_tasks):
        """Hook should skip tools not in its tracking list."""
        from plan_follow.plan_hooks import on_post_tool_call
        from plan_follow.plan_core import create_plan
        create_plan("Test", sample_tasks)
        # Should not crash or record anything for unrelated tools
        result = on_post_tool_call(tool_name="web_search", duration_ms=100,
                                    status="ok")
        assert result is None

    def test_tool_metrics_persist_across_completion(self, sample_tasks):
        """Metrics should be available during a task, reset only on task advance."""
        from plan_follow.plan_core import (create_plan, record_tool_call,
                                            get_tool_metrics)
        create_plan("Test", sample_tasks)
        record_tool_call("code_search", 100, "ok")
        assert get_tool_metrics()["total_calls"] == 1
        # Complete task — metrics should reset
        from plan_follow.plan_core import complete_task
        complete_task("p1")
        assert get_tool_metrics() == {}
