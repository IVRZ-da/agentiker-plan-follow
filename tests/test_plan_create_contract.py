"""Contract-Tests fuer plan_create — die 5 Fehlersignaturen aus der Analyse 2026-11-11.

Diese Tests sind absichtlich RED, bis P2/P3/P6/P7 des Plans
`2026-11-11-plan-follow-default-eager` umgesetzt sind. Sie beschreiben das
SOLL-Verhalten der Tool-Oberflaeche, nicht die aktuelle Implementierung:

1. Fehlt template UND tasks, nennt der Fehler beide Optionen + ein Beispiel.
2. Ein blockierter Plan liefert status=error (keine Success-Box mit error-Key)
   und hinterlaesst KEINE Plan-Datei auf der Platte.
3. tasks werden normalisiert: dict->list, title->name, fehlende id->auto.
4. tasks duerfen als JSON-String ankommen.
5. Die Response enthaelt hoechstens 3 Peer-Review-Findings + eine Zusammenfassung.

Kein xfail: die Tests muessen nach der Umsetzung gruen sein.
"""

from __future__ import annotations

import json

import plan_follow.plan_core as plan_core
import plan_follow.tools.task as task_mod
import pytest
from plan_follow.plan_tools import plan_create_tool


def _parse(output: str) -> dict:
    """Tool-Output als dict. conftest::patch_fmt macht alle fmt_*-Aufrufe zu JSON."""
    text = output.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    raise AssertionError(f"Tool-Output ist kein JSON: {output[:400]}")


@pytest.fixture
def temp_plans(monkeypatch, tmp_path):
    """Eigenes Plans-Verzeichnis pro Test (zusaetzlich zur conftest-Isolation)."""
    test_plans = tmp_path / "plans_contract"
    test_plans.mkdir()
    monkeypatch.setattr(plan_core, "PLANS_DIR", test_plans)
    monkeypatch.setattr(plan_core, "PLANS_INDEX", test_plans / "plans_index.json")
    monkeypatch.setattr(plan_core, "ARCHIVE_DIR", test_plans / "archived")
    plan_core._reset_cache()
    yield test_plans


SIMPLE_TASKS = [
    {"id": "T1", "name": "Erster Schritt", "files": ["a.txt"], "verify": "test -f a.txt"},
]


# ─── Contract 1: Fehlertext nennt beide Optionen + Beispiel ──────────────────
class TestErrorContract:
    def test_error_contract_missing_template_and_tasks(self, temp_plans):
        result = _parse(plan_create_tool({"goal": "Nur ein Ziel, keine Tasks"}))

        assert result.get("status") == "error", (
            "Fehlender Task-Input muss status=error liefern, nicht "
            f"'{result.get('status')}'"
        )
        msg = result.get("error", "")
        assert "template" in msg.lower(), "Fehlertext muss die template-Option nennen"
        assert "tasks" in msg.lower(), "Fehlertext muss die tasks-Option nennen"
        # Kopierfertiges Beispiel: ohne das raet das Modell erneut.
        assert "{" in msg or "id" in msg, (
            f"Fehlertext braucht ein Minimal-Beispiel fuer tasks: {msg!r}"
        )
        # Die alte, irrefuehrende Formulierung darf nicht zurueckkehren.
        assert "kein Template = kein Plan" not in msg

    def test_error_contract_blocked_plan_leaves_no_file(self, temp_plans, monkeypatch):
        def _always_critical(_plan):
            return [{
                "id": "F1", "severity": "critical", "check": "verify",
                "description": "künstlich nicht fixbar", "task_id": "T1",
            }]

        monkeypatch.setattr(task_mod.plan_peer_review, "run_peer_review", _always_critical)
        monkeypatch.setattr(
            task_mod.plan_peer_review, "apply_findings", lambda plan, findings: plan
        )

        plan_id = "contract-blocked-plan"
        result = _parse(plan_create_tool({
            "goal": "Blockierter Plan", "plan_id": plan_id, "tasks": SIMPLE_TASKS,
        }))

        assert result.get("status") == "error", (
            "Ein blockierter Plan muss status=error liefern — keine Success-Box "
            f"mit error-Key (aktuell: {result.get('status')})"
        )
        assert not (temp_plans / f"{plan_id}.json").exists(), (
            "Ein blockierter Plan darf keine Plan-Datei auf der Platte hinterlassen"
        )


