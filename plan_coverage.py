"""
plan_coverage.py — Coverage-Messung für das plan_follow Plugin.

Stellt Funktionen bereit, um die Testabdeckung eines Projekts
automatisch zu messen, bevor der Review-Prompt gebaut wird.

Funktionen:
  - measure_coverage(): Misst pytest --cov auf einem Projekt
  - get_project_path(): Leitet Projekt-Root aus task.files oder plan.repo ab
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("plan_follow")

# Coverage-Schwellwert (default: 80% — critical-only)
# Warum 80% statt 90%: Coverage unter 80% signalisiert echte Lücken,
# während 80-90% oft durch triviale Tests erreichbar ist.
# Fokus: Behaviorale Tests mit guten Assertions statt Coverage-Jagd.
DEFAULT_COVERAGE_THRESHOLD = 80.0


def get_project_from_files(files: list[str]) -> Optional[str]:
    """Leite das Projekt-Root aus den task.files ab.

    Geht vom ersten Dateipfad aus und wandert nach oben, bis
    eine Projekt-Markierungsdatei gefunden wird.

    Sucht nach: pyproject.toml, setup.py, setup.cfg, package.json, go.mod
    """
    if not files:
        return None

    # Nimm die erste Datei als Startpunkt
    first_file = files[0]
    path = Path(first_file).resolve()

    if not path.exists():
        # Versuche den Parent des ersten existierenden Teils
        for parent in path.parents:
            if parent.exists():
                path = parent
                break
        else:
            return None

    # Geh nach oben, such nach Projekt-Markern
    markers = ["pyproject.toml", "setup.py", "setup.cfg", "package.json", "go.mod", ".git"]
    for parent in [path] + list(path.parents):
        for marker in markers:
            if (parent / marker).exists():
                return str(parent)
        # Stopp bei /home oder /
        if str(parent) in ("/home", "/"):
            break

    return None


def get_project_path(task: dict, plan: Optional[dict] = None) -> Optional[str]:
    """Bestimme den Projekt-Pfad für Coverage-Messung.

    Reihenfolge:
    1. task['coverage_path'] (explizit gesetzt)
    2. task['project'] (alternatives Feld)
    3. plan['repo'] (einzelnes Repo)
    4. plan['repos'][0] (erstes von mehreren)
    5. Abgeleitet aus task['files']
    6. Aktuelles Arbeitsverzeichnis (letzter Fallback)
    """
    # Explizite Angabe
    cov_path = task.get("coverage_path") or task.get("project")
    if cov_path:
        p = Path(cov_path)
        if p.exists():
            return str(p.resolve())

    # Plan-Repo
    if plan:
        repos_plan = plan.get("repos", []) or []
        single_repo = plan.get("repo", "")
        repo = single_repo or (repos_plan[0] if repos_plan else None)
        if repo:
            p = Path(repo)
            if p.exists():
                return str(p.resolve())

    # Aus Dateien ableiten
    files = task.get("files", [])
    if files:
        result = get_project_from_files(files)
        if result:
            return result

    # Letzter Fallback: CWD
    try:
        return os.getcwd()
    except Exception:
        return None


def measure_coverage(
    project_path: str,
    threshold: float = DEFAULT_COVERAGE_THRESHOLD,
    test_path: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """Messe die Testabdeckung eines Python-Projekts mit pytest --cov.

    Args:
        project_path: Absoluter Pfad zum Projekt-Root.
        threshold: Mindest-Coverage in Prozent (default: 90.0).
        test_path: Optionaler Pfad zum Testverzeichnis (default: 'tests/').
        timeout: Timeout in Sekunden (default: 120).

    Returns:
        Dict mit:
          - success: True wenn Messung erfolgreich
          - pct: Gemessene Coverage in Prozent
          - covered: Abgedeckte Zeilen
          - total: Gesamtzeilen
          - missing_files: Liste der Dateien mit < 100% Coverage
          - passed: True wenn coverage >= threshold
          - threshold: Der verwendete Schwellwert
          - error: Fehlermeldung (wenn success=False)
    """
    if not os.path.isdir(project_path):
        return {
            "success": False,
            "error": f"Project path does not exist: {project_path}",
            "pct": 0.0,
            "covered": 0,
            "total": 0,
            "missing_files": [],
            "passed": False,
            "threshold": threshold,
        }

    # Test-Verzeichnis bestimmen
    if test_path is None:
        test_dir = os.path.join(project_path, "tests")
        if not os.path.isdir(test_dir):
            # Such nach __test__ Ordnern
            test_candidates = [
                os.path.join(project_path, d)
                for d in os.listdir(project_path)
                if d.startswith("test") and os.path.isdir(os.path.join(project_path, d))
            ]
            if test_candidates:
                test_dir = test_candidates[0]
            else:
                return {
                    "success": False,
                    "error": "No test directory found",
                    "pct": 0.0,
                    "covered": 0,
                    "total": 0,
                    "missing_files": [],
                    "passed": False,
                    "threshold": threshold,
                }
    else:
        test_dir = test_path if os.path.isabs(test_path) else os.path.join(project_path, test_path)

    if not os.path.isdir(test_dir):
        return {
            "success": False,
            "error": f"Test directory does not exist: {test_dir}",
            "pct": 0.0,
            "covered": 0,
            "total": 0,
            "missing_files": [],
            "passed": False,
            "threshold": threshold,
        }

    # Coverage-Messung via subprocess
    original_dir = os.getcwd()
    coverage_json_path = None
    try:
        # Prüfe ob pytest-cov installiert ist (graceful degradation)
        try:
            import subprocess as _sp
            cov_check = _sp.run(
                [sys.executable, "-m", "pytest", "--cov", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            if cov_check.returncode != 0:
                return {
                    "success": False,
                    "error": "pytest-cov nicht installiert. Installation: pip install pytest-cov",
                    "pct": 0.0,
                    "covered": 0,
                    "total": 0,
                    "missing_files": [],
                    "passed": False,
                    "threshold": threshold,
                }
        except (OSError, _sp.TimeoutExpired):
            return {
                "success": False,
                "error": "pytest-cov nicht verfügbar (kann nicht ausgeführt werden)",
                "pct": 0.0,
                "covered": 0,
                "total": 0,
                "missing_files": [],
                "passed": False,
                "threshold": threshold,
            }

        os.chdir(project_path)

        # Temporäre Datei für Coverage-JSON-Output
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="cov_"
        ) as tmp:
            coverage_json_path = tmp.name

        # --cov-report=json schreibt nach coverage.json im CWD
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            test_dir,
            "-q",
            "--tb=short",
            "--cov",
            project_path,
            "--cov-report=json",
            "--no-header",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # Lese coverage.json aus dem Projekt-Root
        cov_file = os.path.join(project_path, "coverage.json")
        if not os.path.exists(cov_file):
            # Alternative: Coverage-Daten direkt aus pytest-Output parsen
            stdout = result.stdout
            stderr = result.stderr
            # Fallback: Versuch coverage mit dem Python-Modul zu lesen
            if os.path.exists(".coverage"):
                import coverage as cov_mod

                cov_data = cov_mod.CoverageData()
                try:
                    cov_data.read()
                    measured = cov_data.line_counts()
                    if measured:
                        covered = sum(1 for c in measured.values() if c > 0)
                        total = len(measured)
                        pct = (covered / total) * 100 if total > 0 else 0.0
                        return {
                            "success": True,
                            "pct": round(pct, 2),
                            "covered": covered,
                            "total": total,
                            "missing_files": [],
                            "passed": pct >= threshold,
                            "threshold": threshold,
                        }
                except Exception as e:
                    logger.debug("Coverage JSON parse failed, falling back to regex: %s", e)

            # Parse coverage summary from stdout
            pct_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)\s+(\d+)%\s*$", stdout, re.MULTILINE)
            if pct_match:
                total = int(pct_match.group(1))
                pct = float(pct_match.group(2))
                return {
                    "success": True,
                    "pct": pct,
                    "covered": total,
                    "total": total,
                    "missing_files": [],
                    "passed": pct >= threshold,
                    "threshold": threshold,
                }

            return {
                "success": False,
                "error": f"Could not parse coverage data. stdout: {stdout[:500]}",
                "pct": 0.0,
                "covered": 0,
                "total": 0,
                "missing_files": [],
                "passed": False,
                "threshold": threshold,
                "stdout": stdout[:1000],
                "stderr": stderr[:500],
            }

        # Parsen der coverage.json
        try:
            with open(cov_file) as f:
                cov_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            return {
                "success": False,
                "error": f"Failed to parse coverage.json: {e}",
                "pct": 0.0,
                "covered": 0,
                "total": 0,
                "missing_files": [],
                "passed": False,
                "threshold": threshold,
            }
        finally:
            # coverage.json aufräumen
            try:
                os.remove(cov_file)
            except OSError:
                pass

        totals = cov_data.get("totals", {})
        pct = float(totals.get("percent_covered", 0))
        covered_lines = int(totals.get("covered_lines", 0))
        num_statements = int(totals.get("num_statements", 0))

        # Dateien mit < 100% Coverage
        missing_files = []
        for file_path, file_data in cov_data.get("files", {}).items():
            file_totals = file_data.get("summary", {})
            file_pct = file_totals.get("percent_covered", 100)
            if isinstance(file_pct, (int, float)) and file_pct < 100:
                missing_files.append({
                    "path": file_path,
                    "pct": round(file_pct, 1),
                    "missing_lines": file_totals.get("missing_lines", 0),
                })

        # Sortieren nach Coverage (niedrigste zuerst)
        missing_files.sort(key=lambda x: x["pct"])

        return {
            "success": True,
            "pct": round(pct, 2),
            "covered": covered_lines,
            "total": num_statements,
            "missing_files": missing_files[:20],  # Max 20 Dateien anzeigen
            "passed": pct >= threshold,
            "threshold": threshold,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Coverage measurement timed out after {timeout}s",
            "pct": 0.0,
            "covered": 0,
            "total": 0,
            "missing_files": [],
            "passed": False,
            "threshold": threshold,
        }
    except Exception as e:
        logger.warning("Coverage measurement failed: %s", e)
        return {
            "success": False,
            "error": str(e),
            "pct": 0.0,
            "covered": 0,
            "total": 0,
            "missing_files": [],
            "passed": False,
            "threshold": threshold,
        }
    finally:
        os.chdir(original_dir)
        # Aufräumen
        if coverage_json_path and os.path.exists(coverage_json_path):
            try:
                os.remove(coverage_json_path)
            except OSError:
                pass
        # Coverage-Datei aus Projekt-Root aufräumen (falls im CWD gelandet)
        try:
            cov_file = os.path.join(project_path, "coverage.json")
            if os.path.exists(cov_file):
                os.remove(cov_file)
        except OSError:
            pass


# ─── Mutation Testing (PoC) ─────────────────────────────────────────

def run_mutation_testing(
    project_path: str,
    target_file: Optional[str] = None,
    timeout: int = 300,
) -> dict:
    """Führe Mutation-Testing mit mutmut aus (PoC).

    Ist ein OPTIONALER Schritt — wird nur ausgeführt wenn mutmut
    installiert ist. Dient als Qualitätsindikator: Eine Mutation,
    die nicht getötet wird, zeigt fehlende Assertions.

    Args:
        project_path: Absoluter Pfad zum Projekt-Root.
        target_file: Optionales Target (Datei oder Modul).
        timeout: Timeout in Sekunden (default: 300).

    Returns:
        Dict mit:
          - available: True wenn mutmut installiert
          - success: True wenn Tests laufen
          - killed: Anzahl getöteter Mutanten
          - survived: Anzahl überlebender Mutanten (je weniger, desto besser)
          - error: Fehlermeldung
    """
    # Prüfe ob mutmut installiert ist
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "mutmut", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {
                "available": False,
                "success": False,
                "error": "mutmut nicht installiert (pip install mutmut)",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {
            "available": False,
            "success": False,
            "error": "mutmut nicht installiert (pip install mutmut)",
        }

    original_dir = os.getcwd()
    try:
        os.chdir(project_path)

        cmd = [sys.executable, "-m", "mutmut", "run"]
        if target_file:
            cmd.extend(["--paths-to-mutate", target_file])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )

        # Parse Ergebnis
        killed = 0
        survived = 0
        for line in result.stdout.splitlines():
            if "killed" in line.lower():
                import re
                match = re.search(r"(\d+)", line)
                if match:
                    killed = int(match.group(1))
            if "survived" in line.lower() or "suspicious" in line.lower():
                import re
                match = re.search(r"(\d+)", line)
                if match:
                    survived += int(match.group(1))

        return {
            "available": True,
            "success": True,
            "killed": killed,
            "survived": survived,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
        }

    except subprocess.TimeoutExpired:
        return {
            "available": True,
            "success": False,
            "error": f"Mutation testing timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "available": True,
            "success": False,
            "error": str(e),
        }
    finally:
        os.chdir(original_dir)
