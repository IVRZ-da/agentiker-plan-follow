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
    """Control time.monotonic for deterministic tests."""
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
    def test_no_active_plan(self, monkeypatch):
        """Line 122-123: no active plan → empty."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: None,
        )
        assert _build_git_banner() == []

    def test_no_repos(self, monkeypatch):
        """Line 126-127: no repos → empty."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(repos=[]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: [],
        )
        assert _build_git_banner() == []

    def test_git_status_error(self, monkeypatch, mock_time):
        """Line 133-134: status not ok → skip."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace/repo"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_git_status",
            lambda r: {"status": "error", "error": "oops"},
        )
        assert _build_git_banner() == []

    def test_git_status_ok(self, monkeypatch, mock_time):
        """Lines 136-153: full git banner with branch, dirty, ahead/behind."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace/repo"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_git_status",
            lambda r: {
                "status": "ok",
                "branch": "main",
                "dirty": True,
                "dirty_files": 2,
                "ahead": 3,
                "behind": 1,
            },
        )
        lines = _build_git_banner()
        assert len(lines) >= 1
        text = "\n".join(lines)
        assert "repo" in text or "📍" in text
        assert "🌿main" in text
        assert "↑3↓1" in text
        assert "💩+2" in text

    def test_git_ahead_only(self, monkeypatch, mock_time):
        """Line 148-149: only ahead."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace/repo"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_git_status",
            lambda r: {
                "status": "ok", "branch": "main",
                "ahead": 5, "behind": 0, "dirty": False,
            },
        )
        lines = _build_git_banner()
        text = "\n".join(lines)
        assert "↑5" in text
        assert "↓" not in text or "↓0" in text

    def test_git_behind_only(self, monkeypatch, mock_time):
        """Line 150-151: only behind."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace/repo"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_git_status",
            lambda r: {
                "status": "ok", "branch": "main",
                "ahead": 0, "behind": 2, "dirty": False,
            },
        )
        lines = _build_git_banner()
        text = "\n".join(lines)
        assert "↓2" in text

    def test_git_exception_handled(self, monkeypatch):
        """Line 155-156: exception caught."""
        from plan_follow.plan_hooks import _build_git_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert _build_git_banner() == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_drift_banner (Lines 160-183)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildDriftBanner:
    def test_no_drift(self, monkeypatch, mock_time):
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        assert _build_drift_banner() == []

    def test_drift_detected(self, monkeypatch, mock_time):
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: ["src/file1.py", "src/file2.py"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        lines = _build_drift_banner()
        text = "\n".join(lines)
        assert "DRIFT" in text
        assert "src/file1.py" in text

    def test_drift_more_than_3(self, monkeypatch, mock_time):
        """Line 170: '... and N more' for drift files."""
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: ["f1.py", "f2.py", "f3.py", "f4.py"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        lines = _build_drift_banner()
        text = "\n".join(lines)
        assert "and 1 more" in text or "und 1 mehr" in text

    def test_drift_warnings(self, monkeypatch, mock_time):
        """Lines 175-180: proactive drift warnings."""
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: ["Warning: file modified outside task", "Second warning"],
        )
        lines = _build_drift_banner()
        text = "\n".join(lines)
        assert "DRIFT WARNING" in text
        assert "Warning" in text or "proaktiv" in text

    def test_drift_warnings_truncated(self, monkeypatch, mock_time):
        """Line 178-179: '... and N more' for warnings."""
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: ["w1", "w2", "w3"],
        )
        lines = _build_drift_banner()
        text = "\n".join(lines)
        assert "and 1 more" in text or "und 1 mehr" in text

    def test_drift_exception_handled(self, monkeypatch, mock_time):
        """Line 181-182: exception caught from get_drift_warnings."""
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: (_ for _ in ()).throw(RuntimeError("drift warnings failed")),
        )
        assert _build_drift_banner() == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_due_banner (Lines 186-206)
