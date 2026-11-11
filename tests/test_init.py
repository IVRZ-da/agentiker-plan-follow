"""Tests for __init__.py — Plugin registration, hooks, steering hints."""

import logging
import pathlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Mock PluginContext ───────────────────────────────────────────────────────

class MockPluginContext:
    """Simulates Hermes PluginContext for testing registration."""

    def __init__(self):
        self.tools = {}
        self.hooks = {}
        self.skills = {}

    def register_tool(self, name, toolset, schema, handler, description, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_skill(self, name, path, description, **kwargs):
        self.skills[name] = {"path": path, "description": description}


# ─── _register_tools ──────────────────────────────────────────────────────────

class TestRegisterTools:
    """Tests for _register_tools — registers all 24 plan tools."""

    def _call(self, ctx=None):
        """Helper to call _register_tools with fresh imports."""
        from plan_follow.__init__ import _register_tools
        _register_tools(ctx or MockPluginContext())
        return ctx

    def test_registers_all_24_tools(self):
        """All 24 PLAN_TOOLS entries are registered."""
        ctx = self._call(MockPluginContext())
        assert len(ctx.tools) >= 24
        assert "plan_create" in ctx.tools
        assert "plan_current" in ctx.tools
        assert "plan_complete" in ctx.tools
        assert "plan_todo" in ctx.tools
        assert "plan_roadmap" in ctx.tools
        assert "plan_git_init" in ctx.tools
        assert "plan_history" in ctx.tools

    def test_each_tool_has_schema(self):
        """Every registered tool has a non-empty schema with parameters."""
        ctx = self._call(MockPluginContext())
        for name, info in ctx.tools.items():
            schema = info["schema"]
            # Schema must have either top-level properties (raw) or
            # properties nested under parameters (OpenAI format)
            has_props = (
                "properties" in schema
                or (
                    "parameters" in schema
                    and isinstance(schema["parameters"], dict)
                    and "properties" in schema["parameters"]
                )
            )
            assert has_props, f"{name} has no properties in schema"

    def test_each_tool_has_handler(self):
        """Every registered tool has a callable handler."""
        ctx = self._call(MockPluginContext())
        for name, info in ctx.tools.items():
            assert callable(info["handler"]), f"{name} handler is not callable"

    def test_register_tools_schema_descriptions(self):
        """Verify specific tool descriptions."""
        ctx = self._call(MockPluginContext())
        create_schema = ctx.tools["plan_create"]["schema"]
        # Support both raw format (properties on top) and OpenAI format (under parameters)
        props = create_schema.get("properties", {})
        if not props and "parameters" in create_schema:
            props = create_schema["parameters"].get("properties", {})
        assert "goal" in props
        assert "tasks" in props

    def test_plan_todo_has_merge_param(self):
        """plan_todo should have a 'merge' parameter."""
        ctx = self._call(MockPluginContext())
        todo_schema = ctx.tools["plan_todo"]["schema"]
        props = todo_schema.get("properties", {})
        if not props and "parameters" in todo_schema:
            props = todo_schema["parameters"].get("properties", {})
        assert "todos" in props or "merge" in props


# ─── _register_hooks ──────────────────────────────────────────────────────────

class TestRegisterHooks:
    """Tests for _register_hooks — registers pre_llm_call + post_tool_call."""

    def test_registers_both_hooks(self):
        """pre_llm_call and post_tool_call hooks are registered."""
        from plan_follow.__init__ import _register_hooks
        ctx = MockPluginContext()
        _register_hooks(ctx)
        assert "pre_llm_call" in ctx.hooks
        assert "post_tool_call" in ctx.hooks

    def test_hooks_are_callable(self):
        """Both hooks are callable functions."""
        from plan_follow.__init__ import _register_hooks
        ctx = MockPluginContext()
        _register_hooks(ctx)
        assert callable(ctx.hooks["pre_llm_call"])
        assert callable(ctx.hooks["post_tool_call"])


# ─── _register_skill ──────────────────────────────────────────────────────────

class TestRegisterSkill:
    def test_skill_registered_when_file_exists(self):
        """Skill MUSS registriert werden — die Datei heisst skills/SKILL.md.

        Vor v0.5.32 pruefte _register_skill auf 'plan-follow.md', fand nichts und
        registrierte den Companion-Skill stillschweigend nie. Der Test war bedingt
        formuliert ('if ... in ctx.skills') und konnte deshalb nie fehlschlagen.
        """
        from plan_follow.__init__ import _register_skill

        ctx = MockPluginContext()
        _register_skill(ctx)
        assert "plan-follow" in ctx.skills, "Companion-Skill wurde nicht registriert"
        assert ctx.skills["plan-follow"].get("description")
        path = ctx.skills["plan-follow"].get("path")
        assert path is not None and pathlib.Path(str(path)).exists(), f"Skill-Datei fehlt: {path}"

    def test_skill_has_name_and_description(self):
        """Registered skill has proper metadata."""
        from plan_follow.__init__ import _register_skill
        ctx = MockPluginContext()
        _register_skill(ctx)
        if "plan-follow" in ctx.skills:
            skill = ctx.skills["plan-follow"]
            assert skill["description"]
            assert "plan" in skill["description"].lower()


# ─── _inject_steering_hints ───────────────────────────────────────────────────

class TestInjectSteeringHints:
    def test_deregisters_todo(self):
        """Built-in 'todo' tool is deregistered."""
        from plan_follow.__init__ import _inject_steering_hints
        registry = MagicMock()
        with patch.dict("sys.modules", {"tools.registry": MagicMock(registry=registry)}):
            _inject_steering_hints()
        registry.deregister.assert_called_once_with("todo")

    def test_adds_hint_to_plan_create(self):
        """plan_create gets a steering hint appended."""
        from plan_follow.__init__ import _inject_steering_hints
        mock_entry = MagicMock()
        mock_entry.schema = {"description": "Create a plan."}
        registry = MagicMock()
        registry.get_entry.return_value = mock_entry

        with patch.dict("sys.modules", {"tools.registry": MagicMock(registry=registry)}):
            _inject_steering_hints()

        registry.get_entry.assert_any_call("plan_create")
        assert "plan_current" in mock_entry.schema["description"]

    def test_handles_import_error(self):
        """Silently handles ImportError when tools.registry not available."""
        from plan_follow.__init__ import _inject_steering_hints
        with patch.dict("sys.modules", {}):
            # Should not raise
            _inject_steering_hints()

    def test_handles_registry_exception(self, caplog):
        """Handles generic exception from registry gracefully."""
        from plan_follow.__init__ import _inject_steering_hints
        registry = MagicMock()
        registry.deregister.side_effect = RuntimeError("Registry error")

        with patch.dict("sys.modules", {"tools.registry": MagicMock(registry=registry)}):
            _inject_steering_hints()
        registry.deregister.assert_called_once_with("todo")

    def test_skips_hint_when_already_present(self):
        """Does not add duplicate hint to plan_create description."""
        from plan_follow.__init__ import _inject_steering_hints
        hint = "\n\nAfter creating a plan, call plan_current() to see the first task. Complete tasks in order: plan_complete(task_id) when done, then plan_current() shows the next one."  # noqa: E501
        mock_entry = MagicMock()
        mock_entry.schema = {"description": "Basic creation." + hint}
        registry = MagicMock()
        registry.get_entry.return_value = mock_entry

        with patch.dict("sys.modules", {"tools.registry": MagicMock(registry=registry)}):
            _inject_steering_hints()

        # Description should not be modified since hint is already present
        assert mock_entry.schema["description"] == "Basic creation." + hint


# ─── register ─────────────────────────────────────────────────────────────────

class TestRegister:
    def test_calls_all_registration_functions(self):
        """Plugin entry point calls all 4 registration functions."""
        from plan_follow.__init__ import register
        ctx = MockPluginContext()

        with patch("plan_follow.__init__._register_tools") as mock_tools, \
             patch("plan_follow.__init__._register_hooks") as mock_hooks, \
             patch("plan_follow.__init__._register_skill") as mock_skill, \
             patch("plan_follow.__init__._inject_steering_hints") as mock_hints:

            register(ctx)

        mock_tools.assert_called_once_with(ctx)
        mock_hooks.assert_called_once_with(ctx)
        mock_skill.assert_called_once_with(ctx)
        mock_hints.assert_called_once()

    def test_creates_log_message(self, caplog):
        """Register logs success message."""
        caplog.set_level(logging.INFO)
        from plan_follow.__init__ import register
        ctx = MockPluginContext()

        with patch("plan_follow.__init__._register_tools"), \
             patch("plan_follow.__init__._register_hooks"), \
             patch("plan_follow.__init__._register_skill"), \
             patch("plan_follow.__init__._inject_steering_hints"):

            register(ctx)

        assert "registered successfully" in caplog.text
