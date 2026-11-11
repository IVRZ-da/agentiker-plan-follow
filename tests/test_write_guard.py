"""Tests für tools/paths.py Write-Guard und den _save_plan-Datenverlust-Schutz.

Hintergrund: v0.5.31 hat über die Test-Fixture echte Pläne in ~/.hermes/plans
zerstört (alle *.json -> "{}"). Diese Tests sichern den Guard, der genau das
verhindert, und zwar im Produktionscode statt im Testcode.
"""
import json
import os
from pathlib import Path

import pytest
from plan_follow import plan_core
from plan_follow.tools import base as tools_base
from plan_follow.tools.paths import (
    GUARD_ENV,
    assert_writable,
    guard_enabled,
    is_protected,
    protected_roots,
)

HOME_PLANS = Path.home() / ".hermes" / "plans"
HOME_SHARED = Path.home() / ".hermes" / "shared"


# ─── Guard-Grundlagen ────────────────────────────────────────────────────────

def test_guard_enabled_by_conftest():
    """conftest setzt PLAN_FOLLOW_TEST_GUARD=1 beim Import."""
    assert os.environ.get(GUARD_ENV) == "1"
    assert guard_enabled() is True


def test_protected_roots_are_frozen():
    """Die Roots werden beim Import eingefroren (Path.home() ist patchbar)."""
    roots = protected_roots()
    assert HOME_PLANS in roots
    assert HOME_SHARED in roots
    assert Path.home() / ".hermes" / "roadmaps" in roots


def test_is_protected_detects_production_paths():
    assert is_protected(HOME_PLANS / "irgendein-plan.json") is True
    assert is_protected(HOME_PLANS / "archived" / "alt.json") is True
    assert is_protected(HOME_SHARED / "locks.json") is True
    # Test-Root ist erlaubt
    assert is_protected(plan_core.PLANS_DIR / "test-plan.json") is False


def test_assert_writable_blocks_production_path():
    with pytest.raises(RuntimeError, match="Write-Guard"):
        assert_writable(HOME_PLANS / "boese.json")


def test_assert_writable_allows_test_root():
    assert_writable(plan_core.PLANS_DIR / "ok.json")  # darf nicht werfen


def test_assert_writable_noop_when_guard_disabled(monkeypatch):
    monkeypatch.delenv(GUARD_ENV, raising=False)
    assert guard_enabled() is False
    assert_writable(HOME_PLANS / "egal.json")  # kein Raise


# ─── _save_plan: Datenverlust-Schutz ────────────────────────────────────────

def test_save_plan_rejects_empty_dict():
    """Der historische Bug schrieb '{}' in jede Plan-Datei."""
    with pytest.raises(ValueError, match="plan_id"):
        tools_base._save_plan({})


def test_save_plan_rejects_plan_without_tasks():
    with pytest.raises(ValueError, match="keine Tasks"):
        tools_base._save_plan({"plan_id": "guard-test-ohne-tasks"})


def test_save_plan_refuses_production_path(monkeypatch):
    """Zeigt PLANS_DIR auf das echte Verzeichnis -> Guard muss werfen."""
    monkeypatch.setattr(plan_core, "PLANS_DIR", HOME_PLANS)
    plan = {"plan_id": "guard-integration", "goal": "x", "tasks": {"t1": {"status": "pending"}}}
    with pytest.raises(RuntimeError, match="Write-Guard"):
        tools_base._save_plan(plan)
    # Und nichts wurde angelegt
    assert not (HOME_PLANS / "guard-integration.json").exists()


def test_save_plan_writes_into_test_root_and_keeps_backup():
    plan = {
        "plan_id": "guard-backup-test",
        "goal": "Backup-Test",
        "created": "2026-11-10T20:00:00",
        "current_task": "t1",
        "tasks": {"t1": {"id": "t1", "status": "pending", "name": "T1"}},
    }
    tools_base._save_plan(plan)
    target = plan_core.PLANS_DIR / "guard-backup-test.json"
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["plan_id"] == "guard-backup-test"

    # Zweites Schreiben mit geändertem Inhalt -> .bak des ersten Stands
    plan["tasks"]["t1"]["status"] = "completed"
    tools_base._save_plan(plan)
    bak = target.with_suffix(".json.bak")
    assert bak.exists(), "Vor dem Überschreiben muss ein .json.bak entstehen"
    assert json.loads(bak.read_text(encoding="utf-8"))["tasks"]["t1"]["status"] == "pending"


def test_save_plan_does_not_create_backup_for_empty_existing_file():
    """Eine leere 2-Byte-Datei ('{}') ist kein schützenswerter Inhalt."""
    plan_id = "guard-empty-existing"
    target = plan_core.PLANS_DIR / f"{plan_id}.json"
    target.write_text("{}", encoding="utf-8")
    tools_base._save_plan({"plan_id": plan_id, "goal": "g", "tasks": {"t1": {"status": "pending"}}})
    assert not target.with_suffix(".json.bak").exists()


# ─── coord_state / templates / tracking ─────────────────────────────────────

def test_coord_state_blocks_production_shared_dir(monkeypatch):
    from plan_follow import coord_state

    monkeypatch.setattr(coord_state, "SHARED_DIR", HOME_SHARED)
    with pytest.raises(RuntimeError, match="Write-Guard"):
        coord_state._atomic_write(HOME_SHARED / "sessions.json", {})


def test_template_save_blocks_production_dir(monkeypatch):
    from plan_follow import plan_templates

    monkeypatch.setattr(plan_templates, "TEMPLATES_DIR", HOME_PLANS / "templates")
    with pytest.raises(RuntimeError, match="Write-Guard"):
        plan_templates.save_user_template("guard-tpl", [{"id": "a", "name": "A"}])


def test_tracking_blocks_production_file(monkeypatch):
    from plan_follow import plan_suggest

    monkeypatch.setattr(plan_suggest, "_TRACKING_FILE", HOME_PLANS / "time_tracking.json")
    with pytest.raises(RuntimeError, match="Write-Guard"):
        plan_suggest._ensure_tracking_file()
