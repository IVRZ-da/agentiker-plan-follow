"""Coverage tests for plan_follow/tools/base.py — push coverage from 85% to 90%."""

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Line 31: get_session_id fallback (uuid4 when no env var)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetSessionIdFallback:
    def test_no_env_var_generates_uuid(self, monkeypatch):
        """Line 31: No HERMES_SESSION_ID/SESSION_ID → uuid4 fallback."""
        monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)
        from plan_follow.tools.base import get_session_id, reset_session_id

        reset_session_id()
        sid = get_session_id()
        assert sid is not None
        assert len(sid) == 36  # uuid4 format
        assert sid.count("-") == 4


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 101-102, 109-110: _update_plans_index error handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestUpdatePlansIndexErrors:
    def test_corrupt_index_json(self, monkeypatch, tmp_path):
        """Line 101-102: Corrupt plans_index.json → graceful handling."""
        from plan_follow.tools import resolver
        monkeypatch.setattr(resolver, "resolve_plans_index", lambda: tmp_path / "plans_index.json")
        monkeypatch.setattr(resolver, "resolve_plans_dir", lambda: tmp_path / "plans")
        monkeypatch.setattr(resolver, "resolve_roadmaps_dir", lambda: tmp_path / "roadmaps")

        # Create corrupt index
        corrupt = tmp_path / "plans_index.json"
        corrupt.write_text("{{{bad json")
        from plan_follow.tools.base import _ensure_dirs, _update_plans_index

        _ensure_dirs()
        # Should not raise (catches JSONDecodeError)
        _update_plans_index({"plan_id": "test-1", "goal": "test"})
        assert corrupt.exists()

    def test_unwritable_index(self, monkeypatch, tmp_path):
        """Line 109-110: OSError on write → warning logged."""
        from plan_follow.tools import resolver
        monkeypatch.setattr(resolver, "resolve_plans_index", lambda: tmp_path / "plans_index.json")
        monkeypatch.setattr(resolver, "resolve_plans_dir", lambda: tmp_path / "plans")
        monkeypatch.setattr(resolver, "resolve_roadmaps_dir", lambda: tmp_path / "roadmaps")

        from plan_follow.tools.base import _ensure_dirs, _update_plans_index

        _ensure_dirs()
        # Make index path a directory → write raises OSError
        idx_path = tmp_path / "plans_index.json"
        idx_path.mkdir(parents=True, exist_ok=True)
        # Should not raise (catches OSError)
        _update_plans_index({"plan_id": "test-2", "goal": "test"})


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 119-120, 127-128: _clear_plans_index error handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestClearPlansIndexErrors:
    def test_clear_corrupt_index(self, monkeypatch, tmp_path):
        """Line 119-120: Corrupt index → graceful handling."""
        from plan_follow.tools import resolver
        monkeypatch.setattr(resolver, "resolve_plans_index", lambda: tmp_path / "plans_index.json")

        corrupt = tmp_path / "plans_index.json"
        corrupt.write_text("{{{bad json")
        from plan_follow.tools.base import _clear_plans_index

        _clear_plans_index()
        assert corrupt.exists()

    def test_clear_unwritable(self, monkeypatch, tmp_path):
        """Line 127-128: OSError on clear write."""
        from plan_follow.tools import resolver
        monkeypatch.setattr(resolver, "resolve_plans_index", lambda: tmp_path / "plans_index.json")

        idx_path = tmp_path / "plans_index.json"
        idx_path.mkdir(parents=True, exist_ok=True)
        from plan_follow.tools.base import _clear_plans_index

        _clear_plans_index()


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 150-151, 167-168: _recover_plan_from_disk error handling
# ═══════════════════════════════════════════════════════════════════════════════


class TestRecoverFromDiskErrors:
    def test_corrupt_index_in_recover(self, monkeypatch, tmp_path):
        """Line 150-151: corrupt index → fall through to file scan."""
        from plan_follow.tools import base as _base_mod

        monkeypatch.setattr(_base_mod, "resolve_plans_index", lambda: tmp_path / "plans_index.json")
        monkeypatch.setattr(_base_mod, "resolve_plans_dir", lambda: tmp_path)
        monkeypatch.setattr(_base_mod, "resolve_roadmaps_dir", lambda: tmp_path / "roadmaps")

        corrupt = tmp_path / "plans_index.json"
        corrupt.write_text("{{{bad json")
        # Ensure no valid plan files exist in tmp_path
        result = _base_mod._recover_plan_from_disk()
        assert result is None  # no valid plan found

    def test_corrupt_plan_file(self, monkeypatch, tmp_path):
        """Line 167-168: corrupt plan .json → skip."""
        from plan_follow.tools import base as _base_mod

        monkeypatch.setattr(_base_mod, "resolve_plans_index", lambda: tmp_path / "plans_index.json")
        monkeypatch.setattr(_base_mod, "resolve_plans_dir", lambda: tmp_path)
        monkeypatch.setattr(_base_mod, "resolve_roadmaps_dir", lambda: tmp_path / "roadmaps")

        # No index, but a corrupt plan file
        bad_plan = tmp_path / "some-plan.json"
        bad_plan.write_text("{{{bad json")
        result = _base_mod._recover_plan_from_disk()
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 258, 260, 262, 264, 266: __getattr__ backward compat
# ═══════════════════════════════════════════════════════════════════════════════


class TestModuleGetattr:
    def test_backward_compat_attrs_all(self):
        """Lines 258-266: __getattr__ returns STATE attributes."""
        import plan_follow.tools.base as base_mod

        # Before accessing, ensure STATE values are set
        from plan_follow.tools.state import STATE

        STATE.active_plan = {"test": "plan"}
        STATE.active_plan_id = "test-123"
        STATE.tool_metrics = {}
        STATE.drift_warnings = ["warn1"]
        STATE.session_id = "sess-abc"

        assert base_mod._active_plan == {"test": "plan"}
        assert base_mod._active_plan_id == "test-123"
        assert base_mod._tool_metrics == {}
        assert base_mod._drift_warnings == ["warn1"]
        assert base_mod._SESSION_ID == "sess-abc"

    def test_getattr_raises_attribute_error(self):
        """Line 267: unknown attr → AttributeError."""
        import plan_follow.tools.base as base_mod

        with pytest.raises(AttributeError):
            _ = base_mod.nonexistent_attr


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 232-237: _get_active_plan Honcho recovery (best-effort)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetActivePlanHonchoRecovery:
    def test_honcho_recovery_fails_gracefully(self, monkeypatch):
        """Lines 232-237: Honcho recovery exception → returns None."""
        from plan_follow.tools import base as _base_mod

        monkeypatch.setattr(_base_mod, "STATE", type("MockState", (), {
            "active_plan": None, "active_plan_id": None,
        })())
        monkeypatch.setattr(_base_mod, "_recover_plan_from_disk", lambda: None)

        # _load_plan_state_from_honcho is imported lazily inside _get_active_plan
        # Patch the lazy import path inside coondination module
        import plan_follow.tools.coordination as _coord
        monkeypatch.setattr(
            _coord, "_load_plan_state_from_honcho",
            lambda: (_ for _ in ()).throw(RuntimeError("Honcho down")),
        )
        result = _base_mod._get_active_plan()
        assert result is None