# ─── Contract 3+4: Eingabe-Normalisierung ────────────────────────────────────
class TestNormalizeTasks:
    def test_normalize_tasks_dict_to_list(self, temp_plans):
        result = _parse(plan_create_tool({
            "goal": "Dict statt Liste",
            "plan_id": "contract-normalize-dict",
            "tasks": {"T1": {"name": "Erster Schritt", "verify": "test -f a.txt"}},
        }))
        assert result.get("status") in ("created", "warning"), (
            f"Dict-Tasks muessen normalisiert werden: {result}"
        )
        plan = plan_core._load_plan("contract-normalize-dict")
        assert plan and "T1" in plan["tasks"]

    def test_normalize_tasks_title_to_name(self, temp_plans):
        result = _parse(plan_create_tool({
            "goal": "title statt name",
            "plan_id": "contract-normalize-title",
            "tasks": [{"id": "T1", "title": "Erster Schritt", "verify": "test -f a.txt"}],
        }))
        assert result.get("status") in ("created", "warning"), (
            f"'title' muss als 'name' akzeptiert werden: {result}"
        )
        plan = plan_core._load_plan("contract-normalize-title")
        assert plan["tasks"]["T1"]["name"] == "Erster Schritt"

    def test_normalize_tasks_missing_id(self, temp_plans):
        result = _parse(plan_create_tool({
            "goal": "id fehlt",
            "plan_id": "contract-normalize-id",
            "tasks": [{"name": "Erster Schritt", "verify": "test -f a.txt"}],
        }))
        assert result.get("status") in ("created", "warning"), (
            f"Fehlende id muss automatisch vergeben werden: {result}"
        )
        plan = plan_core._load_plan("contract-normalize-id")
        assert len(plan["tasks"]) == 1

    def test_normalize_tasks_json_string(self, temp_plans):
        result = _parse(plan_create_tool({
            "goal": "tasks als JSON-String",
            "plan_id": "contract-normalize-json",
            "tasks": json.dumps(SIMPLE_TASKS),
        }))
        assert result.get("status") in ("created", "warning"), (
            f"tasks als JSON-String muss geparst werden: {result}"
        )
        plan = plan_core._load_plan("contract-normalize-json")
        assert "T1" in plan["tasks"]


# ─── Contract 5: kompakte Response ───────────────────────────────────────────
class TestCompactResponse:
    def test_compact_peer_review_response(self, temp_plans, monkeypatch):
        findings = [
            {"id": f"F{i}", "severity": "important", "check": "files",
             "description": f"Finding {i}", "task_id": "T1"}
            for i in range(1, 7)
        ]
        monkeypatch.setattr(
            task_mod.plan_peer_review, "run_peer_review", lambda plan: list(findings)
        )
        monkeypatch.setattr(
            task_mod.plan_peer_review, "apply_findings", lambda plan, f: plan
        )

        result = _parse(plan_create_tool({
            "goal": "Viele Findings", "plan_id": "contract-compact", "tasks": SIMPLE_TASKS,
        }))

        shown = result.get("peer_review") or []
        assert len(shown) <= 3, (
            f"Response darf hoechstens 3 Findings zeigen, waren {len(shown)}"
        )
        assert "peer_review_summary" in result, (
            "Gekuerzte Findings brauchen eine Zusammenfassung (z.B. '6 important, 0 critical')"
        )


# ─── Contract 6: die Tool-Beschreibung sagt die Wahrheit ─────────────────────
class TestTruthfulDescription:
    def test_description_no_template_required(self):
        from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS

        desc = TOOL_DESCRIPTIONS["plan_create"]
        assert "TEMPLATE IS REQUIRED" not in desc, (
            "Die Beschreibung behauptet weiterhin, ein Template sei Pflicht"
        )
        assert "free" in desc, "Das free-Template fehlt in der Template-Liste"
        assert "tasks" in desc, "Die tasks-Alternative fehlt in der Beschreibung"


