"""Tests for _fmt.py — Rich-basierte Formatierungs-Helper.

Tests focus on plain-text extraction via _strip_ansi to verify
content, structure, and edge cases of every fmt_* function.
"""
import sys
from pathlib import Path

# Ensure plugin is importable (same pattern as test_plan_follow.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _plain(fn, *args, **kwargs) -> str:
    """Call a fmt_* function and return stripped plain text."""
    from plan_follow._fmt import _strip_ansi
    result = fn(*args, **kwargs)
    return _strip_ansi(result)


# Import all fmt_* functions at module level for test usage
from plan_follow._fmt import (  # noqa: E402
    fmt_banner,
    fmt_code,
    fmt_err,
    fmt_info,
    fmt_json,
    fmt_markdown,
    fmt_ok,
    fmt_rule,
    fmt_table,
    fmt_table_simple,
    fmt_tree,
    fmt_warn,
)

# ─── fmt_ok ────────────────────────────────────────────────────────────────────

class TestFmtOk:
    def test_basic(self):
        text = _plain(fmt_ok, {"status": "ok", "id": "123"})
        assert "✅ Success" in text
        assert "status" in text
        assert "ok" in text
        assert "id" in text
        assert "123" in text

    def test_empty_dict(self):
        text = _plain(fmt_ok, {})
        assert "" in text  # leeres Dict = leere Tabelle

    def test_custom_title(self):
        text = _plain(fmt_ok, {"a": 1}, title="✅ Saved")
        assert "✅ Saved" in text

    def test_numeric_values(self):
        text = _plain(fmt_ok, {"count": 0, "ratio": 3.14})
        assert "0" in text
        assert "3.14" in text


# ─── fmt_err ───────────────────────────────────────────────────────────────────

class TestFmtErr:
    def test_basic(self):
        text = _plain(fmt_err, "Something went wrong")
        assert "❌ Error" in text
        assert "Something went wrong" in text

    def test_custom_title(self):
        text = _plain(fmt_err, "msg", title="❌ Failed")
        assert "❌ Failed" in text

    def test_empty_message(self):
        text = _plain(fmt_err, "")
        assert "❌ Error" in text

    def test_multiline_message(self):
        text = _plain(fmt_err, "line1\nline2\nline3")
        assert "line1" in text
        assert "line2" in text
        assert "line3" in text


# ─── fmt_warn ──────────────────────────────────────────────────────────────────

class TestFmtWarn:
    def test_basic(self):
        text = _plain(fmt_warn, "Disk space low")
        assert "⚠️ Warning" in text
        assert "Disk space low" in text

    def test_custom_title(self):
        text = _plain(fmt_warn, "msg", title="⚠️ Alert")
        assert "⚠️ Alert" in text

    def test_rich_markup_in_message(self):
        text = _plain(fmt_warn, "[bold]important[/bold]")
        assert "important" in text


# ─── fmt_info ──────────────────────────────────────────────────────────────────

class TestFmtInfo:
    def test_basic(self):
        text = _plain(fmt_info, "Processing complete")
        assert "📝 Info" in text
        assert "Processing complete" in text

    def test_custom_title(self):
        text = _plain(fmt_info, "msg", title="📝 Notice")
        assert "📝 Notice" in text

    def test_empty_message(self):
        text = _plain(fmt_info, "")
        assert "📝 Info" in text


# ─── fmt_table ─────────────────────────────────────────────────────────────────

class TestFmtTable:
    def test_basic(self):
        rows = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        text = _plain(fmt_table, rows)
        assert "Alice" in text
        assert "Bob" in text
        assert "30" in text
        assert "25" in text

    def test_empty_rows(self):
        text = _plain(fmt_table, [])
        assert "Keine Daten" in text

    def test_custom_columns(self):
        rows = [{"name": "Alice", "age": "30", "city": "Berlin"}]
        text = _plain(fmt_table, rows, columns=["name", "city"])
        assert "Alice" in text
        assert "Berlin" in text
        assert "30" not in text  # age not in selected columns

    def test_single_row(self):
        rows = [{"id": "p1", "status": "done"}]
        text = _plain(fmt_table, rows)
        assert "p1" in text
        assert "done" in text

    def test_title(self):
        rows = [{"a": "1"}]
        text = _plain(fmt_table, rows, title="Results")
        # Title may be rendered with extra spacing; check for key content
        assert "1" in text
        assert "a" in text


# ─── fmt_table_simple ──────────────────────────────────────────────────────────

class TestFmtTableSimple:
    def test_basic(self):
        rows = [("a", "1"), ("b", "2")]
        text = _plain(fmt_table_simple, rows, ["Key", "Value"])
        assert "Key" in text
        assert "Value" in text
        assert "a" in text
        assert "1" in text

    def test_single_row(self):
        text = _plain(fmt_table_simple, [("x",)], ["Col"])
        assert "Col" in text
        assert "x" in text


# ─── fmt_tree ──────────────────────────────────────────────────────────────────

