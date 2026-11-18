# Core-Override: `toolsets._HERMES_CORE_TOOLS` (plan_follow)

Stand 2026-11-18. Geprüft mit `hermes plugins validate` (Hermes 0.23.1) und einem
Wirkungstest gegen die echte Hermes-Runtime.

## Was passiert

`__init__.py::_mark_tools_eager()` hängt `EAGER_TOOLS` in `toolsets._HERMES_CORE_TOOLS`
ein. Der Validator meldet das als **`no core override`: rot** — zu Recht: es ist ein
Schreibzugriff auf eine Core-Konstante, kein öffentlicher Hook.

Der Check steht deshalb in `references/core_override_allowlist.txt`. `scripts/validate_gate.py`
lässt genau diesen einen roten Check zu und schlägt fehl, sobald ein anderer Check rot wird
oder der Eintrag veraltet ist.

## Warum es keinen sauberen Weg gibt

`tools/tool_search.py::is_deferrable_tool_name()` (Hermes 0.23.1, Zeilen 150–162):

```python
if name in _core_tool_names():            return False   # core bleibt eager
toolset = _registry_toolset(name)
return toolset is not None and (toolset.startswith("mcp-") or toolset not in _DIRECT_SURFACE_TOOLSETS)
```

- `_DIRECT_SURFACE_TOOLSETS` = `CLIENT_SURFACE_TOOLSETS | TOOLSET_SESSION_PLATFORMS` —
  enthält nur `project`, `desktop_ui`, `catalog` und Session-Plattformen. Ein Plugin-Toolset
  lässt sich dort nicht eintragen.
- Es gibt **keine** Plugin-API `register_tool(..., eager=True)`; `PluginContext.register_tool`
  kennt nur `name/toolset/schema/handler/description`.
- `tools.tool_search.defer` in der config ersetzt die kuratierte Core-Liste **global** —
  als Plugin-Hebel unbrauchbar.

Damit ist der Rebind der einzige Weg zu eager Tools. Die Alternative ist, auf eager zu
verzichten: dann laufen alle 39 Tools über `tool_search`/`tool_describe`, was pro
Plan-Erstellung zwei Extra-Turns kostet (und den häufigsten Fall — `plan_create` — am
stärksten trifft).

## Wirkungsnachweis

1. **Regressionstest:** `tests/test_init.py::TestEagerIntegration::test_tool_becomes_non_deferrable`
   prüft in einem frischen Prozess gegen die echte Hermes-Runtime, dass ein Tool mit dem
   Namen aus `EAGER_TOOLS` **nicht** mehr als deferrable eingestuft wird (vorher: deferrable).
2. **Mengennachweis:** `tests/test_eager_tools.py` hält fest, dass genau drei Namen
   eingetragen werden (idempotent, keine Fremdnamen).
3. **Kostennachweis:** `scripts/tool_schema_audit.py .`

```
plan_follow: 39 Tools, 44.064 Zeichen ≈ 11.016 Tokens (alle eager)
eager laut EAGER_TOOLS: 6.698 Zeichen ≈ 1.674 Tokens pro Turn
```

Vor dem Umbau (2026-11-18): 5 eager Tools, 10.947 Zeichen ≈ 2.737 Tokens.
Ersparnis: 4.249 Zeichen ≈ 1.063 Tokens pro Turn.

## Bekannte Nebenwirkung

Das GUI-Plugin-Panel leitet die Tools eines Plugins als `tools_registered - _HERMES_CORE_TOOLS`
ab. Die drei Hot-Path-Tools zählen dort als „builtin" und erscheinen nicht unter
plan_follow; die übrigen 36 bleiben zuordenbar. Bewusst akzeptiert.

## Fail-open

Fehlt das Modul `toolsets` oder ist `_HERMES_CORE_TOOLS` nicht schreibbar, loggt das Plugin
eine Warnung und bleibt beim Deferral — kein Crash, kein Startabbruch
(`tests/test_eager_tools.py::test_marking_fails_open_without_toolsets`).

## Wenn Hermes eine Plugin-API nachrüstet

Sobald `ctx.register_tool(..., eager=True)` (oder ein Manifest-Feld) existiert:

1. `_mark_tools_eager()` löschen, `EAGER_TOOLS` als `eager: true` je Tool deklarieren,
2. Eintrag aus `core_override_allowlist.txt` entfernen (das Gate schlägt sonst als
   „stale" fehl — genau dafür ist die Stale-Prüfung da),
3. `provides_tools`-Generator und Tests laufen lassen.
