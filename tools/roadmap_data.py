"""roadmap_data.py — Roadmap data functions for plan_follow tools/ subpackage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .base import (
    _ensure_dirs,
    logger,
)
from .resolver import resolve_roadmaps_dir

# ─── Roadmap Data Model ──────────────────────────────────────────────────────


def _roadmap_path(name: str) -> Path:
    """Get the filesystem path for a roadmap YAML file.

    Args:
        name: Roadmap name (with or without .yaml extension).

    Raises:
        ValueError: If name contains path traversal (..) or is absolute.
    """
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid roadmap name: '{name}' (path traversal blocked)")
    if name.endswith(".yaml"):
        name = name[:-5]
    return resolve_roadmaps_dir() / f"{name}.yaml"


def _list_roadmaps() -> list[dict]:
    """List all available roadmap files.

    Returns:
        List of dicts with 'name' and 'path' keys, sorted by modification time (newest first).
    """
    roadmaps = []
    for f in sorted(resolve_roadmaps_dir().glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        roadmaps.append({
            "name": f.stem,
            "path": str(f),
            "modified": f.stat().st_mtime,
        })
    return roadmaps


def _load_roadmap(name: str) -> Optional[dict]:
    """Load a roadmap from a YAML file.

    Args:
        name: Roadmap name (with or without .yaml).

    Returns:
        Parsed roadmap dict, or None if file not found or invalid.
    """
    path = _roadmap_path(name)
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")

        # Try JSON first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try python yaml if available
        try:
            import yaml
            return yaml.safe_load(content)
        except ImportError:
            pass

        # Fallback: simple hand-rolled parser (same as plan_templates)
        return _parse_roadmap_yaml_simple(content)
    except Exception:
        logger.warning(f"Roadmap '{name}' could not be loaded")
        return None


def _save_roadmap(name: str, data: dict) -> bool:
    """Save a roadmap as YAML file.

    Args:
        name: Roadmap name (without .yaml).
        data: Roadmark dict with 'name', 'goal', 'phases' etc.

    Returns:
        True on success, False on failure.
    """
    _ensure_dirs()
    path = _roadmap_path(name)
    try:
        # Try to use yaml for prettier output
        try:
            import yaml
            content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except ImportError:
            # Fallback to JSON
            import json
            content = json.dumps(data, indent=2, ensure_ascii=False)

        path.write_text(content, encoding="utf-8")
        logger.info(f"Roadmap '{name}' saved to {path}")
        return True
    except Exception as e:
        logger.warning(f"Roadmap '{name}' could not be saved: {e}")
        return False


def _parse_roadmap_yaml_simple(content: str) -> Optional[dict]:
    """Simple YAML parser for roadmap files.

    Handles: top-level keys, list of phases with nested fields.
    Uses indentation to distinguish top-level from phase-level keys.
    """
    try:
        result = {}
        current_phase = None
        phases = []
        in_phases = False

        for line in content.split("\n"):
            # Skip empty and comment lines
            if not line.strip() or line.strip().startswith("#"):
                continue

            stripped = line.strip()
            indent = len(line) - len(line.lstrip())

            # If we're inside phases and this line has indentation, it's a phase field
            if in_phases and indent > 0:
                # Phase list item
                if stripped.startswith("-"):
                    if current_phase:
                        phases.append(current_phase)
                    current_phase = {}
                    rest = stripped[1:].strip()
                    if rest:
                        for part in rest.split("  "):
                            part = part.strip()
                            if ":" in part:
                                k, _, v = part.partition(":")
                                k = k.strip()
                                v = v.strip().strip('"').strip("'")
                                if v.startswith("[") and v.endswith("]"):
                                    v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",")]
                                current_phase[k] = v
                # Phase field (indented key: value)
                elif ":" in stripped:
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if v.startswith("[") and v.endswith("]"):
                        v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",")]
                    current_phase[k] = v
                continue

            # Phase task list item (indented - with no key: value)
            if in_phases and indent > 0 and stripped.startswith("-"):
                # Already handled above
                continue

            # Top-level key: value (no indentation)
            if indent == 0 and ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "phases":
                    in_phases = True
                elif key == "name":
                    result["name"] = val
                elif key == "goal":
                    result["goal"] = val
                elif key == "created":
                    result["created"] = val
                else:
                    result[key] = val
                continue

            # If we hit a non-indented, non-empty line after phases, we're out of phases
            if in_phases and indent == 0 and current_phase is not None:
                # Could be a new top-level key after phases
                pass

        if current_phase:
            phases.append(current_phase)
        if phases:
            result["phases"] = phases

        if result:
            return result
    except Exception:
        pass

    return None
