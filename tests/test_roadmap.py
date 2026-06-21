"""Tests for plan_roadmap module — YAML parsing, phase management, formatting."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from plan_follow.plan_core import (
    ROADMAPS_DIR,
    _list_roadmaps,
    _load_roadmap,
    _parse_roadmap_yaml_simple,
    _save_roadmap,
)
from plan_follow.plan_roadmap import (
    _format_phase_detail,
    _format_roadmap_overview,
    _get_next_phases,
    _get_phase,
    _get_phase_progress,
    _phase_to_plan_tasks,
    _update_phase_status,
    _validate_roadmap,
    get_active_roadmap,
    plan_roadmap_handler,
    reset_active_roadmap,
    set_active_roadmap,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def cleanup_active_roadmap():
    """Reset active roadmap before and after each test."""
    reset_active_roadmap()
    yield
    reset_active_roadmap()


@pytest.fixture
def sample_roadmap_data():
    return {
        "name": "Test-Roadmap",
        "goal": "Website verbessern",
        "created": "2026-06-20",
        "phases": [
            {
                "id": "blog",
                "name": "Blog befüllen",
                "priority": "high",
                "effort": "3 Tage",
                "impact": "SEO",
                "status": "pending",
                "depends_on": [],
                "tasks": ["Artikel 1", "Artikel 2"],
            },
            {
                "id": "casestudies",
                "name": "Fallstudien aufwerten",
                "priority": "high",
                "effort": "2 Tage",
                "impact": "Conversion",
                "status": "pending",
                "depends_on": ["blog"],
                "tasks": ["4 Cases umschreiben"],
            },
            {
                "id": "leadmagnet",
                "name": "Lead-Magnet",
                "priority": "medium",
                "effort": "1 Tag",
                "impact": "Leads",
                "status": "pending",
                "depends_on": ["casestudies"],
                "tasks": ["PDF erstellen"],
            },
        ],
    }


@pytest.fixture
def sample_roadmap_yaml():
    return """name: Test-Roadmap
goal: Website verbessern
created: 2026-06-20
phases:
  - id: blog
    name: Blog befüllen
    priority: high
    effort: 3 Tage
    impact: SEO
    status: pending
    depends_on: []
    tasks:
      - Artikel 1
      - Artikel 2
  - id: casestudies
    name: Fallstudien aufwerten
    priority: high
    effort: 2 Tage
    impact: Conversion
    status: pending
    depends_on: [blog]
    tasks:
      - 4 Cases umschreiben
"""


# ─── YAML Parsing ─────────────────────────────────────────────────────────────

class TestYamlParsing:
    def test_parse_valid_yaml(self, sample_roadmap_yaml):
        result = _parse_roadmap_yaml_simple(sample_roadmap_yaml)
        assert result is not None
        assert result["name"] == "Test-Roadmap"
        assert result["goal"] == "Website verbessern"
        assert len(result["phases"]) == 2
        assert result["phases"][0]["id"] == "blog"
        assert result["phases"][1]["priority"] == "high"

    def test_parse_empty_yaml(self):
        result = _parse_roadmap_yaml_simple("")
        assert result is None

    def test_parse_comments_only(self):
        result = _parse_roadmap_yaml_simple("# nur ein Kommentar\n# noch einer")
        assert result is None

    def test_parse_invalid_yaml(self):
        _parse_roadmap_yaml_simple(": : : invalid")
        # Simple parser may return partial result for garbage input
        # Just verify it doesn't crash
        pass

    def test_parse_with_depends_on_array(self):
        yaml = """name: Test
goal: Test
created: 2026-01-01
phases:
  - id: a
    name: Phase A
    priority: high
    status: pending
    depends_on: [x, y]
