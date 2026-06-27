"""conftest.py - Test config for plan_follow tests.

This runs at module-import time to mock Hermes dependencies
before any plan_follow module is imported.
"""

import json
import sys
import types
from unittest.mock import patch

import pytest

# ─── Early mocks (runs at module level, BEFORE test collection) ───────────────
# These are needed because test files import plan_follow at module level.

if "hermes_cli" not in sys.modules:
    hermes_cli = types.ModuleType("hermes_cli")
    hermes_cli.__path__ = []
    hermes_cli.plugins = types.ModuleType("hermes_cli.plugins")
    hermes_cli.plugins.PluginContext = type("MockPluginContext", (), {
        "register_tool": lambda self, **kw: None,
        "register_hook": lambda self, **kw: None,
        "register_skill": lambda self, **kw: None,
    })
    sys.modules["hermes_cli"] = hermes_cli
    sys.modules["hermes_cli.plugins"] = hermes_cli.plugins

if "tools" not in sys.modules:
    tools_mod = types.ModuleType("tools")
    tools_mod.registry = types.ModuleType("tools.registry")
    tools_mod.registry.get_entry = lambda n: None
    tools_mod.registry.deregister = lambda n: None
    sys.modules["tools"] = tools_mod
    sys.modules["tools.registry"] = tools_mod.registry


@pytest.fixture(autouse=True)
def temp_shared_dir(tmp_path):
    """Redirect coord_state's SHARED_DIR to a temp directory per worker.

    This prevents parallel xdist workers from corrupting each other's
    shared state files (sessions.json, locks.json, notifications.json).
    Uses set_shared_dir() which updates all file paths atomically.
    """
    from plan_follow import coord_state
    temp_shared = tmp_path / "shared"
    temp_shared.mkdir(exist_ok=True)
    coord_state.set_shared_dir(temp_shared)


@pytest.fixture(autouse=True)
def mock_fmt():
    """Mock _fmt output functions to return JSON.

    Patches ALL handler submodules because they import from _fmt at
    module level, which captures the reference before the fixture runs.
    Uses create=True so modules that don't import a specific fmt_*
    function still get the patch.
    """
    handler_modules = [
        # Original handler files (backward-compat stubs)
        "plan_follow.tools.handlers_crud",
        "plan_follow.tools.handlers_git",
        "plan_follow.tools.handlers_misc",
        "plan_follow.tools.handlers_review",
        # New locations after module split
        "plan_follow.tools.git",
        "plan_follow.tools.review",
        "plan_follow.tools.task",
        "plan_follow.tools.status",
        "plan_follow.tools.auto",
        "plan_follow.tools.plan_mgmt",
        "plan_follow.tools.validation",
        "plan_follow.coord_state",
        "plan_follow.plan_decompose",
        "plan_follow.plan_sync",
        "plan_follow.plan_suggest",
        "plan_follow.plan_templates",
        "plan_follow.plan_todo",
    ]
    _fmt_funcs = {
        "fmt_ok": lambda d, **kw: json.dumps(d, ensure_ascii=False),
        "fmt_err": lambda m, **kw: json.dumps({"error": m}),
        "fmt_info": lambda m, **kw: json.dumps({"info": m, "status": "no_active_plan", "message": m}),
        "fmt_table": lambda rows, **kw: json.dumps(rows, ensure_ascii=False),
    }

    patchers = []
    for mod_name in handler_modules:
        for name, side_effect_fn in _fmt_funcs.items():
            p = patch(f"{mod_name}.{name}", side_effect=side_effect_fn, create=True)
            p.start()
            patchers.append(p)

    try:
        yield
    finally:
        for p in patchers:
            p.stop()