# ─── Review-Findings 2026-11-11 (Randfaelle der Normalisierung) ──────────────
class TestNormalizeTasksEdgeCases:
    def test_normalize_tasks_single_dict(self, temp_plans):
        """Ein einzelner Task-Dict darf nicht zu Phantom-Tasks werden."""
        result = _parse(plan_create_tool({
            "goal": "Einzel-Task",
            "plan_id": "contract-normalize-single",
            "tasks": {"id": "T1", "name": "Erster Schritt", "verify": "test -f a.txt"},
        }))
        assert result.get("status") in ("created", "warning"), result
        plan = plan_core._load_plan("contract-normalize-single")
        assert list(plan["tasks"]) == ["T1"], f"Phantom-Tasks entstanden: {list(plan['tasks'])}"

    def test_normalize_tasks_numeric_id_stringified(self, temp_plans):
        """Numerische id muss als String gespeichert werden, sonst ist der Task
        nach dem Reload nicht mehr auflösbar (current_task -> None)."""
        result = _parse(plan_create_tool({
            "goal": "Numerische id",
            "plan_id": "contract-normalize-numeric",
            "tasks": [{"id": 7, "name": "Erster Schritt", "verify": "test -f a.txt"}],
        }))
        assert result.get("status") in ("created", "warning"), result
        plan = plan_core._load_plan("contract-normalize-numeric")
        assert "7" in plan["tasks"]
        assert isinstance(plan["current_task"], str), \
            f"current_task ist {type(plan['current_task']).__name__}, nicht str"
        assert plan["tasks"].get(plan["current_task"]) is not None

    def test_normalize_tasks_duplicate_ids(self, temp_plans):
        """Doppelte IDs dürfen sich nicht still gegenseitig überschreiben."""
        result = _parse(plan_create_tool({
            "goal": "Doppelte ids",
            "plan_id": "contract-normalize-dupes",
            "tasks": [
                {"id": "T1", "name": "A", "verify": "test -f a.txt"},
                {"id": "T1", "name": "B", "verify": "test -f b.txt"},
            ],
        }))
        assert result.get("status") in ("created", "warning"), result
        plan = plan_core._load_plan("contract-normalize-dupes")
        assert len(plan["tasks"]) == 2, f"Task ging verloren: {list(plan['tasks'])}"
        assert len(set(plan["tasks"])) == 2

    def test_normalize_tasks_broken_json(self, temp_plans):
        """Kaputtes JSON muss als solches gemeldet werden, nicht als 'keine Tasks'."""
        result = _parse(plan_create_tool({
            "goal": "Kaputtes JSON",
            "plan_id": "contract-normalize-broken",
            "tasks": '[{"id": "T1", "name": ',
        }))
        assert result.get("status") == "error"
        assert "JSON" in result.get("error", ""), result

    def test_normalize_tasks_notes_truncation(self, temp_plans):
        """Mehr als 5 Korrekturen müssen sichtbar gekappt werden."""
        tasks = [{"name": f"Schritt {i}", "verify": "test -f a.txt"} for i in range(1, 9)]
        result = _parse(plan_create_tool({
            "goal": "Viele Korrekturen",
            "plan_id": "contract-normalize-many",
            "tasks": tasks,
        }))
        assert result.get("status") in ("created", "warning"), result
        notes = result.get("normalized") or []
        assert notes, "Korrekturen müssen ausgewiesen werden"
        assert any("weitere Korrekturen" in n for n in notes), \
            f"Kappung ist nicht sichtbar: {notes}"


