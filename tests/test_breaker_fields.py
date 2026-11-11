"""Circuit-Breaker-Felder: Hermes sendet error_type/error_message, nicht 'error'.

Befund vor dem Fix: ``plan_hooks.on_post_tool_call`` las ``kwargs["error"]``
(existiert seit v0.23.1 nicht mehr). Der Wert war immer leer, und der Fallback
``kwargs["result"]`` schrieb die komplette Tool-Ausgabe — bei ``terminal`` also
die volle stdout — als "Fehlertext" in den Breaker-Banner.
"""
import json

import pytest
from plan_follow import plan_hooks


@pytest.fixture(autouse=True)
def clear_breaker():
    plan_hooks._breaker_state.clear()
    yield
    plan_hooks._breaker_state.clear()


def _post(**kwargs):
    plan_hooks.on_post_tool_call(**kwargs)


def test_breaker_uses_error_message():
    _post(tool_name="mcp_firecrawl_firecrawl_scrape", status="error",
          error_type="TimeoutError", error_message="connection refused after 30s",
          result="riesiger tool output")
    entry = plan_hooks._breaker_state["mcp_firecrawl_firecrawl_scrape"]
    assert "connection refused" in entry["error"]
    assert "TimeoutError" in entry["error"]
    assert "riesiger tool output" not in entry["error"]


def test_breaker_does_not_leak_tool_result():
    big_output = "X" * 10_000
    _post(tool_name="research_start", status="error",
          error_type="ValueError", error_message="bad input",
          result=big_output)
    entry = plan_hooks._breaker_state["research_start"]
    assert "XXXX" not in entry["error"]
    assert "bad input" in entry["error"]


def test_breaker_without_message_uses_placeholder():
    _post(tool_name="analysis_report", status="error", result=json.dumps({"ok": False}))
    entry = plan_hooks._breaker_state["analysis_report"]
    assert entry["error"] == "(no error message)"


def test_breaker_ignores_non_error_status():
    _post(tool_name="code_search", status="ok", error_type="", error_message="")
    assert "code_search" not in plan_hooks._breaker_state


def test_breaker_ignores_non_critical_tools():
    _post(tool_name="read_file", status="error", error_message="nope")
    assert "read_file" not in plan_hooks._breaker_state
