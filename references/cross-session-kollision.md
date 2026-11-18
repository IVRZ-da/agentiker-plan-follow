# Cross-Session-Kollision: Befund (2026-11-18)

Symptom: eine parallele Hermes-Session nimmt den aktiven Plan der anderen weg. Beobachtet
zweimal in derselben Sitzung — `plan_complete` scheiterte mit „Task X is not the current task
(Aktuell: T5)" und einmal mit „No active plan", obwohl der eigene Plan auf Platte offen war.

## Drei Kollisionsebenen

### 1. Prozessglobaler State

`tools/state.py:33` hält `STATE = PlanState()` als Singleton pro Python-Prozess, mit
`active_plan` und `active_plan_id` (Zeile 21-22). Gelesen/geschrieben an **56 Stellen in 7
Modulen**: `tools/base.py` (32), `tools/plan_mgmt.py` (10), `plan_core.py` (6), `tools/task.py`
(4), `tools/state.py` (2), `tools/status.py` (1), `plan_hooks.py` (1).

Laufen mehrere Sessions im selben Prozess (Desktop-Tabs, Gateway mit mehreren Chats), teilen
sie diesen State ohne jeden Dateiumweg.

### 2. Die Session-ID ist nicht pro Session

`tools/base.py:40 get_session_id()` liest `HERMES_SESSION_ID` aus `os.environ` (Zeile 50) und
cached das Ergebnis in `STATE.session_id` (Zeile 48/55). `os.environ` ist prozessglobal — der
erste Aufruf legt die ID für alle Sessions des Prozesses fest. Der eigene Code sagt das in
`plan_hooks.py:90`: „nicht aus dem prozessglobalen `get_session_id()` (im Gateway teilen sich
sonst alle Sessions eine ID)".

Der Hook bekommt die echte ID im Payload, die **Tools** haben keinen `session_id`-Parameter.

Auf dem Host gemessen (2026-11-18, 17:00): mehrere Hermes-Agent-Prozesse parallel
(PIDs 2198517, 2207230, 2209108, 3590326), `HERMES_SESSION_ID` im eigenen Prozess korrekt
gesetzt (`local-16c5719d…`). Also: teils getrennte Prozesse, teils gemeinsamer Prozess — beide
Ebenen kommen vor.

### 3. Ein einziger `active_plan_id` im Index

`tools/base.py:136 _update_plans_index()` schreibt genau ein `active_plan_id` nach
`~/.hermes/plans/plans_index.json` (Zeile 146). Aufrufer ist `set_active_plan`
(`tools/task.py:491-496`), also `plan_create`, `plan_select`, `plan_complete`, `plan_update`.
`_clear_plans_index()` (Zeile 163) leert das Feld, sobald ein Plan keinen `current_task` mehr
hat. Letzter Schreiber gewinnt; Leser sind Banner-Recovery, `plan_status` und die
Disk-Recovery beim ersten Turn einer Session.

Das erklärt beide Fehlerbilder: fremde Task-ID in der Meldung (der Index zeigt auf den fremden
Plan) und „No active plan" (die fremde Session hat den Plan abgeschlossen und den Index
geleert). Die Plan-Dateien selbst sind getrennt — nur der Zeiger kollidiert.

## Was bereits existiert und ungenutzt liegt

- `coord_state.py:167 register_session()` / `:195 update_session()` / `:209 get_sessions()`
  führen `~/.hermes/shared/sessions.json` mit `session_id → {plan_id, goal, cwd, last_seen}`.
  Der Hook `_do_coordination_housekeeping()` (`plan_hooks.py:86-110`) füttert das jeden Turn mit
  der echten Session-ID aus dem Hook-Payload. Das Wissen „welcher Plan gehört welcher Session"
  ist also vorhanden.
- `coord_state.py:220 cleanup_stale_sessions()` (60 min) und `:254 acquire_lock()` /
  `:300 release_lock()` — Locks sind opt-in (`PLAN_FOLLOW_LOCKS=1`, `plan_hooks.py:72-74`,
  Default aus) und sichern Dateien, nicht den Plan-Zeiger.
- Im Core gibt es den korrekten Accessor: `gateway/session_context.py:89 set_current_session_id()`
  setzt ContextVar **und** `os.environ["HERMES_SESSION_ID"]`; `:230 get_session_env(name, default)`
  liest bevorzugt den ContextVar (pro Task korrekt, prozessübergreifend unabhängig).

## Konsequenz für die Umsetzung

1. **Session-ID zuerst** (ContextVar vor `os.environ`) — ohne sie arbeitet jede weitere Trennung
   auf einer falschen ID.
2. **State pro Session** kapseln, ohne die 56 Aufrufstellen anzufassen (Properties über
   session-scoped Slots).
3. **Ownership-Guard am Index**: nicht überschreiben, solange eine andere *lebende* Session den
   Eintrag hält (Mitgliedschaft in `sessions.json` mit `last_seen` innerhalb 60 min).

## Baseline der Suite vor dem Eingriff

```
/usr/bin/python3 -m pytest tests -q -n 8 -p no:cacheprovider
1638 passed, 1 skipped, 2 failed in 175.9s
```

Die zwei Fehlschläge sind **pre-existing** und gehören nicht zu dieser Arbeit:

- `tests/test_init.py::TestEagerIntegration::test_tool_becomes_non_deferrable`
- `tests/test_plan_follow.py::TestDispatchHonchoTool::test_dispatch_tool_entry_not_found`
  (erwartet `None`, bekommt `{'result': 'ok'}` — der Honcho-Dispatch ist nach dem
  Provider-Umstieg nicht mehr leer)

Ein einzelner Lauf ohne `-n 8` dauert > 180 s und läuft in das Timeout — für Iterationen immer
`-n 8` oder gezielte Testdateien verwenden.