"""
        result = _parse_roadmap_yaml_simple(yaml)
        assert result is not None
        assert result["phases"][0]["depends_on"] == ["x", "y"]

    def test_parse_json_format(self):
        """JSON format is handled by _load_roadmap, not the simple parser."""
        import tempfile
        from pathlib import Path
        data = '{"name": "JSON-Roadmap", "goal": "Test", "created": "2026-01-01", "phases": [{"id": "a", "name": "A", "priority": "high", "status": "pending"}]}'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, dir=ROADMAPS_DIR) as f:
            name = Path(f.name).stem
            f.write(data)
        loaded = _load_roadmap(name)
        assert loaded is not None
        assert loaded["name"] == "JSON-Roadmap"
        Path(f.name).unlink(missing_ok=True)


# ─── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_valid_roadmap(self, sample_roadmap_data):
        errors = _validate_roadmap(sample_roadmap_data)
        assert errors == []

    def test_missing_name(self):
        data = {"phases": [{"id": "a", "name": "A", "priority": "high", "status": "pending"}]}
        errors = _validate_roadmap(data)
        assert any("name" in e for e in errors)

    def test_missing_phases(self):
        data = {"name": "Test"}
        errors = _validate_roadmap(data)
        assert any("phases" in e for e in errors)

    def test_phase_missing_id(self):
        data = {"name": "Test", "goal": "Test", "phases": [{"name": "A"}]}
        errors = _validate_roadmap(data)
        assert any("id" in e for e in errors)

    def test_duplicate_phase_id(self):
        data = {
            "name": "Test", "goal": "Test",
            "phases": [
                {"id": "a", "name": "A", "priority": "high", "status": "pending"},
                {"id": "a", "name": "A2", "priority": "high", "status": "pending"},
            ],
        }
        errors = _validate_roadmap(data)
        assert any("duplicate" in e for e in errors)

    def test_invalid_priority_defaults_to_medium(self):
        data = {
            "name": "Test", "goal": "Test",
            "phases": [{"id": "a", "name": "A", "priority": "urgent", "status": "pending"}],
        }
        _validate_roadmap(data)
        assert data["phases"][0]["priority"] == "medium"

    def test_invalid_status_defaults_to_pending(self):
        data = {
            "name": "Test", "goal": "Test",
            "phases": [{"id": "a", "name": "A", "priority": "high", "status": "done"}],
        }
        _validate_roadmap(data)
        assert data["phases"][0]["status"] == "pending"

    def test_unknown_dependency(self):
        data = {
            "name": "Test", "goal": "Test",
            "phases": [
                {"id": "a", "name": "A", "priority": "high", "status": "pending", "depends_on": ["nonexistent"]},
            ],
        }
        errors = _validate_roadmap(data)
        assert any("nonexistent" in e for e in errors)


# ─── Phase Helpers ────────────────────────────────────────────────────────────

class TestPhaseHelpers:
    def test_get_phase_found(self, sample_roadmap_data):
        phase = _get_phase(sample_roadmap_data, "blog")
        assert phase is not None
        assert phase["name"] == "Blog befüllen"

    def test_get_phase_not_found(self, sample_roadmap_data):
        phase = _get_phase(sample_roadmap_data, "nonexistent")
        assert phase is None

    def test_update_phase_status(self, sample_roadmap_data):
        success, msg = _update_phase_status(sample_roadmap_data, "blog", "in_progress")
        assert success
        assert "in_progress" in msg
        assert sample_roadmap_data["phases"][0]["status"] == "in_progress"

    def test_update_phase_blocked_by_dependency(self, sample_roadmap_data):
        """Can't set casestudies to in_progress if blog is not completed."""
        success, msg = _update_phase_status(sample_roadmap_data, "casestudies", "in_progress")
        assert not success
        assert "depends" in msg

    def test_update_phase_unblocked_after_dependency_completed(self, sample_roadmap_data):
        """After blog completes, casestudies can proceed."""
        _update_phase_status(sample_roadmap_data, "blog", "completed")
        success, msg = _update_phase_status(sample_roadmap_data, "casestudies", "in_progress")
        assert success
        assert "in_progress" in msg

    def test_update_phase_invalid_status(self, sample_roadmap_data):
        success, msg = _update_phase_status(sample_roadmap_data, "blog", "invalid")
        assert not success

    def test_update_phase_not_found(self, sample_roadmap_data):
        success, msg = _update_phase_status(sample_roadmap_data, "ghost", "completed")
        assert not success

    def test_update_phase_cascade_unblocks(self, sample_roadmap_data):
        """When blog completes, casestudies should auto-unblock."""
        # First set casestudies to blocked
        sample_roadmap_data["phases"][1]["status"] = "blocked"
        # Complete blog → should cascade
        _update_phase_status(sample_roadmap_data, "blog", "completed")
        assert sample_roadmap_data["phases"][1]["status"] == "pending"


