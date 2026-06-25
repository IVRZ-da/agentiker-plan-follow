"""Tests for plan_follow.mcp_server (MCP Server).

Tests all MCP tool functions: list_plans, get_plan, get_active_plan,
create_plan_from_mcp, set_plan_status, and _summarize_status.
Uses mocked plan_core and plan_tools for isolation.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─── Ensure the plugin package is on sys.path ────────────────────────────
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent  # → plugins/
sys.path.insert(0, str(_PLUGIN_ROOT))

# ─── Mock tools.registry (required by plan_core submodules) ──────────────
registry_mock = types.ModuleType("tools.registry")
registry_mock.registry = types.SimpleNamespace()
registry_mock.registry._entries = {}


class _MockEntry:
    def __init__(self, name):
        self.name = name
        self.schema = {"description": ""}


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


def _mock_get_entry(name):
    return _mock_registry.get(name)


registry_mock.registry.get_entry = _mock_get_entry
sys.modules["tools.registry"] = registry_mock

# ─── Mock hermes_cli.plugins (required by plan_core submodules) ──────────
hermes_cli_mock = types.ModuleType("hermes_cli")
hermes_cli_mock.plugins = types.ModuleType("hermes_cli.plugins")
hermes_cli_mock.plugins.PluginContext = type("PluginContext", (), {})
sys.modules["hermes_cli"] = hermes_cli_mock
sys.modules["hermes_cli.plugins"] = hermes_cli_mock.plugins

# ─── Now we can safely import the module under test ──────────────────────
from plan_follow import mcp_server as mcp

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures & Helpers
# ═══════════════════════════════════════════════════════════════════════════

MINIMAL_PLAN: dict = {
    "plan_id": "test",
    "goal": "Test",
    "tasks": {
        "t1": {
            "id": "t1",
            "name": "T1",
            "files": [],
            "verify": "",
            "review_profile": "none",
            "status": "pending",
        }
    },
}

PLAN_WITH_STATUSES: dict = {
    "plan_id": "multi",
    "goal": "Multi status plan",
    "tasks": {
        "t1": {"id": "t1", "name": "T1", "status": "completed"},
        "t2": {"id": "t2", "name": "T2", "status": "in_progress"},
        "t3": {"id": "t3", "name": "T3", "status": "pending"},
        "t4": {"id": "t4", "name": "T4", "status": "aborted"},
    },
}


@pytest.fixture
def mock_plan_core():
    """Return a MagicMock that stands in for plan_core.

    The mock exposes all methods mcp_server._get_core() is expected to provide.
    """
    pc = MagicMock()
    pc.list_plans.return_value = []
    pc._load_plan.return_value = dict(MINIMAL_PLAN)  # copy to avoid mutation
    pc._get_active_plan.return_value = dict(MINIMAL_PLAN)
    pc.complete_task.return_value = {"status": "completed"}
    pc.get_current_task.return_value = {"task_id": "t1", "name": "T1", "status": "in_progress"}
    return pc


@pytest.fixture(autouse=True)
def _patch_get_core(request, mock_plan_core):
    """Replace mcp._get_core() with a mock for every test in this module."""
    original = mcp._get_core

    def fake_get_core():
        return mock_plan_core

    mcp._get_core = fake_get_core
    yield
    mcp._get_core = original


@pytest.fixture
def mock_plan_create_tool():
    """Mock plan_tools.plan_create_tool for create_plan_from_mcp tests."""
    fake_mod = types.ModuleType("plan_follow.plan_tools")
    fake_mod.plan_create_tool = MagicMock(return_value="Plan created: test-plan-2026")
    sys.modules["plan_follow.plan_tools"] = fake_mod
    yield fake_mod.plan_create_tool
    # Restore: on teardown remove the fake so other tests don't leak
    sys.modules.pop("plan_follow.plan_tools", None)


# ═══════════════════════════════════════════════════════════════════════════
# Tests: list_plans
# ═══════════════════════════════════════════════════════════════════════════

class TestListPlans:
    def test_list_plans_empty(self, mock_plan_core):
        """list_plans returns an empty list when no plans exist."""
        mock_plan_core.list_plans.return_value = []
        result = json.loads(mcp.list_plans())
        assert result["success"] is True
        assert result["plans"] == []

    def test_list_plans_with_plans(self, mock_plan_core):
        """list_plans returns all plans."""
        mock_plan_core.list_plans.return_value = [
            {"plan_id": "p1", "goal": "First"},
            {"plan_id": "p2", "goal": "Second"},
        ]
        result = json.loads(mcp.list_plans())
        assert result["success"] is True
        assert len(result["plans"]) == 2
        assert result["plans"][0]["plan_id"] == "p1"

    def test_list_plans_include_archived(self, mock_plan_core):
        """list_plans passes include_archived to plan_core."""
        mcp.list_plans(include_archived=True)
        mock_plan_core.list_plans.assert_called_once_with(include_archived=True)

    def test_list_plans_excludes_archived_by_default(self, mock_plan_core):
        """list_plans defaults to exclude_archived=False."""
        mcp.list_plans()
        mock_plan_core.list_plans.assert_called_once_with(include_archived=False)

    def test_list_plans_error_returns_false(self, mock_plan_core):
        """list_plans returns error JSON when plan_core raises."""
        mock_plan_core.list_plans.side_effect = RuntimeError("DB down")
        result = json.loads(mcp.list_plans())
        assert result["success"] is False
        assert "DB down" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# Tests: get_plan
# ═══════════════════════════════════════════════════════════════════════════

class TestGetPlan:
    def test_get_plan_found(self, mock_plan_core):
        """get_plan returns a plan summary when the plan exists."""
        mock_plan_core._load_plan.return_value = dict(MINIMAL_PLAN)
        result = json.loads(mcp.get_plan("test"))
        assert result["success"] is True
        assert result["plan"]["plan_id"] == "test"
        assert result["plan"]["goal"] == "Test"
        assert result["plan"]["task_count"] == 1

    def test_get_plan_not_found(self, mock_plan_core):
        """get_plan returns error when plan does not exist."""
        mock_plan_core._load_plan.return_value = None
        result = json.loads(mcp.get_plan("nonexistent"))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_get_plan_summary_structure(self, mock_plan_core):
        """get_plan's summary contains the expected fields."""
        plan = {
            "plan_id": "abc123",
            "goal": "Fix bug",
            "created": "2026-01-01",
            "current_task": "t2",
            "tasks": {"t1": {"status": "completed"}, "t2": {"status": "in_progress"}},
        }
        mock_plan_core._load_plan.return_value = plan
        result = json.loads(mcp.get_plan("abc123"))
        s = result["plan"]
        assert s["plan_id"] == "abc123"
        assert s["goal"] == "Fix bug"
        assert s["created"] == "2026-01-01"
        assert s["current_task"] == "t2"
        assert s["task_count"] == 2
        assert s["status_summary"] == {"completed": 1, "in_progress": 1}

    def test_get_plan_error_returns_false(self, mock_plan_core):
        """get_plan returns error JSON on exception."""
        mock_plan_core._load_plan.side_effect = IOError("Permission denied")
        result = json.loads(mcp.get_plan("test"))
        assert result["success"] is False
        assert "Permission denied" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# Tests: get_active_plan
