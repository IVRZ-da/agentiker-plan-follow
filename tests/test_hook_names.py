"""Hook-Registrierung gegen die Hermes-VALID_HOOKS-Liste absichern.

Regression, die dieser Test verhindert: bis v0.5.31 registrierte das Plugin den
Hook ``session_end`` — in Hermes >= 0.23.1 heisst er ``on_session_end``. Ein
``except Exception`` verschluckte den Fehler, das Plugin lud "erfolgreich" und
der Session-End-Hook lief nie. Sichtbar war nur eine WARNING pro Load.

Der Test prueft beide Richtungen:
  * jeder registrierte Hook ist in VALID_HOOKS enthalten
  * registrierte Hooks == Manifest (plugin.yaml), nicht nur eine Teilmenge
"""
import ast
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PLUGIN_YAML = PLUGIN_DIR / "plugin.yaml"
HERMES_ROOT = Path(__file__).resolve().parents[3] / "hermes-agent"


def _valid_hooks() -> set:
    """VALID_HOOKS aus Hermes importieren — mit AST-Fallback ohne Hermes-Tree."""
    if (HERMES_ROOT / "hermes_cli").is_dir() and str(HERMES_ROOT) not in sys.path:
        sys.path.insert(0, str(HERMES_ROOT))
    try:
        from hermes_cli.plugins import VALID_HOOKS

        return set(VALID_HOOKS)
    except Exception:
        pass

    # AST-Fallback: Literal direkt aus der Quelle lesen
    plugins_py = HERMES_ROOT / "hermes_cli" / "plugins.py"
    if not plugins_py.exists():
        pytest.skip(f"Weder Import noch Quelle von VALID_HOOKS verfuegbar ({plugins_py})")
        raise AssertionError("unreachable")
    tree = ast.parse(plugins_py.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "VALID_HOOKS":
                if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
                    return {
                        elt.value for elt in value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }
                if isinstance(value, ast.Call):  # set({...})
                    for arg in value.args:
                        if isinstance(arg, (ast.Set, ast.List, ast.Tuple)):
                            return {
                                elt.value for elt in arg.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            }
    pytest.skip("VALID_HOOKS im Hermes-Quellcode nicht gefunden")


def _manifest_hooks() -> set:
    data = yaml.safe_load(PLUGIN_YAML.read_text(encoding="utf-8")) or {}
    hooks = data.get("hooks") or []
    return set(hooks)


class _FakeCtx:
    """Minimaler PluginContext-Ersatz, der unbekannte Hooks sofort ablehnt."""

    def __init__(self, valid: set):
        self.valid = valid
        self.registered: dict = {}

    def register_hook(self, name, callback):
        if self.valid and name not in self.valid:
            raise ValueError(f"Hermes kennt keinen Hook '{name}'")
        self.registered[name] = callback


def test_all_registered_hooks_are_valid():
    from plan_follow import HOOK_REGISTRATION_ERRORS, _register_hooks

    valid = _valid_hooks()
    ctx = _FakeCtx(valid)
    _register_hooks(ctx)

    assert not HOOK_REGISTRATION_ERRORS, (
        f"Plugin hat Hooks als ungueltig erkannt: {HOOK_REGISTRATION_ERRORS}"
    )
    unknown = set(ctx.registered) - valid
    assert not unknown, f"Registrierte, aber in Hermes unbekannte Hooks: {unknown}"


def test_registered_hooks_match_manifest():
    """Manifest und Code duerfen nicht auseinanderlaufen (Unterdeklaration)."""
    from plan_follow import _register_hooks

    ctx = _FakeCtx(_valid_hooks())
    _register_hooks(ctx)

    assert set(ctx.registered) == _manifest_hooks(), (
        "plugin.yaml hooks != registrierte Hooks: "
        f"nur im Code: {set(ctx.registered) - _manifest_hooks()}, "
        f"nur im Manifest: {_manifest_hooks() - set(ctx.registered)}"
    )


def test_manifest_hooks_are_subset_of_valid_hooks():
    unknown = _manifest_hooks() - _valid_hooks()
    assert not unknown, f"plugin.yaml deklariert unbekannte Hooks: {unknown}"


def test_unknown_hook_is_reported_not_swallowed(monkeypatch):
    """Ein ungueltiger Hook-Name darf NICHT still verschluckt werden."""
    import plan_follow

    # Nur die drei echten Hooks als "gueltig" vortaeuschen, on_session_end entfernen
    monkeypatch.setattr(
        plan_follow, "_valid_hook_names",
        lambda: {"pre_llm_call", "post_tool_call"},
    )
    ctx = _FakeCtx({"pre_llm_call", "post_tool_call"})
    plan_follow._register_hooks(ctx)

    assert "on_session_end" not in ctx.registered
    assert plan_follow.HOOK_REGISTRATION_ERRORS, "Fehler wurde verschluckt"
    assert "on_session_end" in plan_follow.HOOK_REGISTRATION_ERRORS[0]
