"""Tests for plan_hooks.py — Circuit Breaker, Feature-Flags, Cron, Sessions.

Target: increase plan_hooks.py coverage from 68.75% to >85%.
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _make_current(**overrides) -> dict:
    """Build a minimal current-task dict."""
    base = {
        "task_id": "T001",
        "name": "Test Task",
        "files": ["/workspace/src/main.py"],
        "progress": "in_progress",
        "review_profile": "none",
    }
    base.update(overrides)
    return base


def _make_plan(**overrides) -> dict:
    """Build a minimal plan dict."""
    base = {
        "id": "plan-001",
        "name": "Test Plan",
        "goal": "Test goal",
        "tasks": {},
        "repo": "/workspace",
        "repos": ["/workspace"],
    }
    base.update(overrides)
    return base


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_hooks_state():
    """Reset module-level caches before each test."""
    import plan_follow.plan_hooks as ph
    ph._hook_cache.clear()
    ph._breaker_state.clear()


@pytest.fixture
def mock_time(monkeypatch):
    """Control time.monotonic for deterministic tests + reset coord cache."""
    import plan_follow.plan_hooks as _hooks
    _hooks._coord_cache.clear()
    _hooks._prev_coord_sig = ""
    fake_time = [1000.0]
    def _monotonic():
        return fake_time[0]
    monkeypatch.setattr(time, "monotonic", _monotonic)
    return fake_time  # list so tests can mutate


@pytest.fixture
def mock_no_active_plan(monkeypatch):
    """Simulate no active plan: get_current_task_cached returns None."""
    import plan_follow.plan_core
    monkeypatch.setattr(
        plan_follow.plan_core, "get_current_task_cached",
        lambda: None,
    )
    monkeypatch.setattr(
        plan_follow.plan_core, "_get_active_plan",
        lambda: None,
    )


@pytest.fixture
def mock_active_task(monkeypatch):
    """Simulate an active plan with a current task."""
    import plan_follow.plan_core
    current = _make_current()
    monkeypatch.setattr(
        plan_follow.plan_core, "get_current_task_cached",
        lambda: current,
    )
    monkeypatch.setattr(
        plan_follow.plan_core, "_get_active_plan",
        lambda: _make_plan(),
    )
    return current


# ═══════════════════════════════════════════════════════════════════════════════
# _check_breaker / _set_breaker (Lines 35-46)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    """Circuit Breaker functions: _check_breaker, _set_breaker."""

    def test_check_breaker_empty(self):
        from plan_follow.plan_hooks import _check_breaker
        assert _check_breaker() == {}

    def test_set_breaker_and_check(self, mock_time):
        from plan_follow.plan_hooks import _check_breaker, _set_breaker
        _set_breaker("code_refactor", "Something went wrong")
        active = _check_breaker()
        assert "code_refactor" in active
        assert active["code_refactor"]["error"] == "Something went wrong"
        assert active["code_refactor"]["ts"] == 1000.0

    def test_breaker_truncates_error(self, mock_time):
        from plan_follow.plan_hooks import _check_breaker, _set_breaker
        long_msg = "x" * 200
        _set_breaker("mcp_firecrawl_scrape", long_msg)
        active = _check_breaker()
        assert len(active["mcp_firecrawl_scrape"]["error"]) == 80

    def test_breaker_auto_expires(self, mock_time):
        """Line 40: expired entry is removed."""
        from plan_follow.plan_hooks import _BREAKER_TTL, _check_breaker, _set_breaker

        # Set a breaker entry
        _set_breaker("honcho_tool", "error msg")
        assert "honcho_tool" in _check_breaker()

        # Advance time past TTL
        mock_time[0] += _BREAKER_TTL + 1
        active = _check_breaker()
        assert "honcho_tool" not in active
        assert active == {}

    def test_multiple_breakers(self, mock_time):
        """Line 371-374: multiple active breakers."""
        from plan_follow.plan_hooks import _check_breaker, _set_breaker
        _set_breaker("code_refactor", "err1")
        _set_breaker("code_rename", "err2")
        _set_breaker("mcp_firecrawl_scrape", "err3")
        _set_breaker("analysis_search", "err4")
        active = _check_breaker()
        assert len(active) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# _cached_or_fresh (Lines 49-63)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCachedOrFresh:
    """TTL cache utility."""

    def test_fresh_fetcher(self, mock_time):
        from plan_follow.plan_hooks import _cached_or_fresh, _hook_cache
        result = _cached_or_fresh("my_key", lambda: "fresh_val", ttl=60)
        assert result == "fresh_val"
        assert _hook_cache["my_key"][0] == "fresh_val"

    def test_cached_hit(self, mock_time):
        from plan_follow.plan_hooks import _cached_or_fresh, _hook_cache
        _hook_cache["my_key"] = ("cached_val", 1000.0)
        result = _cached_or_fresh("my_key", lambda: "should_not_call", ttl=60)
        assert result == "cached_val"

    def test_cache_expired(self, mock_time):
        """Line 56: stale entry is deleted and refetched."""
        from plan_follow.plan_hooks import _cached_or_fresh, _hook_cache
        _hook_cache["my_key"] = ("stale_val", 900.0)  # 100s old
        mock_time[0] = 1050.0  # 50s after entry, TTL=60 so expired
        call_count = [0]
        def fetcher():
            call_count[0] += 1
            return "new_val"
        result = _cached_or_fresh("my_key", fetcher, ttl=60)
        assert result == "new_val"
        assert call_count[0] == 1
        assert _hook_cache["my_key"][0] == "new_val"

    def test_fetcher_returns_none(self, mock_time):
        from plan_follow.plan_hooks import _cached_or_fresh, _hook_cache
        result = _cached_or_fresh("none_key", lambda: None, ttl=60)
        assert result is None
        assert "none_key" not in _hook_cache

    def test_fetcher_raises_exception(self, mock_time):
        """Line 62-63: Exception returns None."""
        from plan_follow.plan_hooks import _cached_or_fresh
        def broken():
            raise ValueError("boom")
        result = _cached_or_fresh("bad_key", broken, ttl=60)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# _build_banner (Lines 66-75)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildBanner:
    def test_empty_lines(self):
        from plan_follow.plan_hooks import _build_banner
        assert _build_banner([]) is None

    def test_with_lines(self):
        from plan_follow.plan_hooks import _build_banner
        result = _build_banner(["║  Hello"])
        assert result is not None
        assert "[PLAN]" in result
        assert "Hello" in result
        assert result.startswith("[PLAN] ╔═")
        assert result.endswith("╝")


# ═══════════════════════════════════════════════════════════════════════════════
# _build_breaker_banner (Lines 363-377)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildBreakerBanner:
    def test_no_breaker(self, mock_time):
        from plan_follow.plan_hooks import _build_breaker_banner
        assert _build_breaker_banner() == []

    def test_single_breaker(self, mock_time):
        """Lines 368-372: active breaker with single entry."""
        from plan_follow.plan_hooks import _build_breaker_banner, _set_breaker
        _set_breaker("code_refactor", "Syntax error detected")
        lines = _build_breaker_banner()
        assert len(lines) >= 2
        assert any("CIRCUIT BREAKER ACTIVE" in line for line in lines)
        assert any("code_refactor" in line for line in lines)

    def test_multiple_breakers_truncated(self, mock_time):
        """Line 373-374: more than 3 breakers → '... und N weitere'."""
        from plan_follow.plan_hooks import _build_breaker_banner, _set_breaker
        _set_breaker("a_tool", "e1")
        _set_breaker("b_tool", "e2")
        _set_breaker("c_tool", "e3")
        _set_breaker("d_tool", "e4")
        lines = _build_breaker_banner()
        text = "\n".join(lines)
        assert "und 1 weitere" in text or "und 1 mehr" in text or "... und" in text

    def test_breaker_banner_has_instruction_lines(self, mock_time):
        """Lines 375-376: instruction lines are included."""
        from plan_follow.plan_hooks import _build_breaker_banner, _set_breaker
        _set_breaker("code_refactor", "error")
        lines = _build_breaker_banner()
        text = "\n".join(lines)
        assert "Nur lesende Analyse" in text
        assert "entscheiden lassen" in text


# ═══════════════════════════════════════════════════════════════════════════════
# _build_roadmap_banner (Lines 90-114)
# ═══════════════════════════════════════════════════════════════════════════════
# NOTE: _build_roadmap_banner imports plan_roadmap *inside* the function via
#   from .plan_roadmap import _get_next_phases, get_active_roadmap
# So we must patch plan_roadmap directly, not plan_hooks.

class TestBuildRoadmapBanner:
    def test_no_roadmap(self):
        from plan_follow.plan_hooks import _build_roadmap_banner
        lines = _build_roadmap_banner()
        assert lines == []

    def test_with_roadmap_and_progress(self, monkeypatch):
        """Lines 99-106: progress and next phases."""
        from plan_follow.plan_hooks import _build_roadmap_banner
        fake_rdata = {
            "name": "Mein Roadmap",
            "phases": [
                {"id": "p1", "name": "Phase 1", "status": "completed"},
                {"id": "p2", "name": "Phase 2", "status": "in_progress"},
            ],
        }
        monkeypatch.setattr(
            "plan_follow.plan_roadmap.get_active_roadmap",
            lambda: ("rm1", fake_rdata),
        )
        monkeypatch.setattr(
            "plan_follow.plan_roadmap._get_phase_progress",
            lambda r: {"completed": 1, "total": 2},
        )
        monkeypatch.setattr(
            "plan_follow.plan_roadmap._get_next_phases",
            lambda r: [{"id": "p2", "name": "Phase 2"}],
        )
        lines = _build_roadmap_banner()
        assert len(lines) >= 2
        assert any("ROADMAP" in line for line in lines)
        assert any("1/2" in line or "1 Phasen" in line for line in lines)
        assert any("Phase 2" in line for line in lines)

    def test_with_blocked_phases(self, monkeypatch):
        """Lines 108-111: blocked phases section."""
        from plan_follow.plan_hooks import _build_roadmap_banner
        fake_rdata = {
            "name": "Blocked Roadmap",
            "phases": [
                {"id": "p1", "name": "Phase 1", "status": "completed"},
                {"id": "p2", "name": "Phase 2", "status": "blocked"},
            ],
        }
        monkeypatch.setattr(
            "plan_follow.plan_roadmap.get_active_roadmap",
            lambda: ("rm1", fake_rdata),
        )
        monkeypatch.setattr(
            "plan_follow.plan_roadmap._get_phase_progress",
            lambda r: {"completed": 1, "total": 2},
        )
        monkeypatch.setattr(
            "plan_follow.plan_roadmap._get_next_phases",
            lambda r: [],
        )
        lines = _build_roadmap_banner()
        text = "\n".join(lines)
        assert "Blockiert" in text
        assert "Phase 2" in text

    def test_roadmap_exception_handled(self, monkeypatch):
        """Line 112-113: exception is caught."""
        from plan_follow.plan_hooks import _build_roadmap_banner
        monkeypatch.setattr(
            "plan_follow.plan_roadmap.get_active_roadmap",
            lambda: (_ for _ in ()).throw(ValueError("oops")),
        )
        lines = _build_roadmap_banner()
        assert lines == []

    def test_roadmap_none_rdata(self, monkeypatch):
        """Line 97-98: rdata is None/falsy."""
        from plan_follow.plan_hooks import _build_roadmap_banner
        monkeypatch.setattr(
            "plan_follow.plan_roadmap.get_active_roadmap",
            lambda: ("rm1", None),
        )
        lines = _build_roadmap_banner()
        assert lines == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_git_banner (Lines 117-157)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildGitBanner:
    """Liest ausschliesslich den Snapshot — kein git-Subprozess im Renderpfad.

    v0.5.33: Der Banner startet kein git mehr. ``_refresh_snapshots`` (Observer)
    fuellt den Snapshot, ``_build_git_banner`` liest ihn nur.
    """

    @pytest.fixture(autouse=True)
    def _fresh_snapshot(self):
        import plan_follow.plan_hooks as ph

        ph._git_snapshot = {}
        yield
        ph._git_snapshot = {}

    def test_empty_snapshot(self):
        from plan_follow.plan_hooks import _build_git_banner

        assert _build_git_banner() == []

    def test_branch_and_dirty(self):
        import plan_follow.plan_hooks as ph

        ph._git_snapshot = {
            "/workspace/repo1": {
                "status": "ok",
                "branch": "main",
                "dirty": True,
                "dirty_files": 3,
                "ahead": 0,
                "behind": 0,
            }
        }
        text = "\n".join(ph._build_git_banner())
        assert "repo1" in text
        assert "main" in text
        assert "+3" in text

    def test_ahead_and_behind(self):
        import plan_follow.plan_hooks as ph

        ph._git_snapshot = {
            "/workspace/repo2": {
                "status": "ok",
                "branch": "dev",
                "dirty": False,
                "ahead": 2,
                "behind": 1,
            }
        }
        text = "\n".join(ph._build_git_banner())
        assert "↑2↓1" in text

    def test_error_status_is_filtered_by_refresh(self, monkeypatch):
        import plan_follow.plan_hooks as ph

        monkeypatch.setattr(
            ph.plan_core, "_get_active_plan", lambda: {"plan_id": "p", "repos": ["/r1", "/r2"]}
        )
        monkeypatch.setattr(ph.plan_core, "_get_repos", lambda plan: ["/r1", "/r2"])
        monkeypatch.setattr(
            ph.plan_core,
            "get_git_status",
            lambda repo: {"status": "ok", "branch": "main"}
            if repo == "/r1"
            else {"status": "error", "error": "boom"},
        )
        monkeypatch.setattr(ph.plan_core, "check_drift", lambda: [])

        ph._refresh_snapshots(force=True)

        assert set(ph._git_snapshot) == {"/r1"}

    def test_refresh_respects_ttl(self, monkeypatch):
        import time as _t

        import plan_follow.plan_hooks as ph

        calls = []
        monkeypatch.setattr(ph.plan_core, "_get_active_plan", lambda: {"plan_id": "p"})
        monkeypatch.setattr(ph.plan_core, "_get_repos", lambda plan: ["/r1"])
        monkeypatch.setattr(
            ph.plan_core, "get_git_status", lambda repo: calls.append(repo) or {"status": "ok"}
        )
        monkeypatch.setattr(ph.plan_core, "check_drift", lambda: [])

        ph._refresh_snapshots(force=True)
        ph._refresh_snapshots()  # innerhalb TTL -> kein zweiter Aufruf

        assert calls == ["/r1"]
        ph._git_snapshot_ts = _t.monotonic() - ph._SNAPSHOT_TTL - 1
        ph._refresh_snapshots()
        assert calls == ["/r1", "/r1"]


class TestBuildDriftBanner:
    """Drift kommt aus dem Snapshot und wird je Aenderung nur einmal gerendert."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        import plan_follow.plan_hooks as ph

        ph._drift_snapshot = []
        ph._drift_reported = ()
        yield
        ph._drift_snapshot = []
        ph._drift_reported = ()

    def test_no_drift(self):
        from plan_follow.plan_hooks import _build_drift_banner

        assert _build_drift_banner() == []

    def test_drift_detected(self):
        import plan_follow.plan_hooks as ph

        ph._drift_snapshot = ["src/a.py", "src/b.py"]
        text = "\n".join(ph._build_drift_banner())
        assert "DRIFT DETECTED" in text
        assert "src/a.py" in text

    def test_drift_truncated_after_three(self):
        import plan_follow.plan_hooks as ph

        ph._drift_snapshot = [f"f{i}.py" for i in range(5)]
        text = "\n".join(ph._build_drift_banner())
        assert "and 2 more" in text

    def test_rendered_once_per_change(self):
        import plan_follow.plan_hooks as ph

        ph._drift_snapshot = ["x.py"]
        assert ph._build_drift_banner()
        assert ph._build_drift_banner() == []

    def test_new_change_renders_again(self):
        import plan_follow.plan_hooks as ph

        ph._drift_snapshot = ["x.py"]
        assert ph._build_drift_banner()
        ph._drift_snapshot = ["x.py", "y.py"]
        assert ph._build_drift_banner()

    def test_proactive_warning_from_state(self, monkeypatch):
        import plan_follow.plan_hooks as ph

        monkeypatch.setattr(ph.plan_core, "get_drift_warnings", lambda: ["ausserhalb task.files"])
        text = "\n".join(ph._build_drift_banner())
        assert "DRIFT WARNING" in text


