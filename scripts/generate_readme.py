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
from generate_readme_base import ReadmeGenerator  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# Tool categories based on __init__.py PLAN_TOOLS structure
TOOL_CATEGORIES = {
    "plan_lifecycle": "Plan Lifecycle — Create & Complete",
    "plan_status": "Status & Review — Track & Verify",
    "plan_management": "Plan Management — List, Select, Archive",
    "plan_validation": "Validation & Deadlines",
    "plan_roadmap": "Roadmap & Decomposition",
    "plan_git": "Git Integration — Branch, Commit, PR",
    "plan_cross_session": "Cross-Session — Locks, Notifications",
    "plan_time": "Time Tracking & Simulation",
}

TOOL_CATEGORY_MAP = {
    # Lifecycle
    "plan_create": "plan_lifecycle",
    "plan_current": "plan_lifecycle",
    "plan_complete": "plan_lifecycle",
    "plan_abort": "plan_lifecycle",
    "plan_todo": "plan_lifecycle",
    # Status & Review
    "plan_status": "plan_status",
    "plan_verify": "plan_status",
    "plan_update": "plan_status",
    "plan_review": "plan_status",
    "plan_auto_review": "plan_status",
    "plan_review_profiles": "plan_status",
    "plan_review_save_result": "plan_status",
    # Management
    "plan_list": "plan_management",
    "plan_select": "plan_management",
    "plan_delete": "plan_management",
    "plan_archive": "plan_management",
    "plan_restore": "plan_management",
    "plan_template": "plan_management",
    "plan_suggest": "plan_management",
    # Validation
    "plan_validate": "plan_validation",
    "plan_duedate": "plan_validation",
    # Roadmap
    "plan_roadmap": "plan_roadmap",
    "plan_decompose": "plan_roadmap",
    "plan_sync": "plan_roadmap",
    # Git
    "plan_git_init": "plan_git",
    "plan_git_push": "plan_git",
    "plan_git_status": "plan_git",
    "plan_git_sync": "plan_git",
    "plan_git_stash": "plan_git",
    "plan_git_branch": "plan_git",
    "plan_git_tag": "plan_git",
    "plan_pr_create": "plan_git",
    "plan_history": "plan_git",
    # Cross-Session
    "plan_session": "plan_cross_session",
    "plan_lock": "plan_cross_session",
    "plan_notify": "plan_cross_session",
    "plan_coord_cleanup": "plan_cross_session",
    # Time & Sim
    "plan_time": "plan_time",
    "plan_simulate": "plan_time",
}


class PlanFollowReadmeGenerator(ReadmeGenerator):

    def get_tools(self) -> list[dict]:
        """Extract tools from __init__.py PLAN_TOOLS + descriptions."""
        tools = []

        # Read descriptions from the separate descriptions module
        descs = self._read_descriptions()

        # Extract tool names from __init__.py PLAN_TOOLS list
        init_file = self.plugin_dir / "__init__.py"
        if init_file.exists():
            text = init_file.read_text("utf-8")
            # Find all tool names in the PLAN_TOOLS list (not imports)
            # Match only "plan_xxx" inside the PLAN_TOOLS = [...] definition
            plan_tools_match = re.search(r'PLAN_TOOLS\s*=\s*\[(.*?)\]', text, re.DOTALL)
            tool_names = re.findall(r'"plan_\w+"', plan_tools_match.group(1) if plan_tools_match else "")

            for name in sorted(set(tool_names)):
                name = name.strip('"')
                cat_key = TOOL_CATEGORY_MAP.get(name, "plan_lifecycle")
                category = TOOL_CATEGORIES.get(cat_key, "Other")
                desc = descs.get(name, "—")
                # Shorten descriptions: first sentence only, strip "Parameters:..."
                if "Parameters:" in desc:
                    desc = desc.split("Parameters:")[0].strip()
                if desc.endswith("."):
                    desc = desc
                else:
                    # Take first sentence
                    first_sent = desc.split(". ")[0] if ". " in desc else desc.split("\n")[0]
                    desc = (first_sent + ".") if not first_sent.endswith(".") else first_sent
                if len(desc) > 150:
                    desc = desc[:147] + "..."
                tools.append({"name": name, "description": desc, "category": category})

        return tools

    def _read_descriptions(self) -> dict[str, str]:
        """Read descriptions from tools/descriptions.py."""
        import ast

        descs_path = self.plugin_dir / "tools" / "descriptions.py"
        if not descs_path.exists():
            return {}

        # Try to import the descriptions module directly
        try:
            sys.path.insert(0, str(self.plugin_dir.parent))
            from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS
            result = {}
            for k, v in TOOL_DESCRIPTIONS.items():
                result[k] = v if isinstance(v, str) else str(v)
            return result
        except Exception:
            # Fallback: parse via AST
            try:
                tree = ast.parse(descs_path.read_text("utf-8"))
                result = {}
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign) and hasattr(node.targets[0], 'id') and node.targets[0].id == 'TOOL_DESCRIPTIONS':
                        if isinstance(node.value, ast.Dict):
                            for k, v in zip(node.value.keys, node.value.values):
                                if isinstance(k, ast.Constant) and isinstance(v, (ast.Constant, ast.JoinedStr)):
                                    result[k.value] = ast.literal_eval(v) if isinstance(v, ast.Constant) else str(v)
                return result
            except Exception:
                return {}

    def get_profiles(self) -> list[dict]:
        """Return review profiles."""
        return [
            {"name": "none", "tool_count": "—", "description": "Kein Review (Default)"},
            {"name": "unit-test", "tool_count": "—", "description": "Tests + Coverage + Edge-Cases"},
            {"name": "api-route", "tool_count": "—", "description": "API-Routen: Validierung + Error-Handling + Security"},
            {"name": "ui-component", "tool_count": "—", "description": "React/UI: A11y + SSR + State + Forms + Mobile"},
            {"name": "security", "tool_count": "—", "description": "Secrets + Injection + XSS + Auth"},
            {"name": "full", "tool_count": "—", "description": "Alle Checks kombiniert"},
        ]

    def get_languages(self) -> list[str]:
        return []


if __name__ == "__main__":
    gen = PlanFollowReadmeGenerator(PLUGIN_DIR)
    sys.exit(gen.run())
