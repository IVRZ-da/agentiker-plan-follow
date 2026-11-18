"""Schema-Publishing-Gate (T4).

Der code_intel-Umbau hat den teuersten Fehler dieser Art aufgedeckt: 27 LSP-Tools
wurden mit leerem ``{"properties": {}}`` publiziert, weil ``schema["parameters"]``
statt des Voll-Schemas an die Registry ging. Sie kosteten Tokens in jedem Request und
waren trotzdem nur ueber ``tool_search`` erreichbar — monatelang unbemerkt.

Diese Tests halten fest:
1. jedes registrierte Tool bringt ein echtes ``parameters``-Objekt mit,
2. keine im Schema definierte Property geht bei der Registrierung verloren,
3. keine Beschreibung ist leer,
4. die eager-Summe bleibt unter Budget (unabhaengig von ``tool_schema_audit.py``).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plan_follow  # noqa: E402
from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS  # noqa: E402
from plan_follow.tools.schemas import PER_TOOL_SCHEMAS  # noqa: E402

EAGER_BUDGET_CHARS = 9000
CHARS_PER_TOKEN = 4.0


class RecordingContext:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset=None, schema=None, handler=None, description=None, **kw):
        self.tools[name] = {"schema": schema, "description": description, "toolset": toolset}

    def __getattr__(self, item):
        def _noop(*args, **kwargs):
            return None

        return _noop


def _registered():
    ctx = RecordingContext()
    plan_follow._register_tools(ctx)
    return ctx.tools


def test_all_tools_are_registered():
    assert len(_registered()) == len(plan_follow.PLAN_TOOLS)


def test_every_tool_publishes_parameters():
    for name, entry in _registered().items():
        params = entry["schema"].get("parameters")
        assert isinstance(params, dict), f"{name}: parameters fehlt oder ist kein Objekt"
        assert params.get("type", "object") == "object", f"{name}: parameters.type != object"
        assert isinstance(params.get("properties", {}), dict), f"{name}: properties kaputt"


def test_no_property_is_lost_at_registration():
    """Was im Schema definiert ist, muss beim Tool ankommen."""
    for name, entry in _registered().items():
        declared = set(PER_TOOL_SCHEMAS.get(name, {}).get("properties", {}))
        published = set(entry["schema"]["parameters"].get("properties", {}))
        assert declared == published, f"{name}: verlorene Properties {declared - published}"


def test_required_stays_required():
    for name, entry in _registered().items():
        declared = PER_TOOL_SCHEMAS.get(name, {})
        if "required" in declared:
            assert entry["schema"]["parameters"].get("required") == declared["required"]


def test_no_tool_without_description():
    for name, entry in _registered().items():
        assert entry["description"] and entry["description"].strip(), f"{name}: leere Beschreibung"
        assert name in TOOL_DESCRIPTIONS, f"{name}: fehlt in TOOL_DESCRIPTIONS"


def test_eager_budget_is_kept():
    """Die eager Tools sind das, was pro Turn im Prompt steht."""
    entries = _registered()
    eager_chars = 0
    for name in plan_follow.EAGER_TOOLS:
        entry = entries[name]
        eager_chars += len(
            json.dumps(
                {"schema": entry["schema"], "description": entry["description"]},
                ensure_ascii=False,
            )
        )
    assert eager_chars < EAGER_BUDGET_CHARS, (
        f"eager-Summe {eager_chars} Zeichen ≈ {eager_chars / CHARS_PER_TOKEN:.0f} Tokens "
        f"ueber Budget {EAGER_BUDGET_CHARS}"
    )