# ─── Unit-Tests fuer normalize_tasks (Fehlerpfade + Template-Zweig) ──────────
class TestNormalizeTasksUnit:
    """Direkte Tests der Normalisierung — decken die Zweige ab, die kein
    Tool-Aufruf erreicht (kaputte Strukturen, Platzhalter, params.tasks)."""

    def test_dict_with_tasks_key_is_unpacked(self):
        from plan_follow.tools.task import normalize_tasks

        tasks, notes = normalize_tasks({"tasks": [{"id": "T1", "name": "A"}]})
        assert [t["id"] for t in tasks] == ["T1"]
        assert any("entpackt" in n for n in notes)

    def test_task_map_with_string_values(self):
        from plan_follow.tools.task import normalize_tasks

        tasks, _ = normalize_tasks({"T1": "Erster Schritt", "T2": "Zweiter Schritt"})
        assert [t["id"] for t in tasks] == ["T1", "T2"]
        assert tasks[0]["name"] == "Erster Schritt"

    def test_nested_tasks_dict(self):
        """{"tasks": {id: {...}}} muss aufgeloest werden (nicht als Task-Namen)."""
        from plan_follow.tools.task import normalize_tasks

        tasks, notes = normalize_tasks({"tasks": {"T1": {"name": "A"}}})
        assert [t["id"] for t in tasks] == ["T1"]
        assert tasks[0]["name"] == "A"
        assert any("key=id" in n for n in notes)

    def test_invalid_type_returns_note(self):
        from plan_follow.tools.task import normalize_tasks

        tasks, notes = normalize_tasks(42)
        assert tasks == []
        assert any("ungueltigen Typ" in n for n in notes)

    def test_list_of_strings(self):
        from plan_follow.tools.task import normalize_tasks

        tasks, _ = normalize_tasks(["Erster Schritt"])
        assert len(tasks) == 1
        assert tasks[0]["name"] == "Erster Schritt"
        assert tasks[0]["id"] == "1"

    def test_non_dict_item_is_skipped(self):
        from plan_follow.tools.task import normalize_tasks

        tasks, notes = normalize_tasks([{"id": "T1", "name": "A"}, 42])
        assert len(tasks) == 1
        assert any("uebersprungen" in n for n in notes)

    def test_placeholder_name_when_nothing_given(self):
        from plan_follow.tools.task import normalize_tasks

        tasks, notes = normalize_tasks([{"id": "T1"}])
        assert tasks[0]["name"] == "Task T1"
        assert any("Platzhalter" in n for n in notes)

    def test_empty_input(self):
        from plan_follow.tools.task import normalize_tasks

        for raw in (None, "", [], {}):
            tasks, notes = normalize_tasks(raw)
            assert tasks == []
            assert notes == []

    def test_template_free_with_broken_params_tasks(self, temp_plans):
        """Kaputtes params.tasks muss als solches gemeldet werden (nicht als
        'multi-Template erfordert params.tasks')."""
        result = _parse(plan_create_tool({
            "goal": "Kaputte params.tasks",
            "plan_id": "contract-free-broken",
            "template": "free",
            "params": {"tasks": '[{"id": "T1",'},
        }))
        assert result.get("status") == "error"
        assert "params.tasks" in result.get("error", ""), result

    def test_template_free_with_dict_tasks(self, temp_plans):
        """params.tasks als Dict {id: {...}} muss ebenfalls normalisiert werden."""
        result = _parse(plan_create_tool({
            "goal": "Free mit Dict-Tasks",
            "plan_id": "contract-free-dict",
            "template": "free",
            "params": {"tasks": {"T1": {"name": "A", "verify": "test -f a.txt"}}},
        }))
        assert result.get("status") in ("created", "warning"), result
        plan = plan_core._load_plan("contract-free-dict")
        assert "T1" in plan["tasks"]


