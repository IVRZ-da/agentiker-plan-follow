"""conftest.py — Shared fixtures for plan_follow tests.

Zwei Isolationsebenen:

1. **Import-Zeit-Isolation (Modul-Ebene, vor jeder Collection):** alle sieben
   Pfadkonstanten, die plan_follow zur Import-Zeit aufloest, werden auf ein
   temporaeres Test-Root umgebogen. Eine session-scoped Fixture waere zu spaet
   (plan_core.PLANS_DIR & Co. entstehen beim Import). Zusaetzlich wird
   PLAN_FOLLOW_TEST_GUARD=1 gesetzt, damit der Produktions-Write-Guard
   (tools/paths.py) jeden Schreibzugriff auf ~/.hermes/* hart abweist.
2. **Per-Test-Reset:** Caches/State werden zwischen Tests geleert — ausschliesslich
   innerhalb des Test-Roots. Es gibt hier bewusst kein ``except Exception: pass``
   mehr: genau das hat am 10.11.2026 den stillen Datenverlust in ~/.hermes/plans
   ermoeglicht (Suite gruen, Daten weg).
"""
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Import-Zeit-Isolation (MUSS vor dem ersten Test greifen) ────────────────
_REAL_HERMES = (Path.home() / ".hermes").resolve()
# Geschuetzte Produktions-Wurzeln. Das Test-Root darf innerhalb von ~/.hermes
# liegen (Hermes-Scratch), aber niemals in einer dieser Wurzeln.
_PROTECTED_ROOTS = (
    _REAL_HERMES / "plans",
    _REAL_HERMES / "roadmaps",
    _REAL_HERMES / "shared",
)
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="plan_follow_tests_"))
_TEST_PLANS = _TEST_ROOT / "plans"
_TEST_ROADMAPS = _TEST_ROOT / "roadmaps"
_TEST_SHARED = _TEST_ROOT / "shared"
for _d in (_TEST_PLANS, _TEST_ROADMAPS, _TEST_SHARED):
    _d.mkdir(parents=True, exist_ok=True)

# Der Produktions-Guard (tools/paths.py) wirft bei Schreibzugriffen auf echte Roots.
os.environ["PLAN_FOLLOW_TEST_GUARD"] = "1"
# Env-Overrides greifen bereits beim Import von plan_follow (plan_core,
# coord_state, plan_templates, plan_suggest) — dadurch isoliert auch der
# Import-Zeit-Init (coord_state._ensure_shared_dir) und jeder Subprozess.
os.environ["PLAN_FOLLOW_PLANS_DIR"] = str(_TEST_PLANS)
os.environ["PLAN_FOLLOW_ROADMAPS_DIR"] = str(_TEST_ROADMAPS)
os.environ["PLAN_FOLLOW_SHARED_DIR"] = str(_TEST_SHARED)

# plan_core-Attribute, die zur Import-Zeit aufgeloest werden
_PLAN_CORE_PATHS = ("PLANS_DIR", "PLANS_INDEX", "ARCHIVE_DIR", "ROADMAPS_DIR")


def isolate_paths() -> dict:
    """Alle Import-Zeit-Pfadkonstanten auf das Test-Root umbiegen."""
    from plan_follow import coord_state, plan_core, plan_suggest, plan_templates

    plan_core.PLANS_DIR = _TEST_PLANS
    plan_core.PLANS_INDEX = _TEST_PLANS / "plans_index.json"
    plan_core.ARCHIVE_DIR = _TEST_PLANS / "archived"
    plan_core.ROADMAPS_DIR = _TEST_ROADMAPS

    plan_templates.TEMPLATES_DIR = _TEST_PLANS / "templates"
    plan_suggest._TRACKING_FILE = _TEST_PLANS / "time_tracking.json"

    coord_state.set_shared_dir(_TEST_SHARED)
    return assert_isolated()


def assert_isolated() -> dict:
    """Fail-fast: kein relevanter Pfad darf unter dem echten ~/.hermes liegen."""
    from plan_follow import coord_state, plan_core, plan_suggest, plan_templates

    paths = {name: getattr(plan_core, name) for name in _PLAN_CORE_PATHS}
    paths["plan_templates.TEMPLATES_DIR"] = plan_templates.TEMPLATES_DIR
    paths["plan_suggest._TRACKING_FILE"] = plan_suggest._TRACKING_FILE
    paths["coord_state.SHARED_DIR"] = coord_state.SHARED_DIR

    leaked = {}
    for name, path in paths.items():
        try:
            resolved = Path(path).resolve()
        except OSError:
            continue
        for root in _PROTECTED_ROOTS:
            if resolved == root or root in resolved.parents:
                leaked[name] = str(resolved)
                break

    if leaked:
        raise RuntimeError(
            "Test-Isolation fehlgeschlagen — diese Pfade zeigen in echte Produktionsdaten: "
            f"{leaked}. Kein Test darf gegen ~/.hermes/plans, roadmaps oder shared laufen."
        )
    return paths


isolate_paths()
atexit.register(lambda: shutil.rmtree(_TEST_ROOT, ignore_errors=True))


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
        except OSError:
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
        except ImportError:
            pass


@pytest.fixture(autouse=True)
def reset_shared_state():
    """Clear shared coord_state + plan_state between tests.

    coord_state stores locks/sessions/notifications in shared JSON files,
    plan_core caches plan state in memory. Without cleanup, tests leak
    state and subsequent tests fail with unexpected lock counts /
    None-banner returns.

    Alle Resets laufen ausschliesslich im Test-Root. Die Isolation wird vor
    jedem Test erneut geprueft (assert_isolated) — zeigt ein Pfad wieder auf
    ~/.hermes, schlaegt der Test hart fehl statt Daten zu loeschen.
    """
    from plan_follow import coord_state, plan_core

    # Isolation vor JEDEM Test neu setzen: einzelne Tests biegen Pfade direkt
    # (nicht per monkeypatch) um und wuerden sie sonst in Folgetests leaken.
    paths = isolate_paths()

    # Reset coord_state
    coord_state._SHARED_DIR_INIT = False
    for f in [coord_state.SESSIONS_FILE, coord_state.LOCKS_FILE,
              coord_state.NOTIFICATIONS_FILE]:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}")

    # Reset plan_core caches
    for attr in ['_tasks_cache', '_active_plan_cache', '_current_task_cache']:
        if hasattr(plan_core, attr):
            val = getattr(plan_core, attr)
            if isinstance(val, dict):
                val.clear()
            else:
                setattr(plan_core, attr, None)

    # Reset plan files — nur im verifizierten Test-Root
    plans_dir = paths["PLANS_DIR"]
    if plans_dir.exists():
        for f in plans_dir.iterdir():
            if f.suffix == ".json":
                f.write_text("{}")
            elif f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "plans_index.json").write_text("{}")

    # Reset plan_hooks caches and state (critical: banner+coord+breaker state)
    import plan_follow.plan_hooks as hooks
    hooks._hook_cache.clear()
    hooks._prev_coord_sig = ""
    hooks._coord_cache.clear()
    hooks._breaker_state.clear()
    hooks._banner_turn_counter = 0
    hooks._last_task_id = None

    # Reset tools.base STATE (active_plan, tool_metrics, drift_warnings)
    from plan_follow.tools import base as tools_base
    tools_base._reset_cache()
    tools_base.reset_tool_metrics()

    # Reset plan_follow tools STATE (session_id, etc.)
    from plan_follow.tools.base import STATE as tools_state
    tools_state.session_id = None
    tools_state.tool_metrics = {}
    tools_state.drift_warnings = []