# ═══════════════════════════════════════════════════════════════════════════════

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
    def test_no_sessions_no_locks(self, monkeypatch, mock_time):
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
    def test_no_plan(self, monkeypatch):
        from plan_follow.plan_hooks import _build_tts_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: None,
        )
        assert _build_tts_banner() == []

    def test_no_tts_flags(self, monkeypatch):
        from plan_follow.plan_hooks import _build_tts_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(tts_flags=None),
        )
        assert _build_tts_banner() == []

    def test_plan_created_flag(self, monkeypatch):
        from plan_follow.plan_hooks import _build_tts_banner
        plan = _make_plan(tts_flags={"plan_created": True}, tasks={"T1": {"name": "Task 1"}})
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
        assert "TTS" in text or "plan_created" in text
        assert "plan_created" not in plan.get("tts_flags", {})

    def test_task_completed_flag(self, monkeypatch):
        from plan_follow.plan_hooks import _build_tts_banner
        plan = _make_plan(
            tts_flags={"task_completed": ["T1", "T2"]},
            tasks={"T1": {"name": "Erste Aufgabe"}, "T2": {"name": "Zweite Aufgabe"}},
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
        assert "TTS" in text
        # flags should be cleared after display
        assert plan.get("tts_flags", {}).get("task_completed") in ([], None)

    def test_review_failed_flag(self, monkeypatch):
        from plan_follow.plan_hooks import _build_tts_banner
        plan = _make_plan(
            tts_flags={"review_failed": ["T1"]},
            tasks={
                "T1": {
                    "name": "Failing Task",
                    "review_result": {
                        "issues": [
                            {"severity": "error", "check": "Missing docs"},
                            {"severity": "warning", "check": "Naming"},
                        ],
                    },
                },
            },
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
        assert "TTS" in text
        assert "review_failed" in text or "kritische" in text

    def test_tts_exception_handled(self, monkeypatch):
        """Lines 325-326: exception caught."""
        from plan_follow.plan_hooks import _build_tts_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: (_ for _ in ()).throw(RuntimeError("tts failed")),
        )
        assert _build_tts_banner() == []


# ═══════════════════════════════════════════════════════════════════════════════
# _build_review_banner (Lines 330-360)
# ═══════════════════════════════════════════════════════════════════════════════

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
    def test_health_ok(self, monkeypatch, mock_time):
        from plan_follow.plan_hooks import _build_health_banner
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {"status": "ok"},
        )
        assert _build_health_banner() == []

    def test_health_degraded(self, monkeypatch, mock_time):
        from plan_follow.plan_hooks import _build_health_banner
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {"status": "degraded", "issues": ["Disk full", "Memory low"]},
        )
        lines = _build_health_banner()
        text = "\n".join(lines)
        assert "DEGRADED" in text or "HEALTH" in text
        assert "Disk full" in text

    def test_health_issues_truncated(self, monkeypatch, mock_time):
        """Line 393-394: '... and N more' for health issues."""
        from plan_follow.plan_hooks import _build_health_banner
        monkeypatch.setattr(
            "plan_follow.tools.health.health_check",
            lambda: {
                "status": "degraded",
                "issues": ["i1", "i2", "i3", "i4"],
            },
        )
        lines = _build_health_banner()
        text = "\n".join(lines)
        assert "more" in text

    def test_health_exception_handled(self, monkeypatch, mock_time):
        """Lines 396-397: exception caught."""
        from plan_follow.plan_hooks import _build_health_banner
        # Make _cached_or_fresh throw to hit the except handler
        monkeypatch.setattr(
            "plan_follow.plan_hooks._cached_or_fresh",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("health failed")),
        )
        assert _build_health_banner() == []