# ─── Review-Findings 2026-11-11 (P6): Fail-open + Fix-Persistenz ─────────────
class TestReviewFailOpenAndPersistence:
    def test_fail_open_when_review_raises(self, temp_plans, monkeypatch):
        """Wirft der Review, wird der Plan trotzdem erstellt (nur Log-Warnung)."""
        def _boom(_plan):
            raise RuntimeError("review exploded")

        monkeypatch.setattr(task_mod.plan_peer_review, "run_peer_review", _boom)

        plan_id = "contract-fail-open"
        result = _parse(plan_create_tool({
            "goal": "Review wirft", "plan_id": plan_id, "tasks": SIMPLE_TASKS,
        }))
        assert result.get("status") == "created", result
        assert (temp_plans / f"{plan_id}.json").exists(), "Plan muss trotzdem existieren"

    def test_auto_fix_is_persisted(self, temp_plans, tmp_path):
        """Ein Auto-Fix (verify aus Projekt-Marker) landet in der Plan-Datei."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        plan_id = "contract-autofix-persist"
        result = _parse(plan_create_tool({
            "goal": "Autofix persistiert",
            "plan_id": plan_id,
            "repo": str(tmp_path),
            "tasks": [{"id": "T1", "name": "Code aendern", "files": ["src/x.py"]}],
        }))
        assert result.get("status") in ("created", "warning"), result

        plan = plan_core._load_plan(plan_id)
        assert plan["tasks"]["T1"]["verify"] == "python3 -m pytest", \
            f"Auto-Fix wurde nicht persistiert: {plan['tasks']['T1']}"


# ─── Abschluss-Review 2026-11-11: Bridge-Schema + Persistenz + Templates ─────
class TestBridgeSchemaTolerance:
    """Das Schema darf nicht strenger sein als normalize_tasks (Bridge-Weg)."""

    def test_schema_accepts_tolerant_shapes(self):
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS

        tasks_schema = PER_TOOL_SCHEMAS["plan_create"]["properties"]["tasks"]
        assert "object" in tasks_schema["type"], "Dict-Input muss im Schema erlaubt sein"
        assert "string" in tasks_schema["type"], "JSON-String muss erlaubt sein"
        items = tasks_schema["items"]
        assert "required" not in items, "required [id,name] widerspricht der Normalisierung"
        assert "title" in items["properties"], "title muss als Alias deklariert sein"


class TestKindPersistence:
    def test_review_kind_survives_reload(self, temp_plans):
        """kind: review muss auf der Platte landen, sonst greift die Ausnahme nach Reload nicht."""
        plan_id = "contract-kind-persist"
        result = _parse(plan_create_tool({
            "goal": "Review-Task behaelt kind",
            "plan_id": plan_id,
            "tasks": [
                {"id": "T1", "name": "Code aendern", "files": ["a.py"], "verify": "pytest a.py"},
                {"id": "T2", "name": "Durchsicht", "kind": "review", "verify": ""},
            ],
        }))
        assert result.get("status") in ("created", "warning"), result

        plan = plan_core._load_plan(plan_id)
        assert plan["tasks"]["T2"].get("kind") == "review"
        assert task_mod.plan_peer_review.is_review_task(plan["tasks"]["T2"]) is True


class TestDependsOnNormalization:
    def test_numeric_depends_on_is_stringified(self, temp_plans):
        """int-Abhaengigkeiten duerfen nicht still verschwinden."""
        tasks, notes = task_mod.normalize_tasks([
            {"id": 1, "name": "A"},
            {"id": 2, "name": "B", "depends_on": [1]},
        ])
        assert tasks[1]["depends_on"] == ["1"], tasks[1]
        assert any("depends_on" in n for n in notes), notes


class TestEmptyTemplateGuard:
    def test_free_without_tasks_is_rejected(self, temp_plans):
        """free ohne tasks darf keinen Nur-p0-Plan als Erfolg liefern."""
        result = _parse(plan_create_tool({"goal": "leer", "template": "free"}))
        assert result.get("status") == "error", result
        assert "Leerer Plan" in str(result) or "echte Tasks" in str(result)


class TestTemplateWithoutRepo:
    def test_code_template_without_repo_still_creates(self, temp_plans, tmp_path):
        """deploy ohne repo: echo-Platzhalter sind weg -> Plan entsteht (Hinweis statt Blocker)."""
        result = _parse(plan_create_tool({
            "goal": "Deploy vorbereiten", "template": "deploy", "repo": str(tmp_path),
        }))
        assert result.get("status") in ("created", "warning"), result