class TestBuildDueBanner:
    def test_no_due(self, monkeypatch):
        from plan_follow.plan_hooks import _build_due_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: None,
        )
        assert _build_due_banner() == []

    def test_overdue(self, monkeypatch):
        from plan_follow.plan_hooks import _build_due_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: {"overdue": True, "days_remaining": -2, "due": "2024-01-01"},
        )
        lines = _build_due_banner()
        text = "\n".join(lines)
        assert "OVERDUE" in text or "DEADLINE OVERDUE" in text

    def test_due_soon(self, monkeypatch):
        """Lines 199-203: due within 3 days."""
        from plan_follow.plan_hooks import _build_due_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: {"overdue": False, "days_remaining": 2, "due": "2024-06-25"},
        )
        lines = _build_due_banner()
        text = "\n".join(lines)
        assert "DEADLINE SOON" in text or "SOON" in text
        assert "2" in text

    def test_due_exception_handled(self, monkeypatch):
        """Line 204-205: exception caught."""
        from plan_follow.plan_hooks import _build_due_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: (_ for _ in ()).throw(ValueError("oops")),
        )
        assert _build_due_banner() == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_coordination_banner (Lines 209-258)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildCoordinationBanner:
    @staticmethod
    def _reset_coord_cache(monkeypatch):
        """Reset coord_cache + signature zwischen Tests."""
        import plan_follow.plan_hooks as hooks
        hooks._coord_cache.clear()
        hooks._prev_coord_sig = ""

    def test_no_sessions_no_locks(self, monkeypatch, mock_time):
        self._reset_coord_cache(monkeypatch)
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        assert _build_coordination_banner() == []

    def test_with_sessions(self, monkeypatch, mock_time):
        """Lines 228-233: active sessions listed."""
        self._reset_coord_cache(monkeypatch)
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: {
            "sess-1": {"goal": "Implement feature X"},
            "sess-2": {"goal": "Fix bug Y"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "aktive" in text or "Session" in text
        assert "sess-1" in text or "sess-2" in text

    def test_with_sessions_truncated(self, monkeypatch, mock_time):
        """Line 232-233: more than 3 sessions → '... und N weitere'."""
        self._reset_coord_cache(monkeypatch)
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: {f"s{i}": {"goal": f"Goal {i}"} for i in range(5)})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "und 2 weitere" in text or "und 2 mehr" in text

    def test_with_locks(self, monkeypatch, mock_time):
        """Lines 235-248: locks for current task files."""
        self._reset_coord_cache(monkeypatch)
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {
            "/workspace/src/main.py": {"session_id": "other-sess", "since": "2024-01-01T00:00:00"},
        })
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(files=["/workspace/src/main.py"]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "LOCKS" in text or "gelockt" in text
        assert "other-sess" in text

    def test_with_notifications(self, monkeypatch, mock_time):
        """Lines 250-255: unread notifications."""
        self._reset_coord_cache(monkeypatch)
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [{"id": "n1", "text": "Hello"}])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "Nachricht" in text or "📬" in text

    def test_coord_exception_handled(self, monkeypatch, mock_time):
        """Line 256-257: exception caught."""
        self._reset_coord_cache(monkeypatch)
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        assert _build_coordination_banner() == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_tts_banner (Lines 261-327)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildTTSBanner:
    """TTS-Events kommen aus der Queue; die Plan-Datei wird nicht geschrieben."""

    def _activate(self, tts_flags=None):
        from plan_follow.tools.state import STATE

        plan = {
            "plan_id": "plan-001",
            "goal": "Test goal",
            "current_task": "t1",
            "tasks": {
                "t1": {
                    "id": "t1",
                    "status": "in_progress",
                    "name": "Task eins",
                    "files": [],
                    "verify": "true",
                    "depends_on": [],
                    "review_profile": "none",
                    "review_result": None,
                }
            },
        }
        if tts_flags is not None:
            plan["tts_flags"] = tts_flags
        # Disk-Freshness: STATE ohne Datei wird vom Freshness-Check verworfen
        import json as _json

        from plan_follow.tools.base import _plan_path

        path = _plan_path(plan["plan_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(plan, indent=2), encoding="utf-8")
        STATE.active_plan = plan
        STATE.active_plan_id = plan["plan_id"]
        return plan

    def test_queue_plan_created(self):
        import plan_follow.plan_hooks as ph
        from plan_follow.tools import tts_queue

        plan = self._activate()
        tts_queue.enqueue("plan_created", plan["plan_id"], message="Ziel", name="3")

        text = "\n".join(ph._build_tts_banner("s1"))
        assert "plan_created" in text
        assert "Ziel" in text

    def test_queue_event_once(self):
        import plan_follow.plan_hooks as ph
        from plan_follow.tools import tts_queue

        plan = self._activate()
        tts_queue.enqueue("task_completed", plan["plan_id"], task_id="t1", name="Task eins")

        assert ph._build_tts_banner("s1")
        assert ph._build_tts_banner("s1") == []

    def test_legacy_flag_read_only_once(self):
        import plan_follow.plan_hooks as ph

        plan = self._activate({"plan_created": True})

        assert ph._build_tts_banner("")  # erster Aufruf zeigt den Marker
        assert ph._build_tts_banner("") == []
        # Flag bleibt in der Datei stehen — der Renderer raeumt nicht mehr auf
        assert plan["tts_flags"]["plan_created"] is True

    def test_review_failed_is_no_longer_rendered(self):
        """review_failed hatte nie einen Writer — das Event ist entfernt."""
        import plan_follow.plan_hooks as ph

        self._activate({"review_failed": ["t1"]})

        assert ph._build_tts_banner("") == []

    def test_foreign_session_event_is_not_shown(self):
        import plan_follow.plan_hooks as ph
        from plan_follow.tools import tts_queue

        plan = self._activate()
        tts_queue.enqueue("task_completed", plan["plan_id"], task_id="t1", session_id="other")

        assert ph._build_tts_banner("mine") == []


class TestBuildReviewBanner:
    def test_no_review_profile(self):
        from plan_follow.plan_hooks import _build_review_banner
        current = _make_current(review_profile="none")
        assert _build_review_banner(current) == []

    def test_in_review(self, monkeypatch):
        from plan_follow.plan_hooks import _build_review_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "in_review",
        )
        current = _make_current(review_profile="strict")
        lines = _build_review_banner(current)
        text = "\n".join(lines)
        assert "REVIEW REQUIRED" in text or "in_review" in text or "REVIEW_PENDING" in text

    def test_review_failed(self, monkeypatch):
        from plan_follow.plan_hooks import _build_review_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "failed",
        )
        current = _make_current(
            review_profile="strict",
            review_result={"issues": [{"check": "Style issue"}, {"check": "Logic error"}]},
        )
        lines = _build_review_banner(current)
        text = "\n".join(lines)
        assert "REVIEW FAILED" in text or "❌" in text
        assert "Style issue" in text

    def test_review_failed_truncated(self, monkeypatch):
        """Line 352-353: '... and N more' for issues."""
        from plan_follow.plan_hooks import _build_review_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "failed",
        )
        current = _make_current(
            review_profile="strict",
            review_result={
                "issues": [
                    {"check": "Issue 1"},
                    {"check": "Issue 2"},
                    {"check": "Issue 3"},
                ],
            },
        )
        lines = _build_review_banner(current)
        text = "\n".join(lines)
        assert "more" in text

    def test_review_passed(self, monkeypatch):
        from plan_follow.plan_hooks import _build_review_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "passed",
        )
        current = _make_current(review_profile="strict")
        lines = _build_review_banner(current)
        text = "\n".join(lines)
        assert "PASSED" in text or "✅" in text

    def test_review_exception_handled(self, monkeypatch):
        """Lines 358-359: exception caught."""
        from plan_follow.plan_hooks import _build_review_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: (_ for _ in ()).throw(RuntimeError("review error")),
        )
        assert _build_review_banner(_make_current(review_profile="strict")) == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_health_banner (Lines 380-398)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildHealthBanner:
    """Health-Banner: Zeitstempel, Flap-Daempfung, sichtbare Fehler."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        import plan_follow.plan_hooks as ph

        ph._hook_cache.clear()
        yield
        ph._hook_cache.clear()

    def test_silent_when_ok(self, monkeypatch):
        import plan_follow.tools.health as health

        monkeypatch.setattr(
            health, "health_check", lambda: {"status": "ok", "issues": [], "pending": []}
        )
        from plan_follow.plan_hooks import _build_health_banner

        assert _build_health_banner() == []

    def test_single_failure_is_a_hint_only(self, monkeypatch):
        import plan_follow.tools.health as health

        monkeypatch.setattr(
            health,
            "health_check",
            lambda: {
                "status": "ok",
                "issues": [],
                "pending": ["plan_tools fehlt"],
                "checked_at": "2026-11-11T10:00:00+00:00",
            },
        )
        text = "\n".join(__import__("plan_follow.plan_hooks", fromlist=["x"])._build_health_banner())
        assert "noch nicht DEGRADED" in text

    def test_degraded_lists_issues_and_age(self, monkeypatch):
        import plan_follow.tools.health as health

        monkeypatch.setattr(
            health,
            "health_check",
            lambda: {
                "status": "degraded",
                "issues": ["a", "b", "c", "d"],
                "pending": [],
                "checked_at": "2026-11-11T10:00:00+00:00",
            },
        )
        from plan_follow.plan_hooks import _build_health_banner

        text = "\n".join(_build_health_banner())
        assert "DEGRADED" in text
        assert "geprüft" in text
        assert "d" not in text.split("a")[0] or "• d" not in text  # max 3 Issues
        assert "(Arbeit trotzdem möglich)" in text

    def test_exception_is_visible(self, monkeypatch):
        import plan_follow.tools.health as health

        def boom():
            raise RuntimeError("kaputt")

        monkeypatch.setattr(health, "health_check", boom)
        from plan_follow.plan_hooks import _build_health_banner

        text = "\n".join(_build_health_banner())
        assert "fehlgeschlagen" in text


class TestOnPreLLMCall:
    def test_no_current_task(self, monkeypatch):
        from plan_follow.plan_hooks import on_pre_llm_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        assert on_pre_llm_call() is None

    def test_full_banner(self, monkeypatch, mock_time):
        """Full banner path with git/drift/coord/tts/review/health/breaker sections."""
        from plan_follow.plan_hooks import on_pre_llm_call
        current = _make_current(review_profile="basic")
        plan = _make_plan(
            tts_flags={"plan_created": True},
            tasks={},
        )
        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: plan,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_git_status",
            lambda r: {"status": "ok", "branch": "main"},
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: ["f1.py"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "in_review",
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {"status": "ok"},
        )

        result = on_pre_llm_call()
        assert result is not None
        assert "[PLAN]" in result
        assert "CURRENT TASK" in result

    def test_banner_with_git_and_drift_separators(self, monkeypatch, mock_time):
        """Lines 416-418: git separator line is added."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import on_pre_llm_call
        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_git_status",
            lambda r: {"status": "ok", "branch": "main"},
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: ["f1.py"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "none",
        )
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {"status": "ok"},
        )

        result = on_pre_llm_call()
        assert result is not None

    def test_banner_with_coord_and_breaker(self, monkeypatch, mock_time):
        """Lines 426-428, 439-441: coord and breaker separators."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _set_breaker, on_pre_llm_call
        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "none",
        )
        monkeypatch.setattr(cs, "get_sessions", lambda: {"s1": {"goal": "Coord test"}})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {"status": "ok"},
        )
        _set_breaker("code_rename", "oops")
        result = on_pre_llm_call()
        assert result is not None
        assert "[PLAN]" in result

    def test_banner_with_health_lines(self, monkeypatch, mock_time):
        """Lines 434-437: health_lines separator is added when health degraded."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import on_pre_llm_call
        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "none",
        )
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {"status": "degraded", "issues": ["Disk space low"]},
        )

        result = on_pre_llm_call()
        assert result is not None
        assert "HEALTH" in result or "DEGRADED" in result or "Disk" in result

    def test_exception_handled(self, monkeypatch):
        """Lines 444-447: exception in on_pre_llm_call returns None."""
        from plan_follow.plan_hooks import on_pre_llm_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: (_ for _ in ()).throw(RuntimeError("unexpected error")),
        )
        assert on_pre_llm_call() is None


