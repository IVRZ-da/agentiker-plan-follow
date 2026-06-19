"""
review_profiles.py — Review-Profile-Definitionen für das plan_follow Plugin.

Jedes Profil definiert eine Liste von Checks, die beim Review durchgeführt werden.
Die Profile werden von plan_review.py und plan_review_tool genutzt.

Profile:
  - none:        Kein Review (Default)
  - unit-test:   Tests + Coverage + Edge-Cases
  - api-route:   API-Routen: Validierung + Error-Handling + Auth + Security
  - ui-component: React/UI: A11y + SSR + State + Forms + Mobile
  - security:    Security: Secrets + Injection + XSS + Auth
  - full:        Alle Checks (Kombination aller Profile)
"""

from __future__ import annotations

from typing import Any


PROFILES: dict[str, dict[str, Any]] = {
    "none": {
        "description": "Kein Review — Task wird ohne Prüfung abgeschlossen.",
        "checks": [],
    },
    "unit-test": {
        "description": "Tests + Coverage + Edge-Cases: prüft dass neue Tests existieren, "
                       "Edge-Cases abgedeckt sind und keine Debug-Overheads zurückbleiben.",
        "checks": [
            "code_compiles",
            "new_tests_exist",
            "test_count_increased",
            "edge_cases_covered",
            "no_debug_prints",
            "test_names_descriptive",
            "test_coverage_90",
            "test_coverage_measured",
        ],
    },
    "api-route": {
        "description": "API-Routen: prüft Input-Validierung, Error-Handling, "
                       "Authentifizierung, Rate-Limiting und Sicherheit.",
        "checks": [
            "input_validation",
            "error_handling",
            "auth_check",
            "rate_limiting",
            "sql_injection",
            "response_consistency",
            "logging",
        ],
    },
    "ui-component": {
        "description": "React/UI-Komponenten: prüft A11y, SSR-Kompatibilität, "
                       "State-Management, Form-Validierung und Mobile-Responsiveness.",
        "checks": [
            "a11y_basics",
            "ssr_compatible",
            "no_state_mutation",
            "form_validation",
            "mobile_responsive",
            "no_vanilla_dom",
        ],
    },
    "security": {
        "description": "Security: prüft auf Secrets im Code, Injection-Schwachstellen, "
                       "XSS, CSRF, Path-Traversal und unsichere Auswertungen.",
        "checks": [
            "no_secrets_in_code",
            "input_sanitization",
            "csrf_protection",
            "data_validation",
            "no_eval",
            "no_path_traversal",
        ],
    },
    "full": {
        "description": "Alle Checks: Kombination aller Profile — für kritische Tasks.",
        "checks": [
            "code_compiles",
            "new_tests_exist",
            "test_count_increased",
            "edge_cases_covered",
            "no_debug_prints",
            "input_validation",
            "error_handling",
            "auth_check",
            "sql_injection",
            "a11y_basics",
            "ssr_compatible",
            "no_secrets_in_code",
            "input_sanitization",
            "csrf_protection",
            "no_eval",
            "test_coverage_90",
            "test_coverage_measured",
        ],
    },
}

PROFILE_NAMES = tuple(PROFILES.keys())


def get_profile(name: str) -> dict[str, Any]:
    """Hole ein Review-Profil anhand seines Namens.

    Args:
        name: Profilname (none, unit-test, api-route, ui-component, security, full)

    Returns:
        Das Profil-Dict mit description und checks, oder das none-Profil bei unbekanntem Namen.
    """
    return PROFILES.get(name, PROFILES["none"])


def get_check_description(check_name: str) -> str:
    """Hole eine menschenlesbare Beschreibung für einen Check-Namen.

    Args:
        check_name: Technischer Check-Name (z.B. 'code_compiles', 'input_validation')

    Returns:
        Beschreibung des Checks in Deutsch.
    """
    descriptions = {
        "code_compiles": "Code compiliert fehlerfrei (tsc --noEmit, go build, etc.)",
        "new_tests_exist": "Neue Tests existieren für neue Funktionen",
        "test_count_increased": "Test-Anzahl ist gestiegen (keine ungetesteten Änderungen)",
        "edge_cases_covered": "Edge-Cases abgedeckt (leere Inputs, null, Grenzfälle)",
        "no_debug_prints": "Keine Debug-Prints / console.log zurückgelassen",
        "test_names_descriptive": "Test-Namen sind deskriptiv (describe/it)",
        "input_validation": "Input-Validierung vorhanden (Zod / Joi / express-validator)",
        "error_handling": "Error-Handling (try/catch, kein unhandled rejection)",
        "auth_check": "Auth/Authorization-Check (wer darf diese Route aufrufen?)",
        "rate_limiting": "Rate-Limiting (bei öffentlichen Endpunkten)",
        "sql_injection": "Keine SQL/NoSQL-Injection (parametrisierte Queries)",
        "response_consistency": "Response-Format konsistent",
        "logging": "Logging vorhanden (insb. Fehler-Fälle)",
        "a11y_basics": "A11y-Grundlagen (aria-labels, focus-management, tab-order)",
        "ssr_compatible": "SSR-kompatibel (kein window/document in Server Components)",
        "no_state_mutation": "Keine State-Mutation (kein state.foo.bar = x)",
        "form_validation": "Form-Validierung (onSubmit + onChange, keine Lücke)",
        "mobile_responsive": "Mobile-Responsive (Tailwind Breakpoints)",
        "no_vanilla_dom": "Keine Vanilla-JS DOM-Manipulation (useRef statt getElementById)",
        "test_coverage_90": "Test-Coverage ist ≥ 90% (gemessen via pytest --cov)",
        "test_coverage_measured": "Coverage-Messung wurde erfolgreich durchgeführt (kein Fehler im Messprozess)",
        "no_secrets_in_code": "Keine Secrets/Keys im Code (nur env-vars)",
        "input_sanitization": "Input-Sanitization (XSS, HTML Injection)",
        "csrf_protection": "CSRF-Schutz (bei Server Actions: CSRF-Token)",
        "data_validation": "Daten-Validierung (type-checking, bounds-checking)",
        "no_eval": "Keine eval() / exec() / new Function()",
        "no_path_traversal": "Keine Path-Traversal in File-Operationen",
    }
    return descriptions.get(check_name, f"Unbekannter Check: {check_name}")
