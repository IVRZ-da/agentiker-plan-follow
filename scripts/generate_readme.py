#!/usr/bin/env python3
"""README auto-generator for plan_follow — uses shared generate_readme_base.py.

Usage:
    python3 scripts/generate_readme.py          # update README.md in place
    python3 scripts/generate_readme.py --check  # exit 1 if README is stale
    python3 scripts/generate_readme.py --verbose  # show debug info
"""

import re
import sys
from pathlib import Path

BASE = Path.home() / ".hermes" / "scripts" / "generate_readme_base.py"
sys.path.insert(0, str(BASE.parent))
from generate_readme_base import ReadmeGenerator, read_existing_descriptions, merge_descriptions  # noqa: E402, I001


PLUGIN_DIR = Path(__file__).resolve().parent.parent


class PlanFollowReadmeGenerator(ReadmeGenerator):

    def get_tools(self) -> list[dict]:
        """Extract tools from PLAN_TOOLS + descriptions from TOOL_DESCRIPTIONS."""
        # Get tool names from __init__.py PLAN_TOOLS list
        init = self.plugin_dir / "__init__.py"
        text = init.read_text("utf-8")
        m = re.search(r"PLAN_TOOLS\s*=\s*\[(.*?)\]", text, re.DOTALL)
        names = []
        if m:
            names = re.findall(r'\(\s*"(plan_\w+)"', m.group(1))

        # Get descriptions from tools/descriptions.py (first line only)
        desc_file = self.plugin_dir / "tools" / "descriptions.py"
        schema_descs = {}
        if desc_file.exists():
            desc_text = desc_file.read_text("utf-8")
            for name in names:
                # Find the TOOL_DESCRIPTIONS entry for this name
                d_m = re.search(
                    rf'"{name}":\s*\((.*?)\),\s*"', desc_text, re.DOTALL
                )
                if d_m:
                    # Get first meaningful line
                    desc_raw = d_m.group(1)
                    first_line = re.sub(r'\s+', ' ', desc_raw).split("Parameters:")[0].strip('"\' \n')
                    # Clean up concatenated strings (" " -> space)
                    first_line = re.sub(r'"\s+"', ' ', first_line)
                    if first_line and first_line != name:
                        schema_descs[name] = first_line

        # Fallback: existing descriptions from README
        existing = read_existing_descriptions(self.readme_path)

        # Categorize
        CATEGORIES: dict[str, list[str]] = {
            "CRUD": ["plan_create", "plan_current", "plan_complete", "plan_verify",
            "plan_status", "plan_update", "plan_list", "plan_abort", "plan_delete",
            "plan_select", "plan_validate", "plan_duedate", "plan_archive", "plan_restore",
            "plan_template"],
        }

        tools = merge_descriptions(names, existing, schema_descs)
        for t in tools:
            for cat, members in CATEGORIES.items():
                if t["name"] in members:
                    t["category"] = cat
                    break
            else:
                # Check if it's a git tool
                if t["name"].startswith("plan_git"):
                    t["category"] = "Git"
                elif t["name"].startswith("plan_review") or "review" in t["name"]:
                    t["category"] = "Review"
                else:
                    t["category"] = "Advanced"

        return tools

    def get_profiles(self) -> list[dict]:
        return []

    def get_languages(self) -> list[str]:
        return []


if __name__ == "__main__":
    gen = PlanFollowReadmeGenerator(PLUGIN_DIR)
    sys.exit(gen.run())
