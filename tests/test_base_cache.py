"""Cache-Freshness in ``tools/base.py``.

``_get_active_plan()`` darf keinen Stand behaupten, der auf der Platte nicht mehr gilt:
die Signatur (mtime_ns, size, sha256) verbindet Prozess-Cache und Datei. Diese Tests
decken die Zweige ab, die vorher ungetestet waren — ohne Anker, mit verschwundener Datei
und mit geaenderter Datei.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def base_mod():
    from plan_follow.tools import base

    base.STATE.active_plan = None
    base.STATE.active_plan_id = ""
    base.STATE.active_plan_sig = None
    yield base
    base.STATE.active_plan = None
    base.STATE.active_plan_id = ""
    base.STATE.active_plan_sig = None


def _write_plan(base_mod, plan_id: str, goal: str) -> dict:
    data = {"plan_id": plan_id, "goal": goal, "tasks": []}
    path = base_mod._plan_path(plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


class TestCacheOhneSignatur:
    def test_ohne_pid_gibt_den_cache(self, base_mod):
        plan = {"goal": "ohne plan_id im dict"}
        base_mod.STATE.active_plan = plan
        base_mod.STATE.active_plan_id = ""
        assert base_mod._get_active_plan() is plan

    def test_datei_fehlt_leert_cache_und_gibt_none(self, base_mod):
        base_mod.STATE.active_plan = {"plan_id": "p-weg", "goal": "x"}
        base_mod.STATE.active_plan_id = "p-weg"
        base_mod.STATE.active_plan_sig = None

        assert base_mod._get_active_plan() is None
        assert base_mod.STATE.active_plan is None

    def test_platte_neuer_als_cache_wird_geladen(self, base_mod):
        base_mod.STATE.active_plan = {"plan_id": "p1", "goal": "alt"}
        base_mod.STATE.active_plan_id = "p1"
        base_mod.STATE.active_plan_sig = None
        disk = _write_plan(base_mod, "p1", "neu")

        geladen = base_mod._get_active_plan()

        assert geladen == disk
        assert base_mod.STATE.active_plan_sig is not None

    def test_gleicher_stand_bleibt_im_cache(self, base_mod):
        disk = _write_plan(base_mod, "p1", "gleich")
        base_mod.STATE.active_plan = disk
        base_mod.STATE.active_plan_id = "p1"
        base_mod.STATE.active_plan_sig = None

        geladen = base_mod._get_active_plan()

        assert geladen == disk  # Inhalt gleich: kein Neuladen, Cache-Objekt bleibt


class TestCacheMitSignatur:
    def test_unveraenderte_signatur_gibt_cache_ohne_reload(self, base_mod, monkeypatch):
        disk = _write_plan(base_mod, "p1", "stabil")
        cache_obj = dict(disk)
        base_mod.STATE.active_plan = cache_obj
        base_mod.STATE.active_plan_id = "p1"
        base_mod.STATE.active_plan_sig = base_mod._plan_disk_signature("p1")

        gerufen = []
        monkeypatch.setattr(base_mod, "_load_plan", lambda pid: gerufen.append(pid) or None)

        assert base_mod._get_active_plan() is cache_obj
        assert gerufen == []  # kein Dateizugriff bei gleicher Signatur

    def test_verschwundene_datei_leert_cache(self, base_mod):
        _write_plan(base_mod, "p1", "weg gleich")
        sig = base_mod._plan_disk_signature("p1")
        base_mod.STATE.active_plan = {"plan_id": "p1"}
        base_mod.STATE.active_plan_id = "p1"
        base_mod.STATE.active_plan_sig = sig
        base_mod._plan_path("p1").unlink()

        assert base_mod._get_active_plan() is None
        assert base_mod.STATE.active_plan is None

    def test_geaenderte_datei_wird_neu_geladen(self, base_mod):
        _write_plan(base_mod, "p1", "alt")
        sig = base_mod._plan_disk_signature("p1")
        base_mod.STATE.active_plan = {"plan_id": "p1", "goal": "alt", "tasks": []}
        base_mod.STATE.active_plan_id = "p1"
        base_mod.STATE.active_plan_sig = sig

        neu = _write_plan(base_mod, "p1", "neu")
        geladen = base_mod._get_active_plan()

        assert geladen == neu
        assert base_mod.STATE.active_plan_sig == base_mod._plan_disk_signature("p1")


class TestPlanForWrite:
    def test_ohne_pid_und_ohne_index_gibt_none(self, base_mod, monkeypatch):
        monkeypatch.setattr(base_mod, "_recover_plan_from_disk", lambda: None)
        base_mod.STATE.active_plan_id = ""
        base_mod.STATE.active_plan = None
        assert base_mod.plan_for_write() is None

    def test_fehlende_datei_leert_cache(self, base_mod):
        base_mod.STATE.active_plan = {"plan_id": "p-weg"}
        base_mod.STATE.active_plan_id = "p-weg"

        assert base_mod.plan_for_write("p-weg") is None
        assert base_mod.STATE.active_plan is None

    def test_liest_frisch_von_der_platte(self, base_mod):
        disk = _write_plan(base_mod, "p1", "frisch")
        base_mod.STATE.active_plan = {"plan_id": "p1", "goal": "veraltet"}

        assert base_mod.plan_for_write("p1") == disk
        assert base_mod.STATE.active_plan_id == "p1"
        assert base_mod.STATE.active_plan_sig is not None


class TestLegacyAliase:
    def test_active_plan_sig_proxy(self, base_mod):
        base_mod.STATE.active_plan_sig = ("sig",)
        assert base_mod.__getattr__("_active_plan_sig") == ("sig",)

    def test_active_plan_proxy(self, base_mod):
        base_mod.STATE.active_plan = {"plan_id": "p1"}
        assert base_mod.__getattr__("_active_plan") == {"plan_id": "p1"}

    def test_id_metrics_warnings_session_proxies(self, base_mod):
        base_mod.STATE.active_plan_id = "p9"
        assert base_mod.__getattr__("_active_plan_id") == "p9"
        assert base_mod.__getattr__("_tool_metrics") is base_mod.STATE.tool_metrics
        assert base_mod.__getattr__("_drift_warnings") is base_mod.STATE.drift_warnings
        assert base_mod.__getattr__("_SESSION_ID") == base_mod.STATE.session_id

    def test_unbekannter_name_wirft_attributeerror(self, base_mod):
        with pytest.raises(AttributeError):
            base_mod.__getattr__("gibt_es_nicht")

    def test_cached_plan_liest_nur_den_cache(self, base_mod):
        base_mod.STATE.active_plan = {"plan_id": "p1"}
        assert base_mod._get_cached_plan() == {"plan_id": "p1"}
        base_mod.STATE.active_plan = None
        assert base_mod._get_cached_plan() is None


class TestKaputteDateiImCache:
    def test_signatur_geaendert_und_datei_unlesbar_leert_cache(self, base_mod):
        """Signatur abweichend, ``_load_plan`` liefert None (kaputtes JSON) → Cache weg."""
        _write_plan(base_mod, "p1", "alt")
        sig = base_mod._plan_disk_signature("p1")
        base_mod.STATE.active_plan = {"plan_id": "p1", "goal": "alt"}
        base_mod.STATE.active_plan_id = "p1"
        base_mod.STATE.active_plan_sig = sig

        base_mod._plan_path("p1").write_text("{kaputt", encoding="utf-8")

        assert base_mod._get_active_plan() is None
        assert base_mod.STATE.active_plan is None
