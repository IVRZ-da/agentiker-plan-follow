# Tool-Surface-Baseline (plan_follow)

Messung vom 2026-11-18 vor dem Token-Umbau. Reproduzierbar:

```
env -u PYTHONPATH ~/.hermes/hermes-agent/venv/bin/python3 scripts/tool_schema_audit.py .
```

Hermes rechnet Tokens als `chars / 4.0` (`tools/tool_search_catalog.py: CHARS_PER_TOKEN`).

## Summen

| Kennzahl | Zeichen | ≈ Tokens |
|---|---:|---:|
| Alle 39 Tools (obere Schranke, falls alles eager wäre) | 48.313 | 12.078 |
| **Eager (`EAGER_TOOLS`)** — das steht pro Turn im Prompt | **10.947** | **2.737** |
| Deferred (34 Tools, kosten nur Katalognamen) | 37.366 | 9.341 |

## Die eager Tools (Kostentreiber)

| Tool | Zeichen | ≈ Tokens |
|---|---:|---:|
| plan_create | **6.713** | 1.678 |
| plan_complete | 1.779 | 445 |
| plan_update | 1.550 | 388 |
| plan_current | 490 | 122 |
| plan_status | 415 | 104 |

`plan_create` allein sind 6.713 Zeichen = **61 % der Eager-Kosten** und 14 % der Gesamtfläche.

## Größte deferred Tools (nur relevant, falls sie eager würden)

| Tool | Zeichen | ≈ Tokens |
|---|---:|---:|
| plan_roadmap | 5.186 | 1.296 |
| plan_auto_review | 1.663 | 416 |
| plan_pr_create | 1.634 | 408 |
| plan_notify | 1.566 | 392 |
| plan_decompose | 1.546 | 386 |
| plan_todo | 1.518 | 379 |
| plan_review | 1.484 | 371 |
| plan_template | 1.466 | 366 |

## Zielbudgets (aus dem Plan 2026-11-18-plugin-tool-surface-ausbau)

| Task | Budget | Prüfung |
|---|---|---|
| T2 | `plan_create` ≤ 3.000 Zeichen | `--max-chars plan_create=3000` |
| T3 | Eager-Set = {plan_create, plan_current, plan_complete} | `tests/test_eager_tools.py` |
| T4 | eager-Summe ≤ 9.000 Zeichen | `--max-eager-chars 9000` |

Erwartete Einsparung nach T2+T3: rund 1.400 Tokens pro Turn
(von 2.737 auf ~1.300) bei unveränderter Funktionsfläche — die 34 deferred Tools
bleiben unangetastet.
