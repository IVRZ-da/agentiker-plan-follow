"""Tests for hooks/breaker.py — Circuit Breaker (100% coverage)."""

import sys
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Make plan_follow importable ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Stub missing plan_follow.hooks.base so the hooks package imports normally ─
# hooks/__init__.py imports from .base which doesn't exist yet. We create
# a stub in sys.modules so that coverage can track the breaker module.
_base = types.ModuleType("plan_follow.hooks.base")
_base.__path__ = []
# Provide all symbols that hooks/__init__.py imports from .base
_sentinel_attrs = {
    "_BANNER_COMPACT_EVERY_N_TURNS": 5,
    "_BANNER_FULL_EVERY_N_TURNS": 20,
    "_HEALTH_CACHE_KEY": "health",
    "_HEALTH_CACHE_TTL": 300,
    "_HOOK_CACHE_TTL": 60,
    "_PLAN_KEYWORDS": ("plan", "todo", "roadmap"),
    "_banner_last_task_id": None,
    "_banner_turn_counter": 0,
    "_build_banner": lambda **kw: [],
    "_build_compact_banner": lambda **kw: [],
    "_build_coordination_banner": lambda **kw: [],
    "_build_drift_banner": lambda **kw: [],
    "_build_due_banner": lambda **kw: [],
    "_build_git_banner": lambda **kw: [],
    "_build_health_banner": lambda **kw: [],
    "_build_review_banner": lambda **kw: [],
    "_build_roadmap_banner": lambda **kw: [],
    "_build_task_header": lambda **kw: "",
    "_build_tts_banner": lambda **kw: [],
    "_cached_or_fresh": lambda **kw: {},
    "_get_last_user_message": lambda **kw: "",
    "_has_plan_keywords": lambda **kw: False,
    "_hook_cache": {},
    "_last_task_id": None,
    "invalidate_hook_cache": lambda: None,
}
for _name, _val in _sentinel_attrs.items():
    setattr(_base, _name, _val)
sys.modules["plan_follow.hooks.base"] = _base

# Now normal import works
from plan_follow.hooks.breaker import (  # noqa: E402
    _BREAKER_CRITICAL_PREFIXES,
    _BREAKER_TTL,
    _breaker_state,
    _build_breaker_banner,
    _check_breaker,
    _set_breaker,
)

# Need module reference for patching time.monotonic
_breaker_mod = sys.modules["plan_follow.hooks.breaker"]


@pytest.fixture(autouse=True)
def reset_breaker_state():
    """Clear module-level breaker state before each test."""
    _breaker_state.clear()
    yield
    _breaker_state.clear()


# ─── Constants ──────────────────────────────────────────────────────────────


class TestConstants:
    def test_breaker_ttl_is_300(self):
        assert _BREAKER_TTL == 300

    def test_critical_prefixes_tuple(self):
        assert isinstance(_BREAKER_CRITICAL_PREFIXES, tuple)
        expected = {
            "honcho_", "mcp_firecrawl_", "analysis_", "bug_hunt_",
            "research_", "code_", "plan_",
        }
        assert set(_BREAKER_CRITICAL_PREFIXES) == expected


# ─── _set_breaker ───────────────────────────────────────────────────────────


