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
        assert "nicht gefunden" in str(result.get("message", ""))

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