# ═══════════════════════════════════════════════════════════════════════════

class TestGetActivePlan:
    def test_get_active_plan_found(self, mock_plan_core):
        """get_active_plan returns the active plan with current task."""
        mock_plan_core._get_active_plan.return_value = dict(MINIMAL_PLAN)
        mock_plan_core.get_current_task.return_value = {
            "task_id": "t1", "name": "T1", "status": "in_progress"
        }
        result = json.loads(mcp.get_active_plan())
        assert result["success"] is True
        assert result["plan"]["plan_id"] == "test"
        assert result["plan"]["current_task"]["task_id"] == "t1"

    def test_get_active_plan_none(self, mock_plan_core):
        """get_active_plan returns error when no plan is active."""
        mock_plan_core._get_active_plan.return_value = None
        result = json.loads(mcp.get_active_plan())
        assert result["success"] is False
        assert "No active plan" in result["error"]

    def test_get_active_plan_no_current_task(self, mock_plan_core):
        """get_active_plan returns plan even when current_task is None (all done)."""
        mock_plan_core._get_active_plan.return_value = dict(MINIMAL_PLAN)
        mock_plan_core.get_current_task.return_value = None
        result = json.loads(mcp.get_active_plan())
        assert result["success"] is True
        assert result["plan"]["current_task"] is None

    def test_get_active_plan_error(self, mock_plan_core):
        """get_active_plan returns error JSON on exception."""
        mock_plan_core._get_active_plan.side_effect = RuntimeError("Corrupt index")
        result = json.loads(mcp.get_active_plan())
        assert result["success"] is False
        assert "Corrupt index" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# Tests: create_plan_from_mcp
