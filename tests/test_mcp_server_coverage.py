"""Coverage tests for plan_follow.mcp_server — targets uncovered lines 32-34, 316-359, 362, 374-385.

All tests are self-contained and rely on the same mocks as test_mcp_server.py.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─── Ensure the plugin package is on sys.path (same as test_mcp_server.py) ─
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent  # → plugins/
sys.path.insert(0, str(_PLUGIN_ROOT))

# ─── Mock tools.registry (required by plan_core submodules) ──────────────
registry_mock = types.ModuleType("tools.registry")
registry_mock.registry = types.SimpleNamespace()
registry_mock.registry._entries = {}


class _MockEntry:
    def __init__(self, name):
        self.name = name
        self.schema = {"description": ""}


_mock_registry = {
    "plan_create": _MockEntry("plan_create"),
    "plan_current": _MockEntry("plan_current"),
    "plan_complete": _MockEntry("plan_complete"),
    "plan_verify": _MockEntry("plan_verify"),
    "plan_status": _MockEntry("plan_status"),
    "plan_update": _MockEntry("plan_update"),
    "code_search": _MockEntry("code_search"),
    "code_refactor": _MockEntry("code_refactor"),
    "code_definition": _MockEntry("code_definition"),
    "mcp_firecrawl_firecrawl_search": _MockEntry("mcp_firecrawl_firecrawl_search"),
    "mcp_firecrawl_firecrawl_scrape": _MockEntry("mcp_firecrawl_firecrawl_scrape"),
}


def _mock_get_entry(name):
    return _mock_registry.get(name)


registry_mock.registry.get_entry = _mock_get_entry
sys.modules["tools.registry"] = registry_mock

# ─── Mock hermes_cli.plugins (required by plan_core submodules) ──────────
hermes_cli_mock = types.ModuleType("hermes_cli")
hermes_cli_mock.plugins = types.ModuleType("hermes_cli.plugins")
hermes_cli_mock.plugins.PluginContext = type("PluginContext", (), {})
sys.modules["hermes_cli"] = hermes_cli_mock
sys.modules["hermes_cli.plugins"] = hermes_cli_mock.plugins

# ─── Now we can safely import the module under test ──────────────────────
from plan_follow import mcp_server as mcp  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════
# Helper: Extract MCPHandler class from inside run_http()
# ═══════════════════════════════════════════════════════════════════════════
# MCPHandler is defined as a local class inside run_http(), so we can't
# import it directly.  We trick the server into revealing it by patching
# HTTPServer.__init__ to capture the handler class on construction, then
# immediately abort with KeyboardInterrupt.


@pytest.fixture(scope="session")
def mcp_handler_class():
    """Return the MCPHandler class defined inside run_http()."""
    from http.server import HTTPServer

    captured: dict = {}

    def capturing_init(self, addr, cls):
        captured["cls"] = cls
        # Call real __init__ so no AttributeError on server.server_close()
        return HTTPServer.__init__(self, addr, cls)

    with patch.object(HTTPServer, "__init__", capturing_init):
        with patch.object(HTTPServer, "serve_forever", side_effect=KeyboardInterrupt()):
            with patch.object(mcp.logger, "info"), patch.object(mcp.logger, "debug"):
                try:
                    mcp.run_http("127.0.0.1", 0)
                except Exception:
                    pass

    cls = captured.get("cls")
    if cls is None:
        raise RuntimeError("Could not extract MCPHandler class")
    return cls


def _make_handler(cls, body: bytes, **kwargs):
    """Create a bare MCPHandler instance with mocked wiring.

    Returns (handler, wfile) where wfile is the BytesIO that captures
    the JSON response body written by the handler.
    """
    handler = object.__new__(cls)
    handler.headers = {"Content-Length": str(len(body)), **kwargs.get("extra_headers", {})}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.command = "POST"
    handler.path = "/"
    handler.request_version = "HTTP/1.0"
    handler.requestline = "POST / HTTP/1.0"
    # Mock the response-header methods so they don't write junk to wfile
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    return handler


import io  # noqa: E402 — needed by _make_handler, kept here so top-level is tidy

# ═══════════════════════════════════════════════════════════════════════════
# Lines 32-34: _get_core() — sys.path.insert + import plan_core
# ═══════════════════════════════════════════════════════════════════════════


class TestGetCoreReal:
    """Exercise the real _get_core function body (uncovered lines 32-34).

    The existing autouse fixture in test_mcp_server.py replaces _get_core
    with a mock.  This file does *not* have that fixture, so we test the
    real function directly.
    """

    def test_get_core_inserts_path_and_imports(self):
        """_get_core inserts plugin dir into sys.path (line 32) and imports plan_core."""
        plugin_dir = str(Path(mcp.__file__).resolve().parent)
        orig_path = list(sys.path)

        # The real fn calls sys.path.insert(0, plugin_dir) — ensure clean slate
        while plugin_dir in sys.path:
            sys.path.remove(plugin_dir)

        try:
            core = mcp._get_core()
            # Successfully imported plan_core
            assert core is not None
            # Verify path was inserted at front
            assert sys.path[0] == plugin_dir
        except ImportError:
            # If relative imports inside plan_core fail when loaded as
            # top-level module, we still verify the path manipulation
            assert plugin_dir in sys.path
        finally:
            sys.path[:] = orig_path

    def test_get_core_returns_plan_core_module(self):
        """_get_core returns the real plan_core module with expected attributes."""
        # Pre-populate sys.modules so 'import plan_core' finds the already-
        # loaded plan_follow.plan_core package (avoids relative-import blowup)
        from plan_follow import plan_core as pf_plan_core
        from plan_follow.mcp_server import _get_core as real_get_core
        sys.modules["plan_core"] = pf_plan_core
        try:
            core = real_get_core()
            assert core is pf_plan_core
            for attr in ("_load_plan", "_get_active_plan", "_save_plan", "list_plans"):
                assert hasattr(core, attr), f"plan_core missing expected attribute: {attr}"
        finally:
            sys.modules.pop("plan_core", None)


# ═══════════════════════════════════════════════════════════════════════════
# Lines 316-359: MCPHandler.do_POST()
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPHandlerDoPOST:
    """Test the real MCPHandler.do_POST HTTP handler.

    The handler class is extracted from inside run_http() via the
    mcp_handler_class fixture, then instantiated with mocked wiring.
    """

    # ── list_tools (line 324-335) ────────────────────────────────────────

    def test_do_POST_list_tools(self, mcp_handler_class):
        """do_POST returns tool list for method=list_tools (covers 324-335, 351-354)."""
        body = json.dumps({"method": "list_tools", "id": 1}).encode()
        handler = _make_handler(mcp_handler_class, body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "application/json")
        assert handler.end_headers.called

        response = json.loads(handler.wfile.getvalue())
        assert response["id"] == 1
        tools = response["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "list_plans" in tool_names
        assert "get_plan" in tool_names
        assert "get_active_plan" in tool_names

    # ── call_tool (line 336-347) ─────────────────────────────────────────

    def test_do_POST_call_tool_list_plans(self, mcp_handler_class):
        """do_POST dispatches call_tool → list_plans (covers 336-340, 347)."""
        with patch.object(mcp, "list_plans", return_value='{"success": true, "plans": []}'):
            body = json.dumps({
                "method": "call_tool", "id": 2,
                "params": {"name": "list_plans", "arguments": {}},
            }).encode()
            handler = _make_handler(mcp_handler_class, body)

            handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue())
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["success"] is True

    def test_do_POST_call_tool_get_plan(self, mcp_handler_class):
        """do_POST dispatches call_tool → get_plan (covers 341-342)."""
        with patch.object(mcp, "get_plan", return_value='{"success": true, "plan": {}}'):
            body = json.dumps({
                "method": "call_tool", "id": 3,
                "params": {"name": "get_plan", "arguments": {"plan_id": "test"}},
            }).encode()
            handler = _make_handler(mcp_handler_class, body)

            handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue())
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["success"] is True

    def test_do_POST_call_tool_get_active_plan(self, mcp_handler_class):
        """do_POST dispatches call_tool → get_active_plan (covers 343-344)."""
        with patch.object(mcp, "get_active_plan", return_value='{"success": true, "plan": {}}'):
            body = json.dumps({
                "method": "call_tool", "id": 4,
                "params": {"name": "get_active_plan", "arguments": {}},
            }).encode()
            handler = _make_handler(mcp_handler_class, body)

            handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue())
        content = json.loads(response["result"]["content"][0]["text"])
        assert content["success"] is True

    def test_do_POST_call_tool_unknown_tool(self, mcp_handler_class):
        """do_POST returns error for unknown tool name (covers 345-346)."""
        body = json.dumps({
            "method": "call_tool", "id": 5,
            "params": {"name": "bogus_tool", "arguments": {}},
        }).encode()
        handler = _make_handler(mcp_handler_class, body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue())
        result_text = response["result"]["content"][0]["text"]
        assert "Unknown: bogus_tool" in result_text

    # ── unknown method (line 348-349) ────────────────────────────────────

    def test_do_POST_unknown_method(self, mcp_handler_class):
        """do_POST returns empty result for unknown method (covers 348-349)."""
        body = json.dumps({"method": "nonexistent", "id": 6}).encode()
        handler = _make_handler(mcp_handler_class, body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(200)
        response = json.loads(handler.wfile.getvalue())
        assert response["id"] == 6
        assert response["result"] == {}

    # ── error path — bad JSON (line 355-359) ─────────────────────────────

    def test_do_POST_bad_json(self, mcp_handler_class):
        """do_POST returns 500 when request body is not valid JSON (covers 355-359)."""
        body = b"this is not json"
        handler = _make_handler(mcp_handler_class, body)

        handler.do_POST()

        handler.send_response.assert_called_once_with(500)
        handler.send_header.assert_any_call("Content-Type", "application/json")
        assert handler.end_headers.called
        response = json.loads(handler.wfile.getvalue())
        assert "error" in response

    def test_do_POST_exception_in_tool(self, mcp_handler_class):
        """do_POST returns 500 when a tool function raises (covers 355-359)."""
        with patch.object(mcp, "list_plans", side_effect=RuntimeError("boom")):
            body = json.dumps({
                "method": "call_tool", "id": 7,
                "params": {"name": "list_plans", "arguments": {}},
            }).encode()
            handler = _make_handler(mcp_handler_class, body)

            handler.do_POST()

        handler.send_response.assert_called_once_with(500)
        response = json.loads(handler.wfile.getvalue())
        assert "error" in response


# ═══════════════════════════════════════════════════════════════════════════
# Line 362: MCPHandler.log_message
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPHandlerLogMessage:
    """Test the log_message override on MCPHandler."""

    def test_log_message_delegates_to_logger(self, mcp_handler_class):
        """log_message calls logger.debug with HTTP prefix (line 362)."""
        handler = object.__new__(mcp_handler_class)
        with patch.object(mcp.logger, "debug") as mock_debug:
            handler.log_message("Status %d: %s", 200, "OK")
        mock_debug.assert_called_once_with("HTTP %s", "Status 200: OK")


# ═══════════════════════════════════════════════════════════════════════════
# Lines 374-385: if __name__ == "__main__" block (argparse + dispatch)
# ═══════════════════════════════════════════════════════════════════════════


class TestMainBlock:
    """Test the argparse and dispatch logic at module bottom (lines 374-385).

    These tests execute the ACTUAL if-main block code from the source file,
    so coverage.py registers lines 374-385 as executed.
    """

    @staticmethod
    def _exec_main_block(argv):
        """Exec the if-main block (lines 374-385) from the real source file.

        Reads the block code, compiles it with the real file path so that
        coverage.py can track the lines, and runs it with patched deps
        and ``__name__ == '__main__'`` to trigger execution.
        """
        filepath = mcp.__file__
        with open(filepath) as f:
            all_lines = f.readlines()

        # Lines 373-385 (1-indexed) → indices 372-384 (0-indexed)
        # Include the 'if __name__ == "__main__":' guard + block body
        block_code = "".join(all_lines[372:385])

        with patch.object(sys, "argv", list(argv)):
            p1 = patch("plan_follow.mcp_server.run_stdio")
            p2 = patch("plan_follow.mcp_server.run_http")
            mock_run_stdio = p1.start()
            mock_run_http = p2.start()
            try:
                # Build a globals dict from the module's namespace so that
                # run_http / run_stdio (now pointing to our mocks) are visible.
                globals_dict = dict(mcp.__dict__)
                globals_dict["__name__"] = "__main__"

                code_obj = compile(block_code, filepath, "exec")
                # Adjust co_firstlineno so that coverage.py records the
                # correct absolute line numbers (line 1 of snippet → line 373)
                code_obj = code_obj.replace(co_firstlineno=373)

                exec(code_obj, globals_dict)
            finally:
                p1.stop()
                p2.stop()
        return mock_run_stdio, mock_run_http

    def test_main_block_default_stdio(self):
        """Default --transport=stdio calls run_stdio (lines 374-385)."""
        mock_stdio, mock_http = self._exec_main_block(["mcp_server.py"])
        mock_stdio.assert_called_once()
        mock_http.assert_not_called()

    def test_main_block_http_transport(self):
        """--transport=http calls run_http with host/port (lines 374-385)."""
        mock_stdio, mock_http = self._exec_main_block(
            ["mcp_server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "9999"]
        )
        mock_http.assert_called_once_with("0.0.0.0", 9999)
        mock_stdio.assert_not_called()

    def test_main_block_http_default_host_port(self):
        """--transport=http uses default host/port when not specified (lines 374-385)."""
        mock_stdio, mock_http = self._exec_main_block(
            ["mcp_server.py", "--transport", "http"]
        )
        mock_http.assert_called_once_with("127.0.0.1", 8123)
        mock_stdio.assert_not_called()

    def test_main_block_stdio_explicit(self):
        """Explicit --transport=stdio calls run_stdio (lines 374-385)."""
        mock_stdio, mock_http = self._exec_main_block(
            ["mcp_server.py", "--transport", "stdio"]
        )
        mock_stdio.assert_called_once()
        mock_http.assert_not_called()
