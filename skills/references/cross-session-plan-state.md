# Cross-Session Plan-State: warum parallele Sessions kollidieren

Zwei Hermes-Sessions, ein Plan-System. Symptome: `Task 'X' is not the current task
(Aktuell: T5)` mit einer ID, die man nie vergeben hat; oder `No active plan`, obwohl im
eigenen Plan-Datei noch Tasks offen sind. Beide Meldungen sind dasselbe Problem.

## Ursache (drei Ebenen)

1. **Prozessglobaler State.** `tools/state.py` hält `STATE = PlanState()` als Singleton pro
   Python-Prozess; `STATE.active_plan` / `STATE.active_plan_id` werden in ~56 Stellen in 7
   Modulen gelesen und geschrieben (`tools/base.py` dominiert, dazu `plan_mgmt`, `plan_core`,
   `task`, `status`, `plan_hooks`). Laufen mehrere Sessions im Gateway-Prozess (Desktop-Tabs,
   parallele CLI), teilen sie diesen State ohne Datei-Umweg.
2. **Session-ID ist im Gateway nicht pro Session unterscheidbar.** `get_session_id()`
   (`tools/base.py`) liest `HERMES_SESSION_ID` aus `os.environ` und cached sie in
   `STATE.session_id` — beides prozessglobal. Der Hook bekommt die echte ID im Payload
   (`_do_coordination_housekeeping`), die **Tools** nicht; sie haben keinen `session_id`-
   Parameter.
3. **Ein einziger Index-Eintrag.** `_update_plans_index()` (`tools/base.py`) schreibt genau
   ein `active_plan_id` nach `~/.hermes/plans/plans_index.json`. Aufrufer ist
   `set_active_plan` (`tools/task.py`), also `plan_create` / `plan_select` / `plan_complete` /
   `plan_update`. Letzter Schreiber gewinnt; Leser sind Recovery beim ersten Turn, Banner und
   `plan_status`.

## Was bereits existiert und nur nicht steuert

- `coord_state.py` führt `~/.hermes/shared/sessions.json` mit
  `session_id → {plan_id, goal, cwd, last_seen}` und wird vom Hook **jeden Turn** mit der
  echten Session-ID aktualisiert. Das Wissen „welcher Plan gehört welcher Session" liegt also
  schon auf Platte — es beeinflusst nur weder Index noch Recovery.
- `acquire_lock` / `release_lock` / `cleanup_stale_locks` und `cleanup_stale_sessions`
  existieren; Locks sind opt-in (`PLAN_FOLLOW_LOCKS=1`) und sichern Dateien, nicht den
  Plan-Zeiger.
- Der Core hat den korrekten Accessor: `gateway/session_context.py` hält die Session-ID in
  einem **ContextVar** (pro Task/Thread richtig, anders als `os.environ`) und bietet
  `get_session_env(name, default)` sowie `bound_session_key()`.

## Optionen

| Option | Wirkung | Aufwand | Grenze |
|---|---|---|---|
| **A** Index session-fähig (`sessions: {sid: …}` + Legacy-Feld) | löst Cross-Session **und** Cross-Prozess, inkl. Recovery | mittel-hoch: alle Leser (Banner, Recovery, `plan_status`) umstellen, Migration nötig | braucht vorher den sid-Fix |
| **B** `STATE` pro Session (`dict[sid]`) | löst In-Process-Kollision vollständig | hoch: ~56 Referenzen + Tests | hilft nicht bei getrennten Prozessen |
| **C** Ownership-Guard beim Schreiben | Überschreiben wird verweigert statt nur sichtbar | ~1–2 h, keine Migration | bewusstes gemeinsames Arbeiten an einem Plan braucht eine Übernahme-Regel |
| **D** nur Konvention (`/new`, `plan_select` vor jedem Block) | nichts | 0 | kostet Disziplin im Flow |
| **E** Core: Session-Kontext für Tool-Calls verbindlich | sauberste Schicht | außerhalb des Plugins | ContextVar existiert schon — kein eigener Weg |

## Empfohlene Reihenfolge

1. **sid-Fix** (Enabler): `get_session_id()` liest zuerst
   `gateway.session_context.get_session_env("HERMES_SESSION_ID")`, dann `os.environ`. Ohne
   diesen Schritt arbeitet jede Session-Trennung im Plugin auf einer falschen ID — auch die
   bestehende `sessions.json` ist im Gateway sonst unzuverlässig.
2. **Ownership-Guard (C)**: `set_active_plan` prüft, ob der eingetragene Plan einer anderen
   *lebenden* Session gehört (`sessions.json`, `last_seen` < 60 min, `sid != meine`); wenn ja,
   nicht überschreiben, sondern Warnung + eigenen Plan in `sessions[meine].plan_id` führen,
   und `plan_current` bevorzugt den eigenen Eintrag lesen.
3. **Session-fähiger Index (A)** nur, wenn Stufe 2 im Alltag an Grenzen stößt (mehrere offene
   Pläne, Recovery nach Neustart).

Nicht empfehlen: B allein (teuer, halbe Lösung).

## Sofort-Regel ohne Umbau

Vor **jedem** `plan_complete`: `plan_current()` prüfen, ob dort die eigene `plan_id` steht —
die Prüfung gehört direkt vor den Abschluss, nicht an den Blockanfang, weil die andere
Session zwischendurch erneut umschalten kann. Danach die eigene Task-ID senden. `plan_select`
holt den Plan zurück, ändert aber nur den Index, nie die fremde Plan-Datei — deshalb ist der
Direktweg über das eigene Plan-JSON (Status/`current_task` setzen) beim Abschluss-Sprint
verlässlicher als ein Wettlauf mit `plan_select`.