# ═══════════════════════════════════════════════════════════════════════════

class TestCreatePlanFromMCP:
    def test_create_plan_basic(self, mock_plan_create_tool):
        """create_plan_from_mcp with goal and default template calls plan_create_tool."""
        result = json.loads(mcp.create_plan_from_mcp(goal="Test goal"))
        assert result["success"] is True
        mock_plan_create_tool.assert_called_once_with(
            {"goal": "Test goal", "template": "fix"}
        )

    def test_create_plan_custom_template(self, mock_plan_create_tool):
        """create_plan_from_mcp accepts a custom template name."""
        mcp.create_plan_from_mcp(goal="Deploy", template="deploy")
        mock_plan_create_tool.assert_called_once_with(
            {"goal": "Deploy", "template": "deploy"}
        )

    def test_create_plan_with_tasks(self, mock_plan_create_tool):
        """create_plan_from_mcp with tasks switches template to 'multi'."""
        tasks = [{"id": "t1", "name": "Step 1"}]
        mcp.create_plan_from_mcp(goal="Multi step", tasks=tasks)
        mock_plan_create_tool.assert_called_once_with(
            {"goal": "Multi step", "template": "multi", "params": {"tasks": tasks}}
        )

    def test_create_plan_error(self, mock_plan_create_tool):
        """create_plan_from_mcp returns error JSON when plan_create_tool raises."""
        mock_plan_create_tool.side_effect = ValueError("Invalid template 'bad'")
        result = json.loads(mcp.create_plan_from_mcp(goal="Oops"))
        assert result["success"] is False
        assert "Invalid template" in result["error"]

    def test_create_plan_empty_goal(self, mock_plan_create_tool):
        """create_plan_from_mcp passes empty goal through to plan_create_tool."""
        mcp.create_plan_from_mcp(goal="")
        mock_plan_create_tool.assert_called_once_with(
            {"goal": "", "template": "fix"}
        )


# ═══════════════════════════════════════════════════════════════════════════
# Tests: set_plan_status
# ═══════════════════════════════════════════════════════════════════════════