# ═══════════════════════════════════════════════════════════════════════════════
# on_post_tool_call (Lines 453-544)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnPostToolCall:
    def test_circuit_breaker_critical_error(self, monkeypatch, mock_time):
        """Lines 470-472: error on critical tool sets breaker."""
        from plan_follow.plan_hooks import _check_breaker, on_post_tool_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        on_post_tool_call(
            tool_name="code_refactor",
            duration_ms=100,
            status="error",
            error="Syntax failure in AST",
            args={},
        )
        active = _check_breaker()
        assert "code_refactor" in active
        assert "Syntax failure" in active["code_refactor"]["error"]

    def test_circuit_breaker_truncated_error(self, monkeypatch, mock_time):
        """Line 471: error truncated to 80 chars."""
        from plan_follow.plan_hooks import _check_breaker, on_post_tool_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        long_err = "x" * 200
        on_post_tool_call(
            tool_name="mcp_firecrawl_scrape",
            duration_ms=100,
            status="error",
            error=long_err,
            args={},
        )
        active = _check_breaker()
        assert len(active["mcp_firecrawl_scrape"]["error"]) == 80

    def test_circuit_breaker_ignores_non_critical(self, monkeypatch, mock_time):
        """Non-critical tool errors don't set breaker."""
        from plan_follow.plan_hooks import _check_breaker, on_post_tool_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        on_post_tool_call(
            tool_name="patch",
            duration_ms=100,
            status="error",
            error="Some error",
            args={},
        )
        assert _check_breaker() == {}

    def test_early_return_no_tracking(self, monkeypatch, mock_time):
        """Line 475-476: non-tracked tools are skipped."""
        from plan_follow.plan_hooks import on_post_tool_call
        calls = []
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: calls.append(("record", a, kw)),
        )
        # Should not call record_tool_call for non-tracked tools
        on_post_tool_call(tool_name="some_unknown_tool", duration_ms=0, status="ok")
        assert len(calls) == 0

    def test_records_metrics(self, monkeypatch, mock_time):
        """Tool call recording for tracked tools."""
        from plan_follow.plan_hooks import on_post_tool_call
        records = []
        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: records.append(a),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda *a, **kw: None,
        )

        on_post_tool_call(tool_name="code_search", duration_ms=200, status="ok", args={})
        assert len(records) >= 1

    def test_drift_tracking_outside_files(self, monkeypatch, mock_time):
        """Lines 499-509: drift warning when tool writes outside task files."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []
        current = _make_current(files=["/workspace/src/main.py"])
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )

        on_post_tool_call(
            tool_name="patch",
            duration_ms=100,
            status="ok",
            error="",
            args={"path": "/workspace/src/unrelated.py"},
        )
        assert len(drift_warnings) >= 1
        assert "unrelated" in drift_warnings[0] or "outside" in drift_warnings[0]

    def test_drift_tracking_inside_files(self, monkeypatch, mock_time):
        """No drift warning when tool writes inside task files."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []
        current = _make_current(files=["/workspace/src/main.py"])
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )

        on_post_tool_call(
            tool_name="patch",
            duration_ms=100,
            status="ok",
            error="",
            args={"path": "/workspace/src/main.py"},
        )
        assert len(drift_warnings) == 0

    def test_lock_enforcement_other_session(self, monkeypatch, mock_time):
        """Lines 519-528: lock enforcement for file locked by another session."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []
        current = _make_current(files=["/workspace/src/main.py"])
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )
        monkeypatch.setattr(
            cs, "get_lock",
            lambda path: {
                "session_id": "other-session",
                "since": "2024-01-01T00:00:00",
            } if "main.py" in path else None,
        )

        on_post_tool_call(
            tool_name="code_refactor",
            duration_ms=100,
            status="ok",
            error="",
            args={"path": "/workspace/src/main.py"},
        )
        assert len(drift_warnings) >= 1
        assert "gelockt" in drift_warnings[0] or "Lock" in drift_warnings[0]

    def test_lock_enforcement_exception(self, monkeypatch, mock_time):
        """Lines 527-528: lock enforcement exception caught."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import on_post_tool_call
        current = _make_current(files=["/workspace/src/main.py"])
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )
        monkeypatch.setattr(
            cs, "get_lock",
            lambda path: (_ for _ in ()).throw(RuntimeError("lock check failed")),
        )

        # Should not raise
        on_post_tool_call(
            tool_name="code_refactor",
            duration_ms=100,
            status="ok",
            error="",
            args={"path": "/workspace/src/main.py"},
        )

    def test_session_log_exception(self, monkeypatch, mock_time):
        """Lines 543-544: session log write failure is caught."""
        from plan_follow.plan_hooks import on_post_tool_call
        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            Path("/nonexistent_dir_for_test"),
        )

        # Should not raise
        on_post_tool_call(
            tool_name="code_search",
            duration_ms=100,
            status="ok",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# _build_task_header (Lines 78-87)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildTaskHeader:
    def test_basic(self):
        from plan_follow.plan_hooks import _build_task_header
        current = _make_current(files=["f1.py", "f2.py", "f3.py", "f4.py"])
        lines = _build_task_header(current)
        assert len(lines) >= 3
        assert any("CURRENT TASK" in line for line in lines)
        assert any("f1.py" in line for line in lines)
        # More than 3 files should show "..."
        text = "\n".join(lines)
        assert "..." in text

    def test_few_files(self):
        from plan_follow.plan_hooks import _build_task_header
        current = _make_current(files=["f1.py"])
        lines = _build_task_header(current)
        text = "\n".join(lines)
        assert "f1.py" in text
        assert "..." not in text


# ═══════════════════════════════════════════════════════════════════════════════
# Multilingual / German Umlaut support
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultilingualSupport:
    def test_roadmap_german_names(self, monkeypatch):
        """Plan-Namen mit deutschen Umlauten in Roadmap-Banner."""
        from plan_follow.plan_hooks import _build_roadmap_banner
        fake_rdata = {
            "name": "Änderungs-Roadmap für Überprüfung",
            "phases": [
                {"id": "p1", "name": "Phase 1 — Einführung", "status": "completed"},
                {"id": "p2", "name": "Phase 2 — Überarbeitung", "status": "in_progress"},
            ],
        }
        monkeypatch.setattr(
            "plan_follow.plan_roadmap.get_active_roadmap",
            lambda: ("rm1", fake_rdata),
        )
        monkeypatch.setattr(
            "plan_follow.plan_roadmap._get_phase_progress",
            lambda r: {"completed": 1, "total": 2},
        )
        monkeypatch.setattr(
            "plan_follow.plan_roadmap._get_next_phases",
            lambda r: [{"id": "p2", "name": "Phase 2 — Überarbeitung"}],
        )
        lines = _build_roadmap_banner()
        text = "\n".join(lines)
        assert "Änderungs-Roadmap" in text
        assert "Überarbeitung" in text

    def test_tts_german_task_names(self, monkeypatch):
        """TTS-Banner mit deutschen Umlauten."""
        from plan_follow.plan_hooks import _build_tts_banner
        plan = _make_plan(
            tts_flags={"task_completed": ["T1"]},
            tasks={"T1": {"name": "Überprüfung der Änderungen"}},
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: plan,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        lines = _build_tts_banner()
        text = "\n".join(lines)
        assert "Überprüfung" in text or "Änderungen" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_on_pre_llm_call_no_current(self, monkeypatch):
        """Line 410-411: no current task → None (Nudge hier deaktiviert)."""
        from plan_follow import plan_hooks
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        # Der Nudge (v0.5.34) ist eine eigene Funktion mit eigenen Tests; hier
        # geht es um das Banner-Verhalten ohne Task.
        monkeypatch.setattr(plan_hooks, "_NUDGE_ENABLED", False)
        assert plan_hooks.on_pre_llm_call() is None

    def test_git_banner_empty_plan_name(self, monkeypatch, mock_time):
        """Git banner with empty plan object edge case."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: [],
        )
        assert _build_git_banner() == []

    def test_build_banner_none_lines(self):
        """Line 68: _build_banner with None-ish lines."""
        from plan_follow.plan_hooks import _build_banner
        assert _build_banner([]) is None
        assert _build_banner(["", "  "]) is not None

    def test_coord_banner_empty_sessions_with_notifs(self, monkeypatch, mock_time):
        """Coordination banner with only notifications."""
        import plan_follow.plan_hooks as hooks
        hooks._coord_cache.clear()
        hooks._prev_coord_sig = ""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner
        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [{"id": "n1"}])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )
        lines = _build_coordination_banner()
        assert len(lines) > 0

    def test_tts_banner_empty_flag_lists(self, monkeypatch):
        """TTS banner with empty task_completed list."""
        from plan_follow.plan_hooks import _build_tts_banner
        plan = _make_plan(
            tts_flags={"task_completed": [], "review_failed": []},
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: plan,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        assert _build_tts_banner() == []

    def test_cached_or_fresh_not_called_on_hit(self, mock_time):
        """Ensure fetcher is not called on cache hit."""
        from plan_follow.plan_hooks import _cached_or_fresh, _hook_cache
        _hook_cache["k"] = ("val", 1000.0)
        called = [False]
        def dont_call():
            called[0] = True
            return "should_not_happen"
        _cached_or_fresh("k", dont_call, ttl=60)
        assert not called[0]

    def test_on_post_tool_call_error_result_fallback(self, monkeypatch, mock_time):
        """Kein Fallback auf 'result' mehr (v0.5.32).

        Hermes liefert error_type/error_message. Der frueher benutzte
        'result'-Fallback schrieb die komplette Tool-Ausgabe (bei terminal die
        volle stdout) als Fehlertext in den Breaker-Banner. Fehlt die Message,
        steht dort ein Platzhalter.
        """
        from plan_follow.plan_hooks import _check_breaker, on_post_tool_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        on_post_tool_call(
            tool_name="code_refactor",
            duration_ms=100,
            status="error",
            error_message="",
            result="Critical failure occurred",
            args={},
        )
        active = _check_breaker()
        assert "code_refactor" in active
        assert active["code_refactor"]["error"] == "(no error message)"
        assert "Critical failure" not in active["code_refactor"]["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# _do_coordination_housekeeping (Lines 26-62)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoordinationHousekeeping:
    """Housekeeping: Session-Heartbeat immer, Locks nur mit PLAN_FOLLOW_LOCKS=1."""

    def test_registers_session_with_locks(self, monkeypatch):
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        monkeypatch.setattr(plan_core, "_get_active_plan", lambda: {"plan_id": "p1", "goal": "G"})
        current = _make_current(task_id="T001", files=["/test/file.ts"])

        result = _do_coordination_housekeeping(current, session_id="s-42")

        assert result >= 1
        sessions = coord_state.get_sessions()
        assert "s-42" in sessions
        assert sessions["s-42"]["plan_id"] == "p1"

    def test_no_locks_without_flag(self, monkeypatch):
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        monkeypatch.delenv("PLAN_FOLLOW_LOCKS", raising=False)
        monkeypatch.setattr(plan_core, "_get_active_plan", lambda: {"plan_id": "p1", "goal": "G"})
        current = _make_current(task_id="T001", files=["/test/file.ts"])

        assert _do_coordination_housekeeping(current, session_id="s-42") == 0
        assert coord_state.get_locks() == {}
        assert "s-42" in coord_state.get_sessions()

    def test_releases_locks_when_task_changes(self, monkeypatch):
        import plan_follow.plan_hooks as ph
        from plan_follow import coord_state, plan_core

        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        monkeypatch.setattr(plan_core, "_get_active_plan", lambda: {"plan_id": "p1", "goal": "G"})
        coord_state.acquire_lock("/old/file.ts", "s-42")
        ph._LAST_LOCKED_TASK = "T001"

        ph._do_coordination_housekeeping(
            _make_current(task_id="T002", files=["/new/file.ts"]), session_id="s-42"
        )

        assert coord_state.get_lock("/old/file.ts") is None
        new_lock = coord_state.get_lock("/new/file.ts")
        assert new_lock is not None
        assert new_lock["session_id"] == "s-42"

    def test_task_without_files_locks_nothing(self, monkeypatch):
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        monkeypatch.setattr(plan_core, "_get_active_plan", lambda: {"plan_id": "p1", "goal": "G"})

        assert _do_coordination_housekeeping(_make_current(task_id="T1", files=[]), "s-1") == 0
        assert coord_state.get_locks() == {}

    def test_completed_plan_releases_and_clears(self, monkeypatch):
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        monkeypatch.setenv("PLAN_FOLLOW_LOCKS", "1")
        finished = {
            "plan_id": "p1",
            "goal": "G",
            "current_task": None,
            "tasks": {"t1": {"status": "completed"}},
        }
        monkeypatch.setattr(plan_core, "_get_active_plan", lambda: finished)
        coord_state.register_session("s-1", plan_id="p1", goal="G")
        coord_state.acquire_lock("/a.py", "s-1")

        _do_coordination_housekeeping(None, session_id="s-1")

        assert coord_state.get_locks() == {}
        assert not coord_state.get_session("s-1").get("plan_id")


class TestPlanLockTool:
    """Tests for plan_lock action=list and action=my."""

    def test_plan_lock_list(self, monkeypatch):
        """plan_lock action=list should return all locks."""
        from plan_follow import coord_state
        from plan_follow.plan_tools import plan_lock_tool
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        coord_state.acquire_lock("/file1.ts", "session-a")
        coord_state.acquire_lock("/file2.ts", "session-b")

        result = plan_lock_tool({"action": "list"})
        assert '"action": "list"' in result
        assert '"count": 2' in result
        assert "file1.ts" in result
        assert "file2.ts" in result

    def test_plan_lock_my(self, monkeypatch):
        """plan_lock action=my should return only own session's locks."""
        from plan_follow import coord_state
        from plan_follow.plan_tools import plan_lock_tool
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        coord_state.acquire_lock("/file1.ts", "session-a")
        coord_state.acquire_lock("/file2.ts", "session-b")

        result = plan_lock_tool({"action": "my"})
        assert '"action": "my"' in result
        assert '"count": 1' in result
        assert "file1.ts" in result
        assert "file2.ts" not in result

    def test_plan_lock_list_empty(self, monkeypatch):
        """plan_lock action=list with no locks should return count=0."""
        from plan_follow.plan_tools import plan_lock_tool
        result = plan_lock_tool({"action": "list"})
        assert '"count": 0' in result
        assert '"locks": []' in result


# ═══════════════════════════════════════════════════════════════════════════════
# Stale Lock Banner
# ═══════════════════════════════════════════════════════════════════════════════


class TestStaleLockBanner:
    """Stale-Lock Warning im Coordination Banner."""

    def test_stale_lock_warning(self, monkeypatch, mock_time):
        """Locks older than 30 minutes should trigger stale warning."""
        from plan_follow import coord_state  # noqa: I001
        from plan_follow.plan_hooks import _build_coordination_banner  # noqa: I001
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        locks_file = coord_state.LOCKS_FILE
        locks_file.parent.mkdir(parents=True, exist_ok=True)
        import json
        locks_file.write_text(json.dumps({
            "/stale/file.ts": {
                "session_id": "old-session",
                "since": old_ts,
            }
        }), encoding="utf-8")

        lines = _build_coordination_banner()
        assert any("Stale-Locks" in ln for ln in lines), "No stale lock warning in banner:\n" + "\n".join(lines)

    def test_no_stale_warning_for_fresh(self, monkeypatch, mock_time):
        """Locks newer than 30 minutes should NOT show stale warning."""
        from plan_follow import coord_state  # noqa: I001
        from plan_follow.plan_hooks import _build_coordination_banner  # noqa: I001
        from datetime import datetime, timezone
        fresh_ts = datetime.now(timezone.utc).isoformat()
        locks_file = coord_state.LOCKS_FILE
        locks_file.parent.mkdir(parents=True, exist_ok=True)
        import json
        locks_file.write_text(json.dumps({
            "/fresh/file.ts": {
                "session_id": "my-session",
                "since": fresh_ts,
            }
        }), encoding="utf-8")

        lines = _build_coordination_banner()
        stale_lines = [ln for ln in lines if "Stale-Locks" in ln]
        assert len(stale_lines) == 0, "Unexpected stale lock warning:\n" + "\n".join(stale_lines)


# ═══════════════════════════════════════════════════════════════════════════════
# plan_coord_cleanup Tool
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoordCleanup:
    """Tests for plan_coord_cleanup_tool."""

    def test_cleanup_dry_run(self, monkeypatch):
        """Dry run should report counts without removing."""
        from plan_follow import coord_state
        from plan_follow.plan_tools import plan_coord_cleanup_tool
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        coord_state.register_session("old-session", plan_id="p1")
        coord_state.acquire_lock("/old.ts", "old-session")

        result = plan_coord_cleanup_tool({"session_max_age": 0, "lock_max_age": 0, "dry_run": True})
        assert '"action": "dry_run"' in result
        assert '"stale_sessions": 1' in result
        assert '"stale_locks": 1' in result

        # Verify nothing was actually removed
        assert len(coord_state.get_sessions()) >= 1
        assert len(coord_state.get_locks()) >= 1

    def test_cleanup_executes(self, monkeypatch):
        """Cleanup should remove stale sessions and locks."""
        from plan_follow import coord_state
        from plan_follow.plan_tools import plan_coord_cleanup_tool
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        coord_state.register_session("old-session", plan_id="p1")
        coord_state.acquire_lock("/old.ts", "old-session")

        result = plan_coord_cleanup_tool({"session_max_age": 0, "lock_max_age": 0})
        assert '"action": "cleanup"' in result
        assert '"removed_sessions": 1' in result
        assert '"removed_locks": 1' in result

        # Verify removal
        assert "old-session" not in coord_state.get_sessions()
        assert coord_state.get_lock("/old.ts") is None

    def test_cleanup_keeps_fresh(self, monkeypatch):
        """Fresh sessions/locks should NOT be removed."""
        from plan_follow import coord_state
        from plan_follow.plan_tools import plan_coord_cleanup_tool
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        coord_state.register_session("fresh-session", plan_id="p1")
        coord_state.acquire_lock("/fresh.ts", "fresh-session")

        # max_age=999 should keep everything
        result = plan_coord_cleanup_tool({"session_max_age": 999, "lock_max_age": 999})
        assert '"action": "cleanup"' in result
        assert '"removed_sessions": 0' in result
        assert '"removed_locks": 0' in result

        assert "fresh-session" in coord_state.get_sessions()
        assert coord_state.get_lock("/fresh.ts") is not None


# ─────────────── P4: Notification + Conflict Tests ───────────────────────────


class TestNotifyTool:
    """Tests for plan_notify actions: send, check, list, clear."""

    def test_notify_send_and_check(self, monkeypatch):
        from plan_follow.plan_tools import plan_notify_tool
        from plan_follow.tools import base as _tb
        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        result = plan_notify_tool({"action": "send", "to": "session-b", "message": "Hi!", "kind": "info"})
        assert '"action": "sent"' in result

        # session-b should have the notification
        result2 = plan_notify_tool({"action": "check", "session_id": "session-b"})
        assert '"count": 1' in result2
        assert "Hi!" in result2

    def test_notify_list(self, monkeypatch):
        from plan_follow.plan_tools import plan_notify_tool
        from plan_follow.tools import base as _tb
        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        plan_notify_tool({"action": "send", "to": "session-a", "message": "Test1"})
        plan_notify_tool({"action": "send", "to": "session-a", "message": "Test2"})

        result = plan_notify_tool({"action": "list"})
        assert '"count": 2' in result
        assert "Test1" in result
        assert "Test2" in result

    def test_notify_clear(self, monkeypatch):
        from plan_follow.plan_tools import plan_notify_tool
        from plan_follow.tools import base as _tb
        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        plan_notify_tool({"action": "send", "to": "session-a", "message": "X"})
        result = plan_notify_tool({"action": "clear"})
        assert '"status": "cleared"' in result

        result2 = plan_notify_tool({"action": "list"})
        assert '"count": 0' in result2

    def test_notify_invalid_action(self):
        from plan_follow.plan_tools import plan_notify_tool
        result = plan_notify_tool({"action": "invalid"})
        assert "error" in result.lower() or "unknown" in result.lower()


class TestAutoNotifyOnConflict:
    """Acquire_lock should auto-notify the holder on conflict."""

    def test_auto_notify_on_lock_conflict(self, monkeypatch):
        from plan_follow import coord_state
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-b")
        _tb.reset_session_id()

        # session-a holds lock
        coord_state.acquire_lock("/shared/file.ts", "session-a")

        # session-b tries to acquire → should trigger auto-notification
        result = coord_state.acquire_lock("/shared/file.ts", "session-b")
        assert result["status"] == "exists"

        # session-a should now have a notification about the conflict
        notifs = coord_state.get_notifications("session-a", mark_read=False)
        assert len(notifs) >= 1
        assert any("Lock-Konflikt" in n.get("message", "") for n in notifs)
        assert any("session-b" in n.get("from", "") for n in notifs)

    def test_auto_notify_same_session_no_conflict(self, monkeypatch):
        """Same session re-acquiring lock should NOT send notification."""
        from plan_follow import coord_state
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "session-a")
        _tb.reset_session_id()

        coord_state.acquire_lock("/shared/file.ts", "session-a")
        # Clear any existing notifications
        coord_state.clear_notifications("session-a")

        # Same session re-acquires
        result = coord_state.acquire_lock("/shared/file.ts", "session-a")
        assert result["status"] == "acquired"

        notifs = coord_state.get_notifications("session-a", mark_read=False)
        conflict_msgs = [n for n in notifs if "Lock-Konflikt" in n.get("message", "")]
        assert len(conflict_msgs) == 0

    def test_notification_banner_shows_preview(self, monkeypatch, mock_time):
        """Coordination banner should show notification preview."""
        from plan_follow import coord_state
        from plan_follow.plan_hooks import _build_coordination_banner
        from plan_follow.tools import base as _tb

        monkeypatch.setenv("HERMES_SESSION_ID", "my-session")
        _tb.reset_session_id()

        # Send a notification to current session
        coord_state.send_notification("other-session", "my-session", "Test message", "info")

        lines = _build_coordination_banner()
        assert any("Test message" in ln for ln in lines), "No preview in banner:\n" + "\n".join(lines)
        assert any("other-session" in ln for ln in lines)



# ═══════════════════════════════════════════════════════════════════════════════
# v0.5.34: Nudge — einmaliger Hinweis ohne aktiven Plan
# ═══════════════════════════════════════════════════════════════════════════════


class TestNudge:
    """_nudge_line() feuert genau einmal pro Session, erst ab dem 3. Turn."""

    def _reset(self, monkeypatch, enabled=True):
        import plan_follow.plan_hooks as hooks

        monkeypatch.setattr(hooks, "_NUDGE_ENABLED", enabled)
        monkeypatch.setattr(hooks, "_NUDGE_SESSIONS", set())
        monkeypatch.setattr(hooks, "_nudge_turns", {})
        monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
        return hooks

    def test_nudge_waits_three_turns_then_fires_once(self, monkeypatch):
        hooks = self._reset(monkeypatch)

        assert hooks._nudge_line("sess-a") is None, "Turn 1 darf nicht nudgen"
        assert hooks._nudge_line("sess-a") is None, "Turn 2 darf nicht nudgen"

        line = hooks._nudge_line("sess-a")
        assert line, "Turn 3 muss den Hinweis liefern"
        assert "plan_create" in line
        assert "tool_call" in line, "Hinweis muss den Deferral-Aufrufweg nennen"

        assert hooks._nudge_line("sess-a") is None, "nur einmal pro Session"
        assert hooks._nudge_line("sess-a") is None

    def test_nudge_disabled(self, monkeypatch):
        hooks = self._reset(monkeypatch, enabled=False)
        for _ in range(10):
            assert hooks._nudge_line("sess-b") is None

    def test_nudge_skipped_in_delegated_child(self, monkeypatch):
        hooks = self._reset(monkeypatch)
        monkeypatch.setenv("HERMES_DELEGATED_CHILD_CONTEXT", "1")
        for _ in range(10):
            assert hooks._nudge_line("sess-c") is None

    def test_nudge_is_per_session(self, monkeypatch):
        hooks = self._reset(monkeypatch)

        for _ in range(2):
            hooks._nudge_line("sess-d")
        assert hooks._nudge_line("sess-d"), "Session d muss den Hinweis bekommen"
        # Andere Session hat ihren eigenen Zaehler
        hooks._nudge_line("sess-e")
        hooks._nudge_line("sess-e")
        assert hooks._nudge_line("sess-e"), "Session e muss ebenfalls den Hinweis bekommen"


class TestNudgeRendering:
    """Der Nudge muss durch das Banner passen (Zeilenlimit 96) und Cron meiden."""

    def _reset(self, monkeypatch):
        import plan_follow.plan_hooks as hooks

        monkeypatch.setattr(hooks, "_NUDGE_ENABLED", True)
        monkeypatch.setattr(hooks, "_NUDGE_SESSIONS", set())
        monkeypatch.setattr(hooks, "_nudge_turns", {})
        monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
        return hooks

    def test_each_line_fits_banner_limit(self, monkeypatch):
        """_build_banner schneidet bei 96 Zeichen — der Aufrufweg muss passen."""
        hooks = self._reset(monkeypatch)
        hooks._nudge_lines("s-1")
        hooks._nudge_lines("s-1")
        lines = hooks._nudge_lines("s-1")

        assert lines, "Nudge muss beim dritten Turn kommen"
        for line in lines:
            assert len(line) <= 90, f"Zeile zu lang ({len(line)}): {line}"
        joined = " ".join(lines)
        assert "tool_call" in joined, "Fallback-Aufrufweg fehlt"
        assert "plan_create" in joined

    def test_skipped_for_cron_platform(self, monkeypatch):
        hooks = self._reset(monkeypatch)
        for _ in range(5):
            assert hooks._nudge_lines("s-cron", "cron") == []

    def test_fires_for_cli_platform(self, monkeypatch):
        hooks = self._reset(monkeypatch)
        hooks._nudge_lines("s-cli", "cli")
        hooks._nudge_lines("s-cli", "cli")
        assert hooks._nudge_lines("s-cli", "cli"), "CLI muss den Hinweis bekommen"