class TestSetBreaker:
    def test_sets_state_entry(self):
        """_set_breaker stores an entry in _breaker_state."""
        _set_breaker("honcho_deploy", "Connection refused")
        assert "honcho_deploy" in _breaker_state
        entry = _breaker_state["honcho_deploy"]
        assert entry["error"] == "Connection refused"
        assert "ts" in entry

    def test_truncates_error_to_80_chars(self):
        """Error messages longer than 80 chars are truncated."""
        long_error = "x" * 200
        _set_breaker("code_build", long_error)
        entry = _breaker_state["code_build"]
        assert len(entry["error"]) == 80
        assert entry["error"] == "x" * 80

    def test_sets_timestamp(self):
        """The ts field is a reasonable monotonic timestamp."""
        now = time.monotonic()
        _set_breaker("plan_sync", "Timeout")
        entry = _breaker_state["plan_sync"]
        assert abs(entry["ts"] - now) < 1.0

    def test_overwrites_existing_entry(self):
        """Setting the same tool name overwrites the previous entry."""
        _set_breaker("honcho_deploy", "Error 1")
        _set_breaker("honcho_deploy", "Error 2")
        assert _breaker_state["honcho_deploy"]["error"] == "Error 2"

    def test_multiple_tools_independent(self):
        """Each tool gets its own circuit breaker entry."""
        _set_breaker("honcho_deploy", "Error A")
        _set_breaker("code_build", "Error B")
        assert len(_breaker_state) == 2
        assert _breaker_state["honcho_deploy"]["error"] == "Error A"
        assert _breaker_state["code_build"]["error"] == "Error B"


# ─── _check_breaker ─────────────────────────────────────────────────────────


class TestCheckBreaker:
    def test_returns_empty_dict_when_nothing_tripped(self):
        """No breakers tripped → empty dict."""
        assert _check_breaker() == {}

    def test_returns_active_entries(self):
        """Returns entries that have not expired."""
        _set_breaker("honcho_deploy", "Down")
        result = _check_breaker()
        assert "honcho_deploy" in result

    def test_removes_expired_entry(self):
        """Entries older than TTL are removed and not returned."""
        fake_now = 1000.0
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now):
            _set_breaker("honcho_deploy", "Old error")

        # Advance time past TTL
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now + _BREAKER_TTL + 1):
            result = _check_breaker()
        assert "honcho_deploy" not in result
        # Entry should also be removed from the internal dict
        assert "honcho_deploy" not in _breaker_state

    def test_expired_entries_dont_affect_non_expired(self):
        """Only expired entries are removed; non-expired ones remain."""
        fake_now = 1000.0
        # Set first entry at t=1000 (will expire at 1300)
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now):
            _set_breaker("honcho_deploy", "Old error")

        # Set second entry at t=1200 (won't expire until 1500)
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now + 200):
            _set_breaker("code_build", "Current error")

        # Advance to t=1301 — first entry expired, second still active
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now + _BREAKER_TTL + 1):
            result = _check_breaker()

        assert "honcho_deploy" not in result
        assert "code_build" in result
        assert result["code_build"]["error"] == "Current error"

    def test_returns_copy_not_reference(self):
        """Returns a dict copy — modifying it doesn't affect internal state."""
        _set_breaker("honcho_deploy", "Error")
        result = _check_breaker()
        result["new_tool"] = {"error": "fake", "ts": 0.0}
        assert "new_tool" not in _breaker_state


# ─── _build_breaker_banner ──────────────────────────────────────────────────


