#!/usr/bin/env python3
"""Generiert provides_tools / provides_hooks in plugin.yaml aus der echten Registrierung.

Warum
-----
Handgepflegte Capability-Listen driften: `hermes plugins validate` meldet jede
registrierte Faehigkeit, die im Manifest fehlt, als Fehler ("undeclared tools").
Dieses Skript liest die Wahrheit aus `register(ctx)` und schreibt sie ins
Manifest - idempotent und ohne PyYAML-Dump (der die Formatierung zerstoeren
wuerde).

Aufruf
------
    cd ~/.hermes/plugins/plan_follow
    python3 scripts/gen_manifest_capabilities.py           # schreiben
    python3 scripts/gen_manifest_capabilities.py --check    # nur pruefen (Exit 1 bei Drift)
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
MANIFEST = PLUGIN_DIR / "plugin.yaml"
MANAGED_KEYS = ("manifest_version", "provides_tools", "provides_hooks")


class _StubContext:
    """Minimaler PluginContext-Ersatz: sammelt nur, was register() anmeldet."""

    def __init__(self) -> None:
        self.tools: list[str] = []
        self.hooks: list[str] = []

    # Hermes-Signatur: register_tool(name, toolset, schema, handler, description=...)
    def register_tool(self, name, toolset=None, schema=None, handler=None, **kwargs):  # noqa: ANN001
        if name not in self.tools:
            self.tools.append(name)
        return None

    def register_hook(self, hook_name, callback=None, **kwargs):  # noqa: ANN001
        if hook_name not in self.hooks:
            self.hooks.append(hook_name)
        return None

    # Alles andere (Middleware, Provider, ...) interessiert hier nicht.
    def __getattr__(self, item):  # noqa: ANN001
        def _noop(*args, **kwargs):
            return None

        return _noop


def load_plugin():
    """Importiert das Plugin-Paket unabhaengig vom Hermes-Plugin-Manager."""
    if str(PLUGIN_DIR.parent) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR.parent))
    if "plan_follow" in sys.modules:
        return sys.modules["plan_follow"]
    spec = importlib.util.spec_from_file_location(
        "plan_follow", PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("plan_follow-Paket konnte nicht geladen werden")
    module = importlib.util.module_from_spec(spec)
    sys.modules["plan_follow"] = module
    spec.loader.exec_module(module)
    return module


def collect() -> tuple[list[str], list[str]]:
    """Liefert (tool_names, hook_names) aus der echten register()-Registrierung."""
    plugin = load_plugin()
    ctx = _StubContext()
    plugin.register(ctx)
    return sorted(ctx.tools), sorted(ctx.hooks)


def _drop_key_block(lines: list[str], key: str) -> list[str]:
    """Entfernt `key:` inklusive Folgezeilen, die tiefer eingerueckt sind."""
    out: list[str] = []
    skip_indent: int | None = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if skip_indent is not None:
            if stripped == "" or indent > skip_indent:
                continue
            skip_indent = None
        if re.match(rf"^{re.escape(key)}\s*:", line):
            skip_indent = indent
            continue
        out.append(line)
    return out


def render_manifest(tools: list[str], hooks: list[str], manifest_version: int = 2) -> str:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    for key in MANAGED_KEYS:
        lines = _drop_key_block(lines, key)
    while lines and lines[-1].strip() == "":
        lines.pop()

    block = ["", f"manifest_version: {manifest_version}", "provides_tools:"]
    block += [f"  - {name}" for name in tools]
    block.append("provides_hooks:")
    block += [f"  - {name}" for name in hooks]
    return "\n".join(lines + block) + "\n"


def main(argv: list[str]) -> int:
    tools, hooks = collect()
    wanted = render_manifest(tools, hooks)
    current = MANIFEST.read_text(encoding="utf-8")

    if "--check" in argv:
        if current == wanted:
            print(f"OK: Manifest aktuell ({len(tools)} Tools, {len(hooks)} Hooks)")
            return 0
        print("DRIFT: plugin.yaml passt nicht zur Registrierung.", file=sys.stderr)
        print(f"      registriert: {len(tools)} Tools, {len(hooks)} Hooks", file=sys.stderr)
        print("      -> python3 scripts/gen_manifest_capabilities.py", file=sys.stderr)
        return 1

    MANIFEST.write_text(wanted, encoding="utf-8")
    print(f"geschrieben: {len(tools)} Tools, {len(hooks)} Hooks -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
