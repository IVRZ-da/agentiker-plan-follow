"""config.py — Mutable shared configuration for plan_follow.

All modules access config via get/set functions, allowing
monkeypatching and test isolation.

Usage:
    from plan_follow.tools.config import CFG
    print(CFG.PLANS_DIR)
    CFG.PLANS_DIR = tmp_path  # for tests
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class PlanConfig:
    """Mutable configuration container.

    All path constants are stored here so that tests can monkeypatch
    them by setting CFG.ATTR directly. Submodules read from CFG
    at call time, not at import time.
    """

    def __init__(self) -> None:
        self.PLANS_DIR: Path = Path.home() / ".hermes" / "plans"
        self.PLANS_INDEX: Path = self.PLANS_DIR / "plans_index.json"
        self.ARCHIVE_DIR: Path = self.PLANS_DIR / "archived"
        self.ROADMAPS_DIR: Path = Path.home() / ".hermes" / "roadmaps"
        self.HONCHO_URL: str = "http://127.0.0.1:8001"
        self.HONCHO_WORKSPACE: str = "plan-follow"
        self.HONCHO_PEER: str = "plan-follow-agent"


CFG: PlanConfig = PlanConfig()