class TestNextPhases:
    def test_all_pending_no_deps(self):
        roadmap = {
            "phases": [
                {"id": "a", "status": "pending", "depends_on": []},
                {"id": "b", "status": "pending", "depends_on": []},
            ],
        }
        next_phases = _get_next_phases(roadmap)
        assert len(next_phases) == 2

    def test_dependency_blocks(self, sample_roadmap_data):
        """Only blog should be next (casestudies depends on blog)."""
        next_phases = _get_next_phases(sample_roadmap_data)
        assert len(next_phases) == 1
        assert next_phases[0]["id"] == "blog"

    def test_dependency_chain(self, sample_roadmap_data):
        _update_phase_status(sample_roadmap_data, "blog", "completed")
        next_phases = _get_next_phases(sample_roadmap_data)
        assert len(next_phases) == 1
        assert next_phases[0]["id"] == "casestudies"

    def test_all_completed(self, sample_roadmap_data):
        for p in sample_roadmap_data["phases"]:
            p["status"] = "completed"
        next_phases = _get_next_phases(sample_roadmap_data)
        assert len(next_phases) == 0

    def test_blocked_phases_excluded(self):
        roadmap = {
            "phases": [
                {"id": "a", "status": "blocked", "depends_on": []},
                {"id": "b", "status": "pending", "depends_on": []},
            ],
        }
        next_phases = _get_next_phases(roadmap)
        assert len(next_phases) == 1
        assert next_phases[0]["id"] == "b"


class TestPhaseProgress:
    def test_all_pending(self):
        roadmap = {
            "phases": [
                {"id": "a", "status": "pending"},
                {"id": "b", "status": "pending"},
                {"id": "c", "status": "pending"},
            ],
        }
        prog = _get_phase_progress(roadmap)
        assert prog["total"] == 3
        assert prog["completed"] == 0
        assert prog["pending"] == 3

    def test_mixed_status(self):
        roadmap = {
            "phases": [
                {"id": "a", "status": "completed"},
                {"id": "b", "status": "in_progress"},
                {"id": "c", "status": "pending"},
                {"id": "d", "status": "blocked"},
            ],
        }
        prog = _get_phase_progress(roadmap)
        assert prog["total"] == 4
        assert prog["completed"] == 1
        assert prog["in_progress"] == 1
        assert prog["pending"] == 1
        assert prog["blocked"] == 1

    def test_empty_phases(self):
        prog = _get_phase_progress({"phases": []})
        assert prog["total"] == 0


# ─── Formatting ───────────────────────────────────────────────────────────────

class TestFormatting:
    def test_roadmap_overview(self, sample_roadmap_data):
        result = _format_roadmap_overview(sample_roadmap_data, "test")
        assert "Test-Roadmap" in result
        assert "Roadmap" in result
        assert "0/3" in result
        assert "Blog befüllen" in result
        assert "Fallstudien" in result
        assert "Naechste" in result or "Nächste" in result

    def test_roadmap_overview_with_completed(self, sample_roadmap_data):
        sample_roadmap_data["phases"][0]["status"] = "completed"
        result = _format_roadmap_overview(sample_roadmap_data, "test")
        assert "1/3" in result

    def test_phase_detail(self, sample_roadmap_data):
        result = _format_phase_detail(sample_roadmap_data["phases"][0])
        assert "Blog befüllen" in result
        assert "blog" in result
        assert "high" in result
        assert "3 Tage" in result
        assert "SEO" in result
        assert "Artikel 1" in result

    def test_phase_detail_no_tasks(self):
        phase = {"id": "x", "name": "X", "priority": "low", "status": "pending"}
        result = _format_phase_detail(phase)
        assert "X" in result