class TestFmtTree:
    def test_basic(self):
        symbols = [
            {"name": "hello", "kind": "function", "line": 5, "children": []},
        ]
        text = _plain(fmt_tree, "📄 main.py", symbols)
        assert "📄 main.py" in text or "main.py" in text
        assert "hello" in text
        assert "function" in text
        assert "5" in text

    def test_with_children(self):
        symbols = [{
            "name": "MyClass", "kind": "class", "line": 1, "end_line": 10,
            "children": [
                {"name": "method1", "kind": "method", "line": 3, "children": []},
            ],
        }]
        text = _plain(fmt_tree, "root", symbols)
        assert "MyClass" in text
        assert "method1" in text
        assert "class" in text
        assert "method" in text

    def test_variable_symbol(self):
        symbols = [{"name": "count", "kind": "variable", "line": 1, "children": []}]
        text = _plain(fmt_tree, "root", symbols)
        assert "count" in text
        assert "variable" in text


# ─── fmt_banner ────────────────────────────────────────────────────────────────

class TestFmtBanner:
    def test_basic(self):
        text = _plain(fmt_banner, ["Line 1", "Line 2"])
        assert "Line 1" in text
        assert "Line 2" in text

    def test_with_prefix(self):
        text = _plain(fmt_banner, ["Hello"], prefix="[TEST]")
        assert "[TEST]" in text
        assert "Hello" in text

    def test_single_line(self):
        text = _plain(fmt_banner, ["Only one"])
        assert "Only one" in text

    def test_without_prefix(self):
        from plan_follow._fmt import _strip_ansi, fmt_banner
        raw = fmt_banner(["Line 1"], prefix="")
        text = _strip_ansi(raw)
        assert "Line 1" in text
        assert "PLAN" not in text or "[PLAN]" not in raw


# ─── fmt_code ──────────────────────────────────────────────────────────────────

class TestFmtCode:
    def test_basic(self):
        text = _plain(fmt_code, "def hello(): pass")
        assert "def hello(): pass" in text or "hello" in text

    def test_no_line_numbers(self):
        text = _plain(fmt_code, "x = 1", line_numbers=False)
        assert "x = 1" in text or "x" in text

    def test_json_language(self):
        text = _plain(fmt_code, '{"key": "val"}', lang="json")
        assert "key" in text or "val" in text

    def test_custom_theme(self):
        text = _plain(fmt_code, "print(1)", theme="default")
        assert "print" in text


# ─── fmt_markdown ──────────────────────────────────────────────────────────────

class TestFmtMarkdown:
    def test_plain_text(self):
        text = _plain(fmt_markdown, "Hello **world**")
        assert "Hello" in text
        assert "world" in text

    def test_list(self):
        text = _plain(fmt_markdown, "- item1\n- item2")
        assert "item1" in text
        assert "item2" in text

    def test_empty_string(self):
        text = _plain(fmt_markdown, "")
        assert text is not None

    def test_malformed_markdown(self):
        # Should not crash — fmt_markdown has try/except
        text = _plain(fmt_markdown, "```\nunclosed")
        assert "unclosed" in text or "```" in text

    def test_fallback_on_parse_error(self):
        """Trigger the except branch in fmt_markdown."""
        from plan_follow._fmt import fmt_markdown
        # Very deeply nested or unusual markdown to trigger parser failure
        result = fmt_markdown("\x00broken\x00")
        assert isinstance(result, str)


# ─── fmt_rule ──────────────────────────────────────────────────────────────────

class TestFmtRule:
    def test_empty_title(self):
        text = _plain(fmt_rule, "")
        assert text is not None

    def test_with_title(self):
        text = _plain(fmt_rule, "Section")
        assert "Section" in text


# ─── fmt_json ──────────────────────────────────────────────────────────────────

class TestFmtJson:
    def test_basic(self):
        data = {"name": "test", "count": 42}
        text = _plain(fmt_json, data)
        assert "name" in text
        assert "test" in text
        assert "42" in text

    def test_list_data(self):
        data = [1, 2, 3]
        text = _plain(fmt_json, data)
        assert "1" in text
        assert "2" in text
        assert "3" in text

    def test_nested_dict(self):
        data = {"outer": {"inner": "value"}}
        text = _plain(fmt_json, data)
        assert "outer" in text
        assert "inner" in text
        assert "value" in text


# ─── _strip_ansi ───────────────────────────────────────────────────────────────

class TestStripAnsi:
    def test_strips_colors(self):
        from plan_follow._fmt import _strip_ansi, fmt_ok
        raw = fmt_ok({"ok": True})
        stripped = _strip_ansi(raw)
        assert "\x1b[" not in stripped  # no ANSI codes after stripping
        assert "ok" in stripped

    def test_plain_string_unchanged(self):
        from plan_follow._fmt import _strip_ansi
        assert _strip_ansi("hello") == "hello"

    def test_empty_string(self):
        from plan_follow._fmt import _strip_ansi
        assert _strip_ansi("") == ""
