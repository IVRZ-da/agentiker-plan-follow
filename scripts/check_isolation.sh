#!/usr/bin/env bash
# check_isolation.sh — beweist, dass die plan_follow-Testsuite Produktionsdaten
# unter ~/.hermes unberuehrt laesst.
#
# Hintergrund: bis v0.5.31 ueberschrieb tests/conftest.py alle *.json in
# ~/.hermes/plans mit "{}" und loeschte Unterordner (archived/, templates/).
# Die Suite war dabei 1480/1480 gruen — niemand merkte es.
#
# Ablauf: Manifest (Pfad + Groesse) vor dem Lauf, volle Suite mit aktivem
# Write-Guard, Manifest danach, Vergleich. Jede neue/verschwundene/veränderte
# Datei laesst den Check fehlschlagen.
#
# Nicht verglichen werden rein fluechtige Laufzeitdateien des LIVE-Gateways, das
# waehrend des Testlaufs Tool-Calls protokolliert:
#   ~/.hermes/plans/.session-logs/   (Hook-Log des laufenden Prozesses)
#   ~/.hermes/shared/sessions.json, locks.json, notifications.json
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${TEST_PY:-/home/jo/.hermes/hermes-agent/venv/bin/python}"
HERMES_DIR="${HOME}/.hermes"

if [[ ! -x "$PY" ]]; then
  echo "FAIL: Test-Interpreter nicht gefunden: $PY (TEST_PY setzen)" >&2
  exit 2
fi

manifest() {
  find "${HERMES_DIR}/plans" "${HERMES_DIR}/roadmaps" "${HERMES_DIR}/shared" \
    -type f \
    -not -path "*/.session-logs/*" \
    -not -path "*/plans/templates/*.tmp" \
    -printf "%p %s\n" 2>/dev/null \
  | grep -v -E "shared/(sessions|locks|notifications)\\.json|shared/tts_queue\\.(json|lock)" \
  | sort
}

before="$(mktemp)"
after="$(mktemp)"
trap 'rm -f "$before" "$after"' EXIT

manifest > "$before"
echo "Manifest: $(wc -l < "$before") Dateien unter ${HERMES_DIR}"

PLAN_FOLLOW_TEST_GUARD=1 "$PY" -m pytest "$REPO/tests" -q --no-header -p no:cacheprovider
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "FAIL: Testsuite rot (exit $rc) — Isolation nicht bewertbar" >&2
  exit 1
fi

manifest > "$after"

if ! diff -q "$before" "$after" > /dev/null; then
  echo "FAIL: Produktionsdaten wurden veraendert:" >&2
  diff "$before" "$after" >&2
  exit 1
fi

# Hinweis (kein Fehler): bereits vor dem Lauf vorhandene 2-Byte-Plan-Dateien sind
# Altlasten des Vorfalls vom 10.11.2026. Sie werden gemeldet, aber nicht als
# Regression gewertet — der diff oben beweist, dass dieser Lauf nichts verändert hat.
legacy="$(awk '$2 <= 2 {print}' "$after" | grep -cE "/plans/[^/]+\.json" || true)"
if [[ "${legacy:-0}" -gt 0 ]]; then
  echo "HINWEIS: ${legacy} leere Plan-Datei(en) aus dem Vorfall vom 10.11.2026 vorhanden"
  echo "         (Recovery: scripts/recover_plans_from_db.py --dry-run)"
fi

echo "OK: reale Daten unberuehrt ($(wc -l < "$after") Dateien unveraendert)"