# ─── Phase → Plan Conversion ──────────────────────────────────────────────────

class TestPhaseToPlan:
    def test_phase_with_tasks(self, sample_roadmap_data):
        tasks = _phase_to_plan_tasks(sample_roadmap_data["phases"][0])
        assert len(tasks) == 2
        assert tasks[0]["id"] == "blog-1"
        assert tasks[0]["name"] == "Artikel 1"
        assert tasks[0]["depends_on"] == []
        assert tasks[1]["id"] == "blog-2"
        assert tasks[1]["depends_on"] == ["blog-1"]

    def test_phase_without_tasks(self):
        phase = {"id": "simple", "name": "Simple Phase", "priority": "high", "status": "pending"}
        tasks = _phase_to_plan_tasks(phase)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "simple"
        assert tasks[0]["name"] == "Simple Phase"


# ─── Persistence (Save/Load) ─────────────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self, sample_roadmap_data, tmp_path):
        name = "test-save-load"
        assert _save_roadmap(name, sample_roadmap_data)

        loaded = _load_roadmap(name)
        assert loaded is not None
        assert loaded["name"] == "Test-Roadmap"
        assert len(loaded["phases"]) == 3

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_save_and_list(self, sample_roadmap_data):
        name = "test-list"
        _save_roadmap(name, sample_roadmap_data)
        roadmaps = _list_roadmaps()
        names = [r["name"] for r in roadmaps]
        assert name in names

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_load_nonexistent(self):
        loaded = _load_roadmap("nonexistent-roadmap")
        assert loaded is None


# ─── Tool Handler ─────────────────────────────────────────────────────────────

