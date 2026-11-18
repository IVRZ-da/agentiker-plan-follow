"""Eager-Set von plan_follow (T3): nur der Hot-Path liegt im Tool-Prompt.

Jedes eager Tool kostet sein volles Schema pro Turn; alles andere ist deferred und
kostet nur einen Katalognamen. Der Loop ist create -> current -> complete, deshalb
genau diese drei. plan_update/plan_status kommen ueber die Bridge (tool_call).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import plan_follow  # noqa: E402

EXPECTED = ("plan_create", "plan_current", "plan_complete")


def test_eager_set_is_the_hot_path():
    assert tuple(plan_follow.EAGER_TOOLS) == EXPECTED


def test_eager_set_stays_small(monkeypatch):
    """Eager-Markierung traegt genau diese Namen ein — nicht mehr."""
    core: list[str] = []

    class FakeToolsets:
        _HERMES_CORE_TOOLS = core

    monkeypatch.setitem(sys.modules, "toolsets", FakeToolsets)
    plan_follow._mark_tools_eager()
    assert [n for n in core if n.startswith("plan_")] == list(EXPECTED)


def test_eager_marking_is_idempotent(monkeypatch):
    core: list[str] = []

    class FakeToolsets:
        _HERMES_CORE_TOOLS = core

    monkeypatch.setitem(sys.modules, "toolsets", FakeToolsets)
    plan_follow._mark_tools_eager()
    plan_follow._mark_tools_eager()
    assert core.count("plan_create") == 1
    assert len(core) == len(EXPECTED)


def test_marking_fails_open_without_toolsets(monkeypatch):
    """Fehlt ``toolsets`` (andere Hermes-Version), darf der Load nicht brechen."""
    monkeypatch.setitem(sys.modules, "toolsets", None)
    plan_follow._mark_tools_eager()  # keine Exception


def test_every_eager_tool_is_registered():
    """Ein Name in EAGER_TOOLS ohne Registrierung waere ein toter Eintrag."""
    names = {name for name, _handler in plan_follow.PLAN_TOOLS}
    assert set(EXPECTED) <= names
