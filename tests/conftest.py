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
def mock_fmt():
    """Mock _fmt output functions to return JSON."""
    with patch("plan_follow.plan_tools.fmt_ok", side_effect=lambda d, **kw: json.dumps(d, ensure_ascii=False)):
        with patch("plan_follow.plan_tools.fmt_err", side_effect=lambda m, **kw: json.dumps({"error": m})):
            with patch("plan_follow.plan_tools.fmt_info", side_effect=lambda m, **kw: json.dumps({"info": m, "status": "no_active_plan", "message": m})):
                with patch("plan_follow.plan_tools.fmt_table", side_effect=lambda rows, **kw: json.dumps(rows, ensure_ascii=False)):
                    with patch("plan_follow.plan_todo.fmt_ok", side_effect=lambda d, **kw: json.dumps(d, ensure_ascii=False)):
                        yield
