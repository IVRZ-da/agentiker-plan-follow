"""plan_create-Schema: Budget und Funktionsfaehigkeit nach der Kuerzung (T2).

Das Schema war 6.713 Zeichen (61 % der Eager-Kosten). Gekuerzt wurde an der
Dokumentation — nicht an der Toleranz: der Code akzeptiert weiter Listen, Dicts,
JSON-Strings und Tasks ohne id (normalize_tasks()). Diese Tests halten beides fest:
das Budget UND dass die Eingaben weiter funktionieren.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS  # noqa: E402
from plan_follow.tools.schemas import PER_TOOL_SCHEMAS  # noqa: E402

BUDGET_CHARS = 3000


def _payload_chars() -> int:
    return len(
        json.dumps(
            {"schema": PER_TOOL_SCHEMAS["plan_create"], "description": TOOL_DESCRIPTIONS["plan_create"]},
            ensure_ascii=False,
        )
    )


def test_schema_stays_under_budget():
    chars = _payload_chars()
    assert chars < BUDGET_CHARS, f"plan_create ist {chars} Zeichen (Budget {BUDGET_CHARS})"


def test_task_fields_are_documented_in_description():
    """Ohne items-Schema muessen die Feldnamen in der Beschreibung stehen."""
    desc = PER_TOOL_SCHEMAS["plan_create"]["properties"]["tasks"]["description"]
    for field in ("id", "name", "files", "verify", "review_profile", "depends_on"):
        assert field in desc, f"{field} fehlt in der tasks-Beschreibung"


def test_review_profiles_stay_valid():
    """Das Enum ist aus dem Schema raus — die Werte muessen in der Beschreibung stehen."""
    desc = PER_TOOL_SCHEMAS["plan_create"]["properties"]["tasks"]["description"]
    assert "unit-test" in desc and "api-route" in desc and "ui-component" in desc


def test_goal_is_required():
    schema = PER_TOOL_SCHEMAS["plan_create"]
    assert schema["required"] == ["goal"]


def test_happy_path_task_list():
    from plan_follow.plan_tools import plan_create_tool

    result = plan_create_tool(
        {
            "goal": "Schema-Budget Smoke-Test",
            "tasks": [
                {
                    "id": "T1",
                    "name": "Erster Task",
                    # echter Check, der fehlschlagen kann — 'false' blockt der Auto-Review
                    "verify": "test -f /home/jo/.hermes/plugins/plan_follow/__init__.py",
                },
                {"id": "T2", "name": "Zweiter Task", "depends_on": ["T1"]},
            ],
        }
    )
    assert isinstance(result, str) and result.strip()
    assert "error" not in result.lower()


def test_happy_path_without_id_is_normalised():
    """id wird vergeben, 'title' wird als 'name' akzeptiert — laut Beschreibung."""
    from plan_follow import plan_core
    from plan_follow.plan_tools import plan_create_tool

    plan_create_tool(
        {"goal": "Normalisierung", "tasks": [{"title": "Ohne id und name-Feld"}]}
    )
    index = json.loads(plan_core.PLANS_INDEX.read_text())
    plan_id = index["active_plan_id"]
    plan = json.loads((plan_core.PLANS_DIR / f"{plan_id}.json").read_text())
    tasks = plan["tasks"]
    items = list(tasks.values()) if isinstance(tasks, dict) else tasks
    assert any(t.get("name") == "Ohne id und name-Feld" for t in items)


def test_missing_goal_reports_error():
    from plan_follow.plan_tools import plan_create_tool

    result = plan_create_tool({"tasks": [{"id": "T1", "name": "x"}]})
    assert "goal" in str(result).lower()
