"""_fmt.py muss auch ohne `rich` funktionieren.

Hermes bringt rich mit, das Plugin-eigene .venv (und jeder schlanke Runner)
nicht. Bis v0.5.31 war `from rich import box` ein harter Import auf Modulebene:
13 Testdateien konnten nicht mal eingesammelt werden
(``ModuleNotFoundError: No module named 'rich'``).

Der Test laedt _fmt in einem Subprozess mit blockiertem rich-Import und ruft
alle 12 Formatter auf — so bleibt der rich-Pfad der anderen Tests unberuehrt.
"""
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PARENT = PLUGIN_DIR.parent

FORMATTERS = [
    "fmt_ok", "fmt_err", "fmt_warn", "fmt_info", "fmt_table", "fmt_table_simple",
    "fmt_tree", "fmt_banner", "fmt_code", "fmt_markdown", "fmt_rule", "fmt_json",
]

_PROBE = r'''
import sys
sys.modules["rich"] = None  # blockiert jeden rich-Import
sys.path.insert(0, {parent!r})

import plan_follow._fmt as f

assert f.HAS_RICH is False, "rich wurde nicht blockiert"
missing = [name for name in {formatters!r} if not hasattr(f, name)]
assert not missing, f"Formatter fehlen: {{missing}}"

out = {{
    "ok": f.fmt_ok({{"alpha": 1}}),
    "err": f.fmt_err("boom"),
    "warn": f.fmt_warn("warnung"),
    "info": f.fmt_info("info"),
    "table": f.fmt_table([{{"k": "v"}}], ["k"]),
    "table_simple": f.fmt_table_simple([["zelle"]], ["spalte"]),
    "tree": f.fmt_tree("wurzel", [{{"name": "fn", "kind": "function", "line": 3}}]),
    "banner": f.fmt_banner(["zeile1"], prefix="[PLAN]"),
    "code": f.fmt_code("print(1)", line_numbers=False),
    "markdown": f.fmt_markdown("# titel"),
    "rule": f.fmt_rule("abschnitt"),
    "json": f.fmt_json({{"x": 1}}),
}}

for key, value in out.items():
    assert isinstance(value, str) and value, f"{{key}} lieferte nichts"

assert "alpha" in out["ok"] and "1" in out["ok"], out["ok"]
assert "boom" in out["err"], out["err"]
assert "v" in out["table"], out["table"]
assert "zelle" in out["table_simple"], out["table_simple"]
assert "fn" in out["tree"], out["tree"]
assert "zeile1" in out["banner"], out["banner"]
assert "print(1)" in out["code"], out["code"]
assert "titel" in out["markdown"], out["markdown"]
assert "<" not in out["tree"], f"Rich-Markup nicht entfernt: {{out['tree']}}"
assert f._strip_ansi(out["ok"]) == out["ok"], "Fallback enthaelt ANSI-Codes"
print("FALLBACK-OK", len(out))
'''.format(parent=str(PARENT), formatters=FORMATTERS)


def test_fmt_works_without_rich():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"Fallback fehlgeschlagen:\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}"
    )
    assert "FALLBACK-OK 12" in result.stdout


def test_has_no_hard_rich_import_at_module_level():
    """Regression: 'from rich import ...' darf nicht ungeschuetzt auf Modulebene stehen."""
    source = (PLUGIN_DIR / "_fmt.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith(("from rich", "import rich")):
            assert any(
                marker in line or marker in (lines[idx - 2] if idx >= 2 else "")
                for marker in ("try:", "except", "    ")
            ), f"_fmt.py:{idx} importiert rich ungeschuetzt: {line}"
    assert "HAS_RICH" in source
    assert "except ImportError" in source