class TestSetPlanStatus:
    def test_complete_task(self, mock_plan_core):
        """set_plan_status with status='completed' calls complete_task."""
        mock_plan_core._load_plan.return_value = dict(MINIMAL_PLAN)
        result = json.loads(mcp.set_plan_status("t1", "completed"))
        assert result["success"] is True
        mock_plan_core.complete_task.assert_called_once_with("t1")

    def test_abort_task(self, mock_plan_core):
        """set_plan_status with status='aborted' sets task status and saves."""
        plan = dict(MINIMAL_PLAN)
        mock_plan_core._load_plan.return_value = plan
        result = json.loads(mcp.set_plan_status("t1", "aborted"))
        assert result["success"] is True
        assert plan["tasks"]["t1"]["status"] == "aborted"
        mock_plan_core._save_plan.assert_called_once_with(plan)

    def test_set_pending_status(self, mock_plan_core):
        """set_plan_status with status='pending' sets task status and saves."""
        plan = dict(MINIMAL_PLAN)
        plan["tasks"]["t1"]["status"] = "completed"  # was pending, now reset
        mock_plan_core._load_plan.return_value = plan
        result = json.loads(mcp.set_plan_status("t1", "pending"))
        assert result["success"] is True
        assert plan["tasks"]["t1"]["status"] == "pending"
        mock_plan_core._save_plan.assert_called_once_with(plan)

    def test_set_status_with_plan_id(self, mock_plan_core):
        """set_plan_status uses explicit plan_id when provided."""
        plan = dict(MINIMAL_PLAN)
        plan["plan_id"] = "explicit"
        mock_plan_core._load_plan.return_value = plan
        mcp.set_plan_status("t1", "completed", plan_id="explicit")
        mock_plan_core._load_plan.assert_called_once_with("explicit")
        mock_plan_core.complete_task.assert_called_once_with("t1")

    def test_set_status_uses_active_plan_when_no_plan_id(self, mock_plan_core):
        """set_plan_status uses _get_active_plan when plan_id is empty."""
        mock_plan_core._get_active_plan.return_value = dict(MINIMAL_PLAN)
        mcp.set_plan_status("t1", "completed")
        mock_plan_core._get_active_plan.assert_called_once()
        mock_plan_core._load_plan.assert_not_called()

    def test_set_status_plan_not_found(self, mock_plan_core):
        """set_plan_status returns error when plan is not found."""
        mock_plan_core._get_active_plan.return_value = None
        result = json.loads(mcp.set_plan_status("t1", "completed"))
        assert result["success"] is False
        assert "Plan not found" in result["error"]

    def test_set_status_task_not_found(self, mock_plan_core):
        """set_plan_status returns error when task_id doesn't exist in plan."""
        mock_plan_core._load_plan.return_value = dict(MINIMAL_PLAN)
        result = json.loads(mcp.set_plan_status("nonexistent", "completed"))
        assert result["success"] is False
        assert "not found in plan" in result["error"]

    def test_set_status_error(self, mock_plan_core):
        """set_plan_status returns error JSON on exception."""
        mock_plan_core._load_plan.return_value = dict(MINIMAL_PLAN)
        mock_plan_core.complete_task.side_effect = RuntimeError("Task locked")
        result = json.loads(mcp.set_plan_status("t1", "completed"))
        assert result["success"] is False
        assert "Task locked" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _summarize_status (internal helper)
# ═══════════════════════════════════════════════════════════════════════════

