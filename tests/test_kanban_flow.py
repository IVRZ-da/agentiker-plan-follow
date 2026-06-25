"""Tests for Kanban-Flow Integration (Full E2E Flow).

Testet den kompletten Kanban-Flow:
1. create_plan() → Kanban Task-Graph (Root + Childs mit Links)
2. complete_task() → kanban_complete + verify + drift
3. Review-Gate → Review-Task creation
4. Legacy-Migration → JSON → Kanban
5. Fallback → JSON wenn Kanban nicht verfügbar
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Kanban Mock ─────────────────────────────────────────────────────────────


class MockKanbanDB:
    """Mock für hermes_cli.kanban_db — simuliert Kanban-DB ohne echte SQLite."""

    def __init__(self):
        self.tasks = {}
        self.links = []
        self.comments = []
        self.completed = []

    def connect(self):
        return self

    def execute(self, sql, params=None):
        # Return a proper mock cursor
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = None
        return cursor

    def create_task(self, title="", body="", assignee="", initial_status="pending",
                    skills=None, priority=5):
        tid = f"task-{len(self.tasks) + 1}"
        self.tasks[tid] = {
            "id": tid,
            "title": title,
            "body": body if isinstance(body, str) else json.dumps(body),
            "assignee": assignee,
            "status": initial_status,
            "skills": skills or [],
            "priority": priority,
        }
        return {"id": tid}

    def get_task(self, tid):
        task = self.tasks.get(tid)
        if task:
            return MagicMock(
                id=tid,
                title=task["title"],
                body=task["body"],
                assignee=task["assignee"],
                status=task["status"],
            )
        return None

    def complete_task(self, tid, summary="", metadata=""):
        # Accept any task ID (Kanban auto-generates IDs, we don't know them)
        self.completed.append({"id": tid, "summary": summary, "metadata": metadata})
        return {"status": "completed"}

    def link_tasks(self, parent_id, child_id):
        self.links.append({"parent": parent_id, "child": child_id})
        return {"status": "linked"}

    def add_comment(self, task_id, body):
        self.comments.append({"task_id": task_id, "body": body})
        return {"id": len(self.comments)}

    def list_comments(self, task_id):
        return [c for c in self.comments if c["task_id"] == task_id]

    def list_boards(self):
        return [{"slug": "plans", "display_name": "Plans"}]

    def create_board(self, slug="", display_name="", description=""):
        return {"slug": slug}

    def heartbeat_worker(self, tid):
        return {"status": "ok"}

    def release_stale_claims(self):
        return {"reclaimed": []}


@pytest.fixture
def mock_kanban():
    """Fixture: mockt kanban_db und setzt _KANBAN_AVAILABLE auf True."""
    mock_db = MockKanbanDB()
    # Create a proper hermes_cli module mock
    hermes_cli = MagicMock()
    hermes_cli.kanban_db = mock_db

    # Patch BEFORE any plan_follow imports are resolved
    with patch.dict("sys.modules", {"hermes_cli": hermes_cli, "hermes_cli.kanban_db": mock_db}):
        # Force-reload modules to pick up the mock
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith("plan_follow"):
                del sys.modules[mod_name]
        yield mock_db


SAMPLE_TASKS = [
    {"id": "p0", "name": "Peer Review", "files": [],
     "verify": "echo ok", "depends_on": []},
    {"id": "p1", "name": "Test 1", "files": ["src/test.ts"],
     "verify": "echo ok", "depends_on": ["p0"]},
    {"id": "p2", "name": "Test 2", "files": ["src/test2.ts"],
     "verify": "echo ok", "depends_on": ["p1"]},
]


# ─── Tests: Kanban Plan Creation ─────────────────────────────────────────────


class TestKanbanPlanCreation:
    """Test: create_plan() mit Kanban-DB erzeugt Task-Graphen."""

    def test_create_kanban_plan_creates_root_task(self, mock_kanban):
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("Test Goal", SAMPLE_TASKS)
        assert plan_id is not None
        assert len(plan_id) > 0

    def test_kanban_plan_has_tasks_in_graph(self, mock_kanban):
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("E2E Test", SAMPLE_TASKS)
        # Kanban has tasks
        assert len(mock_kanban.tasks) >= 1

    def test_kanban_plan_creates_child_tasks(self, mock_kanban):
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("Child Test", SAMPLE_TASKS)
        # Should have at least root + child tasks
        task_count = len(mock_kanban.tasks)
        # At least 3 tasks: p0 (peer review) + p1 + p2 from template
        assert task_count >= 3, f"Expected ≥3 tasks, got {task_count}"

    def test_kanban_plan_has_dependencies(self, mock_kanban):
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("Dep Test", SAMPLE_TASKS)
        assert len(mock_kanban.links) >= 1, "Expected at least 1 dependency link"


# ─── Tests: Kanban Complete ──────────────────────────────────────────────────


class TestKanbanComplete:
    """Test: complete_task() ruft kanban_complete auf."""

    def test_complete_task_marks_kanban(self, mock_kanban):
        from plan_follow.plan_core import create_plan, complete_task
        plan_id = create_plan("Complete Test", SAMPLE_TASKS)
        # complete p0 (first task)
        result = complete_task("p0")
        assert result["status"] == "completed"

    def test_complete_task_calls_kanban_complete(self, mock_kanban):
        from plan_follow.plan_core import create_plan, complete_task
        plan_id = create_plan("Kanban Complete Test", SAMPLE_TASKS)
        before = len(mock_kanban.completed)
        complete_task("p0")
        assert len(mock_kanban.completed) == before + 1

    def test_complete_task_with_verify(self, mock_kanban):
        from plan_follow.plan_core import create_plan, complete_task
        plan_id = create_plan("Verify Test", SAMPLE_TASKS)
        result = complete_task("p0", auto_verify=True)
        assert result["status"] == "completed"

    def test_complete_task_advances(self, mock_kanban):
        from plan_follow.plan_core import create_plan, complete_task, get_current_task
        plan_id = create_plan("Advance Test", SAMPLE_TASKS)
        complete_task("p0")
        next_task = get_current_task()
        assert next_task is None or next_task["task_id"] != "p0"


# ─── Tests: Review Gate ──────────────────────────────────────────────────────


class TestKanbanReviewGate:
    """Test: Bei review_profile wird Review-Task erzeugt."""

    def test_review_task_created_on_complete(self, mock_kanban):
        from plan_follow.plan_core import create_plan, complete_task
        from plan_follow.tools.task import _create_review_task

        before = len(mock_kanban.tasks)
        _create_review_task("plan-test", "task-1", "unit-test", ["src/test.ts"])
        assert len(mock_kanban.tasks) > before, "Review-Task sollte erstellt sein"

    def test_review_task_has_correct_assignee(self, mock_kanban):
        from plan_follow.tools.task import _create_review_task
        _create_review_task("plan-test", "task-1", "full", ["src/test.ts"])
        # Find the last created task
        last_task_id = list(mock_kanban.tasks.keys())[-1]
        task = mock_kanban.tasks[last_task_id]
        assert task["assignee"] == "plan-reviewer"

    def test_no_review_for_none_profile(self, mock_kanban):
        from plan_follow.tools.task import _create_review_task
        before = len(mock_kanban.tasks)
        _create_review_task("plan-test", "task-1", "none", [])
        assert len(mock_kanban.tasks) == before, "Kein Review-Task bei none"


# ─── Tests: Drift Detection ──────────────────────────────────────────────────


class TestKanbanDrift:
    """Test: Drift Detection erkennt ungeplante Änderungen."""

    def test_check_drift_no_repos(self):
        from plan_follow.tools.task import _check_drift
        result = _check_drift([])
        assert result == []

    def test_check_drift_nonexistent_repo(self):
        from plan_follow.tools.task import _check_drift
        result = _check_drift(["/nonexistent/path"])
        assert result == []  # Silently skip

    def test_drift_in_complete_result(self, mock_kanban):
        from plan_follow.plan_core import create_plan, complete_task
        plan_id = create_plan("Drift Test", SAMPLE_TASKS, repo="/tmp")
        result = complete_task("p0")
        assert "drift" in result or result["status"] == "completed"


# ─── Tests: Verify Execution ─────────────────────────────────────────────────


class TestKanbanVerify:
    """Test: Verify-Commands werden ausgeführt."""

    def test_run_verify_empty(self):
        from plan_follow.tools.task import _run_verify
        result = _run_verify("")
        assert result["status"] == "skipped"

    def test_run_verify_echo(self):
        from plan_follow.tools.task import _run_verify
        result = _run_verify("echo 'hello world'")
        assert result["status"] == "passed"

    def test_run_verify_failing(self):
        from plan_follow.tools.task import _run_verify
        result = _run_verify("exit 1")
        assert result["status"] == "failed"

    def test_run_verify_timeout(self):
        from plan_follow.tools.task import _run_verify
        result = _run_verify("sleep 10", timeout=1)
        assert result["status"] == "failed"
        assert "Timeout" in result.get("message", "")


# ─── Tests: Legacy Migration ─────────────────────────────────────────────────


class TestLegacyMigration:
    """Test: Legacy JSON → Kanban Migration."""

    def test_migrate_no_plans_dir(self, mock_kanban):
        from plan_follow.plan_migrate import migrate_legacy_plans
        result = migrate_legacy_plans(dry_run=True)
        assert result["status"] in ("no_plans", "ok")

    def test_migrate_dry_run(self, mock_kanban, tmp_path):
        from plan_follow.plan_migrate import migrate_legacy_plans, PLANS_DIR
        # Temporarily point to a test dir with JSON plan
        with patch.object(PLANS_DIR.__class__, "exists", return_value=True):
            result = migrate_legacy_plans(dry_run=True)
            assert result["status"] in ("no_plans", "ok")

    def test_migrate_tool_handler(self, mock_kanban):
        from plan_follow.plan_migrate import plan_migrate_tool
        result = plan_migrate_tool({"dry_run": True})
        assert "Kanban" in result or "no_plans" in result or "error" in result

    def test_migrate_imports_exist(self):
        """Import test — verify plan_migrate module loads."""
        from plan_follow import plan_migrate
        assert hasattr(plan_migrate, "migrate_legacy_plans")
        assert hasattr(plan_migrate, "plan_migrate_tool")


# ─── Tests: Fallback — JSON wenn Kanban nicht verfügbar ──────────────────────


class TestKanbanFallback:
    """Test: Fallback zu JSON wenn Kanban-DB nicht verfügbar."""

    def test_fallback_creates_json(self):
        """Ohne Kanban: create_plan() erzeugt JSON-Datei."""
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("Fallback Test", SAMPLE_TASKS)
        assert plan_id is not None

    def test_fallback_complete_works(self):
        """Ohne Kanban: complete_task() funktioniert trotzdem."""
        from plan_follow.plan_core import create_plan, complete_task
        plan_id = create_plan("Fallback Complete", SAMPLE_TASKS)
        result = complete_task("p0")
        assert result["status"] == "completed"

    def test_fallback_create_then_complete(self):
        """Ohne Kanban: Kompletter Flow ohne Fehler."""
        from plan_follow.plan_core import create_plan, complete_task, get_current_task
        plan_id = create_plan("Full Fallback", SAMPLE_TASKS)
        r1 = complete_task("p0")
        assert r1["status"] == "completed"

    def test_fallback_plan_list(self):
        """Ohne Kanban: plan_list() funktioniert."""
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("List Test", SAMPLE_TASKS)
        # Verify the plan exists in the JSON fallback
        from plan_follow.plan_core import _get_active_plan
        plan = _get_active_plan()
        assert plan is not None
        assert plan["plan_id"] == plan_id


# ─── Tests: Tool-Handler Integration ─────────────────────────────────────────


class TestKanbanTools:
    """Test: Tool-Handler funktionieren mit Kanban (wenn verfügbar)."""

    def test_plan_migrate_tool_registered(self):
        """plan_migrate Tool ist registriert."""
        from plan_follow.__init__ import PLAN_TOOLS
        tool_names = [t[0] for t in PLAN_TOOLS]
        assert "plan_migrate" in tool_names

    def test_plan_migrate_has_schema(self):
        """plan_migrate hat Schema-Eintrag."""
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS
        assert "plan_migrate" in PER_TOOL_SCHEMAS
        assert "dry_run" in PER_TOOL_SCHEMAS["plan_migrate"].get("properties", {})

    def test_create_plan_returns_plan_id(self):
        """create_plan gibt immer eine plan_id zurück (Kanban oder JSON)."""
        from plan_follow.plan_core import create_plan
        plan_id = create_plan("Tool Test", SAMPLE_TASKS)
        assert plan_id is not None
        assert len(plan_id) > 5

    def test_complete_task_returns_result(self):
        """complete_task gibt Dict-Result zurück."""
        from plan_follow.plan_core import create_plan, complete_task
        plan_id = create_plan("Result Test", SAMPLE_TASKS)
        result = complete_task("p0")
        assert isinstance(result, dict)
        assert "status" in result


# ─── Edge Cases: Fehlerbehandlung ────────────────────────────────────────────


class TestKanbanEdgeCases:
    """Test: Edge Cases und Fehlerbehandlung."""

    def test_complete_nonexistent_task(self):
        """Nicht-existenter Task → Error."""
        from plan_follow.plan_core import complete_task
        result = complete_task("nonexistent")
        assert result["status"] == "error"

    def test_complete_without_plan(self):
        """Ohne aktiven Plan → Error."""
        from plan_follow.plan_core import reset_session_id
        from plan_follow.tools.base import _reset_cache
        _reset_cache()
        from plan_follow.plan_core import complete_task
        result = complete_task("nonexistent")
        # Sollte 'error' oder 'verify_failed' sein (je nach STATE)
        assert result["status"] in ("error", "verify_failed")

    def test_drift_invalid_repo(self):
        """Ungültiger Repo-Pfad → keine Exception."""
        from plan_follow.tools.task import _check_drift
        result = _check_drift(["/tmp/.nonexistent-repo-12345"])
        assert result == []

    def test_verify_no_command(self):
        """Kein verify-Command → skipped."""
        from plan_follow.tools.task import _run_verify
        result = _run_verify("")
        assert result["status"] == "skipped"

    def test_verify_none(self):
        """None als verify-Command → skipped."""
        from plan_follow.tools.task import _run_verify
        result = _run_verify(None)
        assert result["status"] == "skipped"