class TestToolHandler:
    def test_cmd_list_empty(self):
        result = plan_roadmap_handler({"cmd": "list"})
        assert isinstance(result, str)

    def test_cmd_list_with_roadmap(self, sample_roadmap_data):
        name = "test-tool-list"
        _save_roadmap(name, sample_roadmap_data)
        result = plan_roadmap_handler({"cmd": "list"})
        assert name in result

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_status_auto_selects(self, sample_roadmap_data):
        name = "test-auto-status"
        _save_roadmap(name, sample_roadmap_data)
        result = plan_roadmap_handler({"cmd": "status"})
        assert "Test-Roadmap" in result

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_create_valid(self):
        result = plan_roadmap_handler({
            "cmd": "create",
            "name": "test-create",
            "goal": "Test goal",
            "phases": [
                {"id": "a", "name": "Phase A", "priority": "high", "status": "pending"},
                {"id": "b", "name": "Phase B", "priority": "medium", "status": "pending", "depends_on": ["a"]},
            ],
        })
        assert "erstellt" in result

        # Cleanup
        path = ROADMAPS_DIR / "test-create.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_create_no_name(self):
        result = plan_roadmap_handler({"cmd": "create", "phases": [{"id": "a", "name": "A"}]})
        assert "name" in result or "Bitte name" in result

    def test_cmd_show(self, sample_roadmap_data):
        name = "test-show"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "show", "phase": "blog"})
        assert "Blog befüllen" in result

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_show_not_found(self, sample_roadmap_data):
        name = "test-show-notfound"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "show", "phase": "ghost"})
        assert "nicht gefunden" in result

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_set_status(self, sample_roadmap_data):
        name = "test-set"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "set", "phase": "blog", "status": "in_progress"})
        assert "in_progress" in result or "->" in result

        # Verify it persisted
        loaded = _load_roadmap(name)
        assert loaded["phases"][0]["status"] == "in_progress"

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_set_blocked_by_dep(self, sample_roadmap_data):
        name = "test-set-blocked"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "set", "phase": "casestudies", "status": "in_progress"})
        assert "Fehler" in result or "depends" in result.lower()

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_to_plan(self, sample_roadmap_data):
        name = "test-to-plan"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "to_plan", "phase": "blog"})
        assert "ready" in result

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_to_plan_not_found(self, sample_roadmap_data):
        name = "test-to-plan-nf"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "to_plan", "phase": "ghost"})
        assert "nicht gefunden" in result

        # Cleanup
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_cmd_invalid(self):
        result = plan_roadmap_handler({"cmd": "invalid_cmd"})
        assert "Unbekannter" in result or "verfuegbar" in result.lower()

    # ─── action= Parameter (konsistent mit plan_lock/plan_notify) ───────────

    def test_action_list_works_like_cmd(self, sample_roadmap_data):
        """action=list funktioniert genauso wie cmd=list."""
        name = "test-action-list"
        _save_roadmap(name, sample_roadmap_data)
        result = plan_roadmap_handler({"action": "list"})
        assert name in result
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_action_create_works_like_cmd(self):
        """action=create funktioniert genauso wie cmd=create."""
        result = plan_roadmap_handler({
            "action": "create",
            "name": "test-action-create",
            "phases": [{"id": "a", "name": "Phase A"}],
        })
        assert "erstellt" in result
        path = ROADMAPS_DIR / "test-action-create.yaml"
        if path.exists():
            path.unlink()

    def test_action_show_works_like_cmd(self, sample_roadmap_data):
        """action=show funktioniert genauso wie cmd=show."""
        name = "test-action-show"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"action": "show", "phase": "blog"})
        assert "Blog befüllen" in result
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_action_set_works_like_cmd(self, sample_roadmap_data):
        """action=set funktioniert genauso wie cmd=set."""
        name = "test-action-set"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"action": "set", "phase": "blog", "status": "in_progress"})
        assert "in_progress" in result or "->" in result
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()

    def test_action_defaults_to_status(self):
        """Kein Parameter -> default 'status' (zeigt Fehler wenn keine Roadmap existiert)."""
        result = plan_roadmap_handler({})
        assert isinstance(result, str)

    def test_cmd_takes_precedence_over_action(self, sample_roadmap_data):
        """Wenn cmd UND action gesetzt sind, hat cmd Vorrang."""
        name = "test-precedence"
        _save_roadmap(name, sample_roadmap_data)
        set_active_roadmap(name)
        result = plan_roadmap_handler({"cmd": "show", "action": "status", "phase": "blog"})
        assert "Blog befüllen" in result  # would show overview if action= had precedence
        path = ROADMAPS_DIR / f"{name}.yaml"
        if path.exists():
            path.unlink()


# ─── Active Roadmap ───────────────────────────────────────────────────────────

class TestActiveRoadmap:
    def test_no_active_roadmap(self):
        name, data = get_active_roadmap()
        assert name is None
        assert data is None

    def test_set_active(self, sample_roadmap_data):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, dir=ROADMAPS_DIR) as f:
            name = Path(f.name).stem
            json.dump(sample_roadmap_data, f)

        reset_active_roadmap()
        result = set_active_roadmap(name)
        assert result
        rname, rdata = get_active_roadmap()
        assert rname == name
        assert rdata is not None

        # Cleanup
        Path(f.name).unlink(missing_ok=True)

    def test_set_active_not_found(self):
        result = set_active_roadmap("does-not-exist")
        assert not result

    def test_reset(self, sample_roadmap_data):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, dir=ROADMAPS_DIR) as f:
            name = Path(f.name).stem
            json.dump(sample_roadmap_data, f)

        set_active_roadmap(name)
        reset_active_roadmap()
        rname, rdata = get_active_roadmap()
        assert rname is None
        assert rdata is None

        # Cleanup
        Path(f.name).unlink(missing_ok=True)