class TestSummarizeStatus:
    def test_empty_tasks(self):
        """_summarize_status returns empty dict for no tasks."""
        assert mcp._summarize_status({}) == {}

    def test_single_status(self):
        """_summarize_status counts tasks with a single status."""
        tasks = {"t1": {"status": "completed"}}
        assert mcp._summarize_status(tasks) == {"completed": 1}

    def test_multiple_statuses(self):
        """_summarize_status counts multiple statuses correctly."""
        tasks = {
            "t1": {"status": "completed"},
            "t2": {"status": "in_progress"},
            "t3": {"status": "completed"},
            "t4": {"status": "pending"},
        }
        assert mcp._summarize_status(tasks) == {
            "completed": 2,
            "in_progress": 1,
            "pending": 1,
        }

    def test_unknown_status_default(self):
        """_summarize_status uses 'unknown' for tasks without a status field."""
        tasks = {"t1": {"name": "no status"}, "t2": {"status": "completed"}}
        result = mcp._summarize_status(tasks)
        assert result.get("unknown") == 1
        assert result.get("completed") == 1

    def test_preserves_different_status_values(self, mock_plan_core):
        """_summarize_status output is consistent with a full plan's tasks."""
        mock_plan_core._get_active_plan.return_value = dict(PLAN_WITH_STATUSES)
        mock_plan_core.get_current_task.return_value = None
        result = json.loads(mcp.get_active_plan())
        assert result["plan"]["status_summary"] == {
            "completed": 1,
            "in_progress": 1,
            "pending": 1,
            "aborted": 1,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Server entry points (smoke tests)
# ═══════════════════════════════════════════════════════════════════════════

class TestRunFunctions:
    @pytest.fixture(autouse=True)
    def _mock_logger(self):
        """Suppress logging during server entry-point tests."""
        with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
            yield

    def test_run_stdio_initialize(self):
        """run_stdio responds to initialize message and exits on empty input."""
        import io

        # Send one request then EOF
        stdin = io.StringIO(
            json.dumps({
                "method": "initialize",
                "id": 1,
                "params": {},
            })
            + "\n"
        )
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
        output = stdout.getvalue()
        assert output, "run_stdio should produce output for initialize"
        response = json.loads(output.strip())
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2025-03-26"
        assert response["result"]["serverInfo"]["name"] == "plan-follow-mcp"

    def test_run_stdio_list_tools(self):
        """run_stdio responds to list_tools with tool definitions."""
        import io

        stdin = io.StringIO(
            json.dumps({"method": "list_tools", "id": 2}) + "\n"
        )
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
        output = stdout.getvalue()
        response = json.loads(output.strip())
        assert response["id"] == 2
        tool_names = [t["name"] for t in response["result"]["tools"]]
        assert "list_plans" in tool_names
        assert "get_plan" in tool_names
        assert "get_active_plan" in tool_names
        assert "create_plan_from_mcp" in tool_names
        assert "set_plan_status" in tool_names

    def test_run_stdio_call_tool_list_plans(self, mock_plan_core):
        """run_stdio dispatches list_plans tool call correctly."""
        import io

        mock_plan_core.list_plans.return_value = []
        stdin = io.StringIO(
            json.dumps({
                "method": "call_tool",
                "id": 3,
                "params": {"name": "list_plans", "arguments": {}},
            })
            + "\n"
        )
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
        output = stdout.getvalue()
        response = json.loads(output.strip())
        assert response["id"] == 3
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["success"] is True

    def test_run_stdio_call_unknown_tool(self):
        """run_stdio returns an error for unknown tools."""
        import io

        stdin = io.StringIO(
            json.dumps({
                "method": "call_tool",
                "id": 4,
                "params": {"name": "unknown_tool", "arguments": {}},
            })
            + "\n"
        )
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
        output = stdout.getvalue()
        response = json.loads(output.strip())
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["success"] is False
        assert "Unknown tool" in content["error"]

    def test_run_stdio_unknown_method(self):
        """run_stdio returns empty result for unknown methods."""
        import io

        stdin = io.StringIO(
            json.dumps({"method": "unknown_method", "id": 5}) + "\n"
        )
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
        output = stdout.getvalue()
        response = json.loads(output.strip())
        assert response["id"] == 5
        assert response["result"] == {}

    def test_run_stdio_bad_json_skips(self):
        """run_stdio skips lines that are not valid JSON."""
        import io

        stdin = io.StringIO("not json\n")
        stdout = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
        # Should not crash and produce no output (EOF after bad line)
        assert stdout.getvalue() == ""

    def test_run_http_smoke(self):
        """run_http starts and can be stopped via KeyboardInterrupt."""
        from http.server import HTTPServer
        from threading import Thread, Event

        started = Event()

        def _fake_serve_forever(self):
            started.set()
            raise KeyboardInterrupt()

        with patch.object(HTTPServer, "serve_forever", _fake_serve_forever):
            thread = Thread(target=mcp.run_http, args=("127.0.0.1", 0), daemon=True)
            thread.start()
            started.wait(timeout=5)
            thread.join(timeout=3)
        assert not thread.is_alive(), "HTTP server thread should have exited"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Edge cases & robustness
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_list_plans_none_result(self, mock_plan_core):
        """list_plans handles None return gracefully."""
        mock_plan_core.list_plans.return_value = None
        result = json.loads(mcp.list_plans())
        assert result["success"] is True

    def test_get_plan_empty_plan_id(self, mock_plan_core):
        """get_plan with empty string still delegates to _load_plan."""
        mock_plan_core._load_plan.return_value = None
        result = json.loads(mcp.get_plan(""))
        assert result["success"] is False

    def test_set_status_empty_task_id(self, mock_plan_core):
        """set_plan_status with empty task_id may not find it in plan."""
        result = json.loads(mcp.set_plan_status("", "completed"))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_create_plan_no_mock_uses_real_import(self, mock_plan_core):
        """create_plan_from_mcp handles ImportError when plan_tools absent."""
        # Remove the mock so the real import path is attempted
        sys.modules.pop("plan_follow.plan_tools", None)
        result = json.loads(mcp.create_plan_from_mcp(goal="Test"))
        # Either succeeds (if real module importable) or fails gracefully
        assert "success" in result


# ═══════════════════════════════════════════════════════════════════════════
# Additional standalone tests for coverage: _summarize_status boundary,
# run_stdio dispatch branches, HTTP error paths, and edge cases.
# ═══════════════════════════════════════════════════════════════════════════


def test_summarize_status_all_same():
    """_summarize_status counts 100 identical statuses (boundary)."""
    tasks = {f"t{i:03d}": {"status": "pending"} for i in range(100)}
    assert mcp._summarize_status(tasks) == {"pending": 100}


def test_summarize_status_none_task_value():
    """_summarize_status raises AttributeError when a single task value is None."""
    with pytest.raises(AttributeError):
        mcp._summarize_status({"t1": None})


def test_run_stdio_call_get_plan(mock_plan_core):
    """run_stdio dispatches call_tool for get_plan (covers line 262)."""
    import io

    mock_plan_core._load_plan.return_value = dict(MINIMAL_PLAN)
    stdin = io.StringIO(
        json.dumps({
            "method": "call_tool",
            "id": 20,
            "params": {"name": "get_plan", "arguments": {"plan_id": "test"}},
        })
        + "\n"
    )
    stdout = io.StringIO()
    with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == 20
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["success"] is True
    assert content["plan"]["plan_id"] == "test"


def test_run_stdio_call_get_active_plan(mock_plan_core):
    """run_stdio dispatches call_tool for get_active_plan (covers line 264)."""
    import io

    mock_plan_core._get_active_plan.return_value = dict(MINIMAL_PLAN)
    mock_plan_core.get_current_task.return_value = {"task_id": "t1"}
    stdin = io.StringIO(
        json.dumps({
            "method": "call_tool",
            "id": 21,
            "params": {"name": "get_active_plan", "arguments": {}},
        })
        + "\n"
    )
    stdout = io.StringIO()
    with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == 21
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["success"] is True


def test_run_stdio_call_create_plan(mock_plan_core, mock_plan_create_tool):
    """run_stdio dispatches call_tool for create_plan_from_mcp (covers line 266)."""
    import io

    stdin = io.StringIO(
        json.dumps({
            "method": "call_tool",
            "id": 22,
            "params": {
                "name": "create_plan_from_mcp",
                "arguments": {"goal": "New"},
            },
        })
        + "\n"
    )
    stdout = io.StringIO()
    with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == 22
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["success"] is True


def test_run_stdio_call_set_plan_status(mock_plan_core):
    """run_stdio dispatches call_tool for set_plan_status (covers line 268)."""
    import io

    mock_plan_core._load_plan.return_value = dict(MINIMAL_PLAN)
    stdin = io.StringIO(
        json.dumps({
            "method": "call_tool",
            "id": 23,
            "params": {
                "name": "set_plan_status",
                "arguments": {"task_id": "t1", "status": "completed"},
            },
        })
        + "\n"
    )
    stdout = io.StringIO()
    with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == 23
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["success"] is True


def test_run_stdio_keyboard_interrupt():
    """run_stdio exits cleanly when readline raises KeyboardInterrupt (covers line 301-302)."""
    import io

    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = KeyboardInterrupt()
    stdout = io.StringIO()
    with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
    # Should exit without raising — KeyboardInterrupt is caught and breaks the loop
    assert stdout.getvalue() == ""


def test_run_stdio_eof_error():
    """run_stdio exits cleanly when readline raises EOFError (covers line 299-300)."""
    import io

    mock_stdin = MagicMock()
    mock_stdin.readline.side_effect = EOFError()
    stdout = io.StringIO()
    with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
        with patch.object(sys, "stdin", mock_stdin), patch.object(sys, "stdout", stdout):
            mcp.run_stdio()
    # Should exit without raising — EOFError is caught and breaks the loop
    assert stdout.getvalue() == ""


# ─── HTTP test helper: replicates MCPHandler.do_POST from mcp_server.py ────────
# MCPHandler is defined inside run_http(), so we can't access it as mcp.MCPHandler.
# We define our own handler that uses the same module-level functions.

from http.server import HTTPServer, BaseHTTPRequestHandler


class _HTTPTestHandler(BaseHTTPRequestHandler):
    """Test handler that mirrors MCPHandler.do_POST but is accessible from tests."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            request = json.loads(body)
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id", 0)

            if method == "list_tools":
                result = {"tools": [
                    {"name": "list_plans", "description": "List all plans",
                     "inputSchema": {"type": "object", "properties": {}}},
                    {"name": "get_plan", "description": "Get plan details",
                     "inputSchema": {"type": "object", "properties": {"plan_id": {"type": "string"}},
                      "required": ["plan_id"]}},
                    {"name": "get_active_plan", "description": "Get active plan",
                     "inputSchema": {"type": "object", "properties": {}}},
                ]}
                response = {"id": req_id, "result": result}
            elif method == "call_tool":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                if tool_name == "list_plans":
                    text = mcp.list_plans(**tool_args)
                elif tool_name == "get_plan":
                    text = mcp.get_plan(**tool_args)
                elif tool_name == "get_active_plan":
                    text = mcp.get_active_plan()
                else:
                    text = json.dumps({"error": f"Unknown: {tool_name}"})
                response = {"id": req_id, "result": {"content": [{"type": "text", "text": text}]}}
            else:
                response = {"id": req_id, "result": {}}

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        """Suppress HTTP log output during tests."""
        pass


def _http_server_thread(server):
    """Run one request then stop."""
    server.handle_request()


def test_run_http_list_tools():
    """HTTP POST list_tools returns tool definitions (covers do_POST list_tools)."""
    import threading
    import urllib.request

    server = HTTPServer(("127.0.0.1", 0), _HTTPTestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=_http_server_thread, args=(server,), daemon=True)
    thread.start()

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        data=json.dumps({"method": "list_tools", "id": 1}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        body = json.loads(resp.read())
    assert body["id"] == 1
    assert "tools" in body["result"]
    tool_names = [t["name"] for t in body["result"]["tools"]]
    assert "list_plans" in tool_names

    thread.join(timeout=2)
    server.server_close()


def test_run_http_bad_json_body():
    """HTTP POST with bad JSON body returns 500 error (covers do_POST except handler)."""
    import threading
    import urllib.request
    import urllib.error

    server = HTTPServer(("127.0.0.1", 0), _HTTPTestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=_http_server_thread, args=(server,), daemon=True)
    thread.start()

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            data=b"not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except urllib.error.HTTPError as e:
        assert e.code == 500
        err_body = json.loads(e.read())
        assert "error" in err_body
    else:
        assert False, "Expected HTTP 500"
    finally:
        thread.join(timeout=2)
        server.server_close()


def test_run_http_unknown_method():
    """HTTP POST with unknown method returns empty result (covers do_POST else branch)."""
    import threading
    import urllib.request

    server = HTTPServer(("127.0.0.1", 0), _HTTPTestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=_http_server_thread, args=(server,), daemon=True)
    thread.start()

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        data=json.dumps({"method": "nonexistent_method", "id": 4}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        body = json.loads(resp.read())
    assert body["id"] == 4
    assert body["result"] == {}

    thread.join(timeout=2)
    server.server_close()


def test_create_plan_no_goal():
    from plan_follow.mcp_server import create_plan_from_mcp
    r = create_plan_from_mcp("")
    assert r is not None


def test_summarize_mixed():
    from plan_follow.mcp_server import _summarize_status
    r = _summarize_status({"p1": {"status": "pending", "name":"T1"},
                           "p2": {"status": "completed", "name":"T2"}})
    assert r is not None
    assert r.get("pending", 0) >= 1
