"""resolver.py — Monkeypatch-safe config resolution for plan_follow.

Allows tests to monkeypatch plan_core.PLANS_DIR and have the change
propagate to all submodules at call time.

Pattern:
  from . resolver import resolve_plans_dir, resolve_archive_dir, resolve_roadmaps_dir

  pd = resolve_plans_dir()  # returns plan_core.PLANS_DIR (monkeypatchable!)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Union


def _resolve(name: str, default: Union[Path, str]) -> Union[Path, str]:
    """Resolve a config value from plan_core facade at call time.

    Falls back to the default if plan_core isn't loaded yet (e.g. during
    initial import of the tools package).
    """
    pc = sys.modules.get("plan_follow.plan_core")
    if pc is not None:
        return getattr(pc, name, default)
    return default


def resolve_plans_dir() -> Path:
    return _resolve("PLANS_DIR", Path.home() / ".hermes" / "plans")


def resolve_plans_index() -> Path:
    return _resolve("PLANS_INDEX", Path.home() / ".hermes" / "plans" / "plans_index.json")


def resolve_archive_dir() -> Path:
    return _resolve("ARCHIVE_DIR", Path.home() / ".hermes" / "plans" / "archived")


def resolve_roadmaps_dir() -> Path:
    return _resolve("ROADMAPS_DIR", Path.home() / ".hermes" / "roadmaps")


def resolve_honcho_url() -> str:
    return _resolve("HONCHO_URL", "http://127.0.0.1:8001")


def resolve_honcho_workspace() -> str:
    return _resolve("HONCHO_WORKSPACE", "plan-follow")


def resolve_honcho_peer() -> str:
    return _resolve("HONCHO_PEER", "plan-follow-agent")