# ═══════════════════════════════════════════════════════════════════════════════
# on_pre_llm_call (Lines 401-447)
# ═══════════════════════════════════════════════════════════════════════════════

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
        """Line 410-411: no current task → None."""
        from plan_follow.plan_hooks import on_pre_llm_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        assert on_pre_llm_call() is None

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
        """Line 471: fallback to result when error is empty."""
        from plan_follow.plan_hooks import _check_breaker, on_post_tool_call
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        on_post_tool_call(
            tool_name="code_refactor",
            duration_ms=100,
            status="error",
            error="",
            result="Critical failure occurred",
            args={},
        )
        active = _check_breaker()
        assert "code_refactor" in active
        assert "Critical failure" in active["code_refactor"]["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# _do_coordination_housekeeping (Lines 26-62)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCoordinationHousekeeping:
    """Auto-Lock + Session Heartbeat in pre_llm_call."""

    def test_housekeeping_registers_session(self, monkeypatch):
        """Session should be registered with plan_id + goal."""
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        monkeypatch.setattr(
            plan_core, "get_session_id", lambda: "test-session-42"
        )
        monkeypatch.setattr(
            plan_core, "_get_active_plan",
            lambda: {"plan_id": "p1", "goal": "Test Goal"},
        )
        current = _make_current(task_id="T001", files=["/test/file.ts"])

        result = _do_coordination_housekeeping(current)
        assert result >= 1  # locks acquired

        # Verify session was registered
        sessions = coord_state.get_sessions()
        assert "test-session-42" in sessions
        assert sessions["test-session-42"]["plan_id"] == "p1"

    def test_housekeeping_releases_on_task_change(self, monkeypatch):
        """When task_id changes, old locks should be released first."""
        import plan_follow.plan_hooks as _ph
        from plan_follow import coord_state
        from plan_follow.plan_hooks import _do_coordination_housekeeping
        from plan_follow.tools import base as _tb

        # Simulate session ID via env var (like Hermes runtime does)
        monkeypatch.setenv("HERMES_SESSION_ID", "test-session-42")
        # Reset session ID cache so it picks up the env var
        _tb.reset_session_id()

        # Create a lock from a "previous" session
        coord_state.acquire_lock("/old/file.ts", "test-session-42")
        assert coord_state.get_lock("/old/file.ts") is not None

        # Mock _get_active_plan
        monkeypatch.setattr(
            "plan_follow.tools.base._get_active_plan",
            lambda: {"plan_id": "p1", "goal": "Test"},
        )

        # Set global to simulate task change detection
        _ph._LAST_LOCKED_TASK = "T001"  # previous task

        current = _make_current(task_id="T002", files=["/new/file.ts"])
        _do_coordination_housekeeping(current)

        # Old lock should be gone
        assert coord_state.get_lock("/old/file.ts") is None
        # New lock should exist
        new_lock = coord_state.get_lock("/new/file.ts")
        assert new_lock is not None
        assert new_lock["session_id"] == "test-session-42"

    def test_housekeeping_no_files(self, monkeypatch):
        """Task with no files should not acquire locks."""
        from plan_follow import plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        monkeypatch.setattr(
            plan_core, "get_session_id", lambda: "test-session-42"
        )
        monkeypatch.setattr(
            plan_core, "_get_active_plan",
            lambda: {"plan_id": "p1", "goal": "Test"},
        )

        current = _make_current(task_id="T001", files=[])
        result = _do_coordination_housekeeping(current)
        assert result == 0

    def test_housekeeping_lock_conflict(self, monkeypatch):
        """Conflict detection: lock held by another session on task files."""
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        # Another session already holds lock on our file
        coord_state.acquire_lock("/shared/file.ts", "other-session")
        assert coord_state.get_lock("/shared/file.ts") is not None

        monkeypatch.setattr(
            plan_core, "get_session_id", lambda: "test-session-42"
        )
        monkeypatch.setattr(
            plan_core, "_get_active_plan",
            lambda: {"plan_id": "p1", "goal": "Test"},
        )

        current = _make_current(
            task_id="T001", files=["/shared/file.ts"]
        )
        result = _do_coordination_housekeeping(current)
        # Lock already exists (held by other), so acquire returns "exists"
        assert result == 0  # no NEW locks acquired