class TestBuildBreakerBanner:
    def test_returns_empty_list_when_no_active_breakers(self):
        """No active breakers → empty list."""
        assert _build_breaker_banner() == []

    def test_returns_banner_with_single_entry(self):
        """Single active breaker produces correct banner."""
        _set_breaker("honcho_deploy", "Connection refused")
        lines = _build_breaker_banner()
        assert len(lines) >= 3
        assert "CIRCUIT BREAKER ACTIVE" in lines[0]
        assert "honcho_deploy" in "".join(lines)
        assert "Nur lesende Analyse" in "".join(lines)

    def test_banner_includes_tool_name_and_error(self):
        """Banner lines include the tool name and truncated error."""
        _set_breaker("honcho_deploy", "Connection refused")
        lines = _build_breaker_banner()
        tool_line = [line for line in lines if "honcho_deploy" in line]
        assert len(tool_line) >= 1
        assert "Connection refused" in tool_line[0]

    def test_shows_max_3_entries(self):
        """Only the first 3 entries are shown; remaining are summarized."""
        _set_breaker("honcho_a", "err1")
        _set_breaker("honcho_b", "err2")
        _set_breaker("honcho_c", "err3")
        _set_breaker("honcho_d", "err4")
        lines = _build_breaker_banner()
        # Count tool entries
        tool_lines = [line for line in lines if "honcho_" in line]
        assert len(tool_lines) <= 3
        # Should mention "und 1 weitere" (1 more)
        summary_line = [line for line in lines if "weitere" in line]
        assert len(summary_line) == 1
        assert "1" in summary_line[0]

    def test_shows_und_n_weitere_for_multiple_overflow(self):
        """With N extra entries beyond 3, shows 'und N weitere'."""
        for i in range(6):
            _set_breaker(f"honcho_{i}", f"err-{i}")
        lines = _build_breaker_banner()
        summary_line = [line for line in lines if "weitere" in line]
        assert len(summary_line) == 1
        assert "3" in summary_line[0]  # 6 total - 3 shown = 3 more

    def test_no_overflow_line_when_3_or_fewer(self):
        """No 'und N weitere' line when there are 3 or fewer entries."""
        _set_breaker("honcho_a", "err1")
        _set_breaker("honcho_b", "err2")
        _set_breaker("honcho_c", "err3")
        lines = _build_breaker_banner()
        summary_lines = [line for line in lines if "weitere" in line]
        assert len(summary_lines) == 0

    def test_all_banner_lines_in_output(self):
        """Verify the full banner structure with a single entry."""
        _set_breaker("honcho_deploy", "Down")
        lines = _build_breaker_banner()
        # Expected structure: header, tool line(s), read-only line, decision line
        assert "CIRCUIT BREAKER ACTIVE" in lines[0]
        assert "Nur lesende Analyse" in lines[-2]
        assert "Johannes entscheiden lassen" in lines[-1]

    def test_expired_entries_cleared_during_banner_build(self):
        """_build_breaker_banner calls _check_breaker which cleans expired entries."""
        fake_now = 1000.0
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now):
            _set_breaker("honcho_deploy", "Error")

        # Advance past TTL
        with patch.object(_breaker_mod.time, "monotonic", return_value=fake_now + _BREAKER_TTL + 1):
            lines = _build_breaker_banner()

        assert lines == []
        assert "honcho_deploy" not in _breaker_state


# ─── Reset / Manual clear ───────────────────────────────────────────────────


class TestResetCircuit:
    def test_clear_all_state(self):
        """Manually clearing _breaker_state works as a full reset."""
        _set_breaker("honcho_deploy", "Error")
        assert len(_breaker_state) == 1
        _breaker_state.clear()
        assert len(_breaker_state) == 0
        assert _check_breaker() == {}

    def test_remove_single_entry(self):
        """Removing a single tool from _breaker_state works."""
        _set_breaker("honcho_a", "Error A")
        _set_breaker("honcho_b", "Error B")
        _breaker_state.pop("honcho_a", None)
        result = _check_breaker()
        assert "honcho_a" not in result
        assert "honcho_b" in result


# ─── Critical-Prefixes ──────────────────────────────────────────────────────


class TestCriticalPrefixes:
    def test_prefixes_tuple_is_immutable(self):
        """The prefix tuple cannot be mutated (no append method, no item assignment)."""
        assert not hasattr(_BREAKER_CRITICAL_PREFIXES, "append")
        with pytest.raises(TypeError):
            _BREAKER_CRITICAL_PREFIXES[0] = "other_"


# ─── Edge Cases ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_error_string(self):
        """Empty error string is accepted."""
        _set_breaker("honcho_test", "")
        assert _breaker_state["honcho_test"]["error"] == ""

    def test_very_short_error(self):
        """Very short error messages work fine."""
        _set_breaker("honcho_test", "!")
        assert _breaker_state["honcho_test"]["error"] == "!"

    def test_external_modifications_to_breaker_state(self):
        """External modifications to _breaker_state are visible."""
        _breaker_state["external_tool"] = {"error": "manual", "ts": time.monotonic()}
        result = _check_breaker()
        assert "external_tool" in result
