"""conftest.py — Shared fixtures for plan_follow tests.

Patches _fmt.fmt_ok/fmt_err/fmt_info so tool handlers return JSON instead of
Rich-formatted text. Also patches all modules that import fmt_* directly
(since `from _fmt import fmt_ok` creates a local reference).
"""
import json
import sys
from pathlib import Path

import pytest

# Ensure plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Find all modules that import from _fmt
_modules_to_patch = []


def _import_paths():
    """Return list of module-import paths that reference _fmt functions."""
    base = Path(__file__).resolve().parent.parent  # plan_follow/
    for pyfile in base.rglob("*.py"):
        if "site-packages" in str(pyfile) or "__pycache__" in str(pyfile):
            continue
        rel = pyfile.relative_to(base)
        mod_parts = list(rel.parts)
        if mod_parts[-1] == "__init__.py":
            mod_parts = mod_parts[:-1]
        else:
            mod_parts[-1] = mod_parts[-1].replace(".py", "")
        mod_name = "plan_follow." + ".".join(mod_parts)
        try:
            content = pyfile.read_text()
            if "from .._fmt import" in content or "from ._fmt import" in content or "from _fmt import" in content:
                _modules_to_patch.append(mod_name)
        except Exception:
            pass
    return _modules_to_patch


_import_paths()


@pytest.fixture(autouse=True)
def patch_fmt(monkeypatch):
    """Automatically patch fmt_* so all tools return JSON."""
    import plan_follow._fmt as _fmt_mod

    def _json_fmt_ok(data: dict, title: str = "✅ Success") -> str:
        return json.dumps(data, ensure_ascii=False, default=str)

    def _json_fmt_err(msg: str, title: str = "❌ Error") -> str:
        return json.dumps({"error": msg, "status": "error"}, ensure_ascii=False)

    def _json_fmt_info(msg: str, title: str = "📝 Info") -> str:
        return json.dumps({"info": msg, "status": "no_active_plan", "message": msg},
                          ensure_ascii=False)

    # Patch the source module
    monkeypatch.setattr(_fmt_mod, "fmt_ok", _json_fmt_ok)
    monkeypatch.setattr(_fmt_mod, "fmt_err", _json_fmt_err)
    monkeypatch.setattr(_fmt_mod, "fmt_info", _json_fmt_info)

    # Also patch all modules that imported fmt_* directly
    for mod_name in _modules_to_patch:
        try:
            # Import module first if not already loaded
            if mod_name not in sys.modules:
                __import__(mod_name)
            mod = sys.modules.get(mod_name)
            if mod and hasattr(mod, "fmt_ok"):
                monkeypatch.setattr(mod, "fmt_ok", _json_fmt_ok)
            if mod and hasattr(mod, "fmt_err"):
                monkeypatch.setattr(mod, "fmt_err", _json_fmt_err)
            if mod and hasattr(mod, "fmt_info"):
                monkeypatch.setattr(mod, "fmt_info", _json_fmt_info)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def reset_shared_state():
    """Clear shared coord_state + plan_state between tests.

    coord_state stores locks/sessions/notifications in shared JSON files,
    plan_core caches plan state in memory. Without cleanup, tests leak
    state and subsequent tests fail with unexpected lock counts /
    None-banner returns.
    """
    from plan_follow import coord_state

    # Reset coord_state
    coord_state._SHARED_DIR_INIT = False
    for f in [coord_state.SESSIONS_FILE, coord_state.LOCKS_FILE,
              coord_state.NOTIFICATIONS_FILE]:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("{}")
        except Exception:
            pass

    # Reset plan_core caches
    from plan_follow import plan_core

    for attr in ['_tasks_cache', '_active_plan_cache', '_current_task_cache']:
        if hasattr(plan_core, attr):
            try:
                val = getattr(plan_core, attr)
                if isinstance(val, dict):
                    val.clear()
                else:
                    setattr(plan_core, attr, None)
            except Exception:
                pass

    # Reset plans_index.json and all plan files
    try:
        import shutil
        plans_dir = plan_core.PLANS_DIR
        if plans_dir and plans_dir.exists():
            for f in plans_dir.iterdir():
                if f.suffix == ".json":
                    f.write_text("{}")
                elif f.is_dir() and f.name != ".":
                    shutil.rmtree(f, ignore_errors=True)
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "plans_index.json").write_text("{}")
    except Exception:
        pass

    # Reset plan_hooks caches and state (critical: banner+coord+breaker state)
    try:
        import plan_follow.plan_hooks as hooks
        hooks._hook_cache.clear()
        hooks._prev_coord_sig = ""
        hooks._coord_cache.clear()
        hooks._breaker_state.clear()
        hooks._banner_turn_counter = 0
        hooks._last_task_id = None
    except Exception:
        pass

    # Reset tools.base STATE (active_plan, tool_metrics, drift_warnings)
    try:
        from plan_follow.tools import base as tools_base
        tools_base._reset_cache()
        tools_base.reset_tool_metrics()
    except Exception:
        pass

    # Reset plan_follow tools STATE (session_id, etc.)
    try:
        from plan_follow.tools.base import STATE as tools_state
        tools_state.session_id = None
        tools_state.tool_metrics = {}
        tools_state.drift_warnings = []
    except Exception:
        pass
