"""Regression: der Health-Selbst-Check darf im Host-Layout nicht faelschlich DEGRADED melden.

Der Host laedt Plugins unter einem Namespace-Paket (``hermes_plugins.plan_follow``) und
legt das Plugin-Verzeichnis NICHT auf ``sys.path``. Ein absoluter Import
(``importlib.import_module("plan_follow.plan_hooks")``) schlaegt dort strukturell fehl —
der Banner meldete dann "SYSTEM HEALTH DEGRADED", obwohl die Module im selben Prozess
liefen. Der Fall wird im Subprozess nachgestellt, weil das Plugin dafuer unter einem
fremden Paketnamen geladen werden muss (Modul-Identitaet im Test-Prozess).
"""

import subprocess
import sys
import textwrap
from pathlib import Path

# Ensure plugin is importable (analog test_health.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

PLUGIN = Path(__file__).resolve().parent.parent

_LOAD_UNDER_NAMESPACE = textwrap.dedent(
    """
    import importlib.util, sys, types
    from pathlib import Path

    DIR = Path(sys.argv[1])
    NS = "hermes_plugins.plan_follow"
    # wie im Host: das Plugin-Verzeichnis steht nicht auf sys.path
    sys.path = [p for p in sys.path if "plan_follow" not in p and "plugins" not in p]
    ns = types.ModuleType("hermes_plugins")
    ns.__path__ = []
    sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(
        NS, DIR / "__init__.py", submodule_search_locations=[str(DIR)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[NS] = mod
    spec.loader.exec_module(mod)

    from hermes_plugins.plan_follow.tools import health
    issues = health._self_check()
    print("ISSUES:", issues)
    raise SystemExit(0 if not issues else 1)
    """
)


def test_self_check_clean_under_namespace_loading():
    """Geladenes Plugin im Namespace -> keine Issues (sonst Banner-DEGRADED)."""
    proc = subprocess.run(
        [sys.executable, "-c", _LOAD_UNDER_NAMESPACE, str(PLUGIN)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/tmp",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_self_check_error_names_the_failing_module(monkeypatch):
    """Ein echter Ladefehler nennt Modul + Ursache, nicht nur die Exception-Klasse."""
    from plan_follow.tools import health

    def boom(short):
        raise ModuleNotFoundError("No module named 'rich'")

    monkeypatch.setattr(health, "_plugin_module", boom)
    issues = health._self_check()
    assert len(issues) == 2
    assert "plan_hooks" in issues[0] and "ModuleNotFoundError" in issues[0]
    assert "rich" in issues[0]


def test_plugin_module_prefers_loaded_instance(monkeypatch):
    """Das geladene Modul gewinnt — kein zweiter Import, keine Dublette."""
    from plan_follow.tools import health

    sentinel = object()
    monkeypatch.setitem(sys.modules, "plan_follow.plan_hooks", sentinel)
    assert health._plugin_module("plan_hooks") is sentinel
