"""mcp_server.py — MCP Server für plan_follow Plugin.

Ermöglicht externen Tools (Cursor, Claude Code, etc.) Zugriff auf
plan_follow Pläne via Model Context Protocol (MCP).

Usage:
    python3 -m plan_follow.mcp_server

    # Oder via systemd: systemctl --user start plan-mcp.service

Tools:
    - list_plans: Alle Pläne auflisten
    - get_plan: Details eines Plans abrufen
    - get_active_plan: Aktiven Plan mit aktuellem Task abrufen
    - create_plan_from_mcp: Neuen Plan erstellen (minimal)
    - set_plan_status: Task-Status setzen
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s [%(levelname)s] %(message)s")
logger = logging.getLogger("plan-mcp")


_plan_core_cache = None


def _get_core():
    """Lazy import plan_core to avoid circular imports on plugin load.

    Cached after first call — sys.path.insert nur einmalig.
    """
    global _plan_core_cache
    if _plan_core_cache is not None:
        return _plan_core_cache
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import plan_core  # noqa: F811
    _plan_core_cache = plan_core
    return plan_core


def _get_api_token() -> str:
    """Get API token for MCP HTTP auth from env var."""
    import os
    token = os.environ.get("PLAN_MCP_API_TOKEN", "")
    if not token:
        logger.warning("plan-mcp: PLAN_MCP_API_TOKEN not set — HTTP auth disabled")
    return token


# ─── MCP Tool Implementations ─────────────────────────────────────────────────


def list_plans(include_archived: bool = False) -> str:
    """List all plans.

    Args:
        include_archived: Whether to include archived plans.

    Returns:
        JSON string with plan list.
    """
    try:
        pc = _get_core()
        plans = pc.list_plans(include_archived=include_archived)
        return json.dumps({"success": True, "plans": plans}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def get_plan(plan_id: str) -> str:
    """Get a plan by ID.

    Args:
        plan_id: The plan ID to retrieve.

    Returns:
        JSON string with plan details.
    """
    try:
        pc = _get_core()
        plan = pc._load_plan(plan_id)
        if not plan:
            return json.dumps({"success": False, "error": f"Plan '{plan_id}' not found"})
        # Sanitize: remove full task bodies for token efficiency
        summary = {
            "plan_id": plan["plan_id"],
            "goal": plan.get("goal", ""),
            "created": plan.get("created", ""),
            "current_task": plan.get("current_task"),
            "task_count": len(plan.get("tasks", {})),
            "status_summary": _summarize_status(plan.get("tasks", {})),
        }
        return json.dumps({"success": True, "plan": summary}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def get_active_plan() -> str:
    """Get the currently active plan with current task.

    Returns:
        JSON string with active plan details and current task info.
    """
    try:
        pc = _get_core()
        plan = pc._get_active_plan()
        if not plan:
            return json.dumps({"success": False, "error": "No active plan"})
        current = pc.get_current_task()
        result = {
            "plan_id": plan["plan_id"],
            "goal": plan.get("goal", ""),
            "current_task": current,
            "task_count": len(plan.get("tasks", {})),
            "status_summary": _summarize_status(plan.get("tasks", {})),
        }
        return json.dumps({"success": True, "plan": result}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def create_plan_from_mcp(goal: str, template: str = "fix", tasks: list = None) -> str:
    """Create a new plan via MCP.

    Args:
        goal: The plan goal.
        template: Template name (default: fix).
        tasks: Optional custom task list (for multi template).

    Returns:
        JSON string with created plan info.
    """
    try:
        from .plan_tools import plan_create_tool
        args = {"goal": goal, "template": template}
        if tasks:
            args["params"] = {"tasks": tasks}
            args["template"] = "multi"
        result = plan_create_tool(args)
        return json.dumps({"success": True, "result": str(result)}, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def set_plan_status(task_id: str, status: str, plan_id: str = "") -> str:
    """Set a task's status.

    Args:
        task_id: Task ID.
        status: New status (completed, aborted, pending).
        plan_id: Plan ID (defaults to active plan).

    Returns:
        JSON string with result.
    """
    try:
        pc = _get_core()
        plan = pc._load_plan(plan_id) if plan_id else pc._get_active_plan()
        if not plan:
            return json.dumps({"success": False, "error": "Plan not found"})
        if task_id not in plan.get("tasks", {}):
            return json.dumps({"success": False, "error": f"Task '{task_id}' not found in plan"})

        if status == "completed":
            result = pc.complete_task(task_id)
            return json.dumps({"success": True, "result": str(result)}, indent=2)
        elif status == "aborted":
            plan["tasks"][task_id]["status"] = "aborted"
            pc._save_plan(plan)
            return json.dumps({"success": True, "result": f"Task '{task_id}' aborted"})
        else:
            plan["tasks"][task_id]["status"] = status
            pc._save_plan(plan)
            return json.dumps({"success": True, "result": f"Task '{task_id}' set to '{status}'"})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def _summarize_status(tasks: dict) -> dict:
    """Summarize task status counts."""
    counts = {}
    for tid, t in tasks.items():
        s = t.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    return counts


# ─── CLI / MCP Entry Point ────────────────────────────────────────────────────
# Der Server kann entweder via CLI (stdio MCP) oder als HTTP-Server laufen.


def run_stdio():
    """Run MCP server via stdio transport."""
    import sys

    logger.info("plan-mcp: Starting stdio MCP server...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            request = json.loads(line)
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id", 0)

            if method == "list_tools":
                response = {
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "list_plans",
                                "description": "List all plans",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "include_archived": {"type": "boolean", "default": False}
                                    }
                                }
                            },
                            {
                                "name": "get_plan",
                                "description": "Get plan details by ID",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "plan_id": {"type": "string"}
                                    },
                                    "required": ["plan_id"]
                                }
                            },
                            {
                                "name": "get_active_plan",
                                "description": "Get active plan with current task",
                                "inputSchema": {"type": "object", "properties": {}}
                            },
                            {
                                "name": "create_plan_from_mcp",
                                "description": "Create a new plan",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "goal": {"type": "string"},
                                        "template": {"type": "string", "default": "fix"},
                                        "tasks": {"type": "array", "items": {"type": "object"}}
                                    },
                                    "required": ["goal"]
                                }
                            },
                            {
                                "name": "set_plan_status",
                                "description": "Set a task's status",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "task_id": {"type": "string"},
                                        "status": {"type": "string", "enum": ["completed", "aborted", "pending"]},
                                        "plan_id": {"type": "string"}
                                    },
                                    "required": ["task_id", "status"]
                                }
                            },
                        ]
                    }
                }
            elif method == "call_tool":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                if tool_name == "list_plans":
                    result_text = list_plans(**tool_args)
                elif tool_name == "get_plan":
                    result_text = get_plan(**tool_args)
                elif tool_name == "get_active_plan":
                    result_text = get_active_plan()
                elif tool_name == "create_plan_from_mcp":
                    result_text = create_plan_from_mcp(**tool_args)
                elif tool_name == "set_plan_status":
                    result_text = set_plan_status(**tool_args)
                else:
                    result_text = json.dumps({"success": False, "error": f"Unknown tool: {tool_name}"})
                response = {
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}]
                    }
                }
            elif method == "initialize":
                response = {
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "plan-follow-mcp",
                            "version": "0.1.0"
                        }
                    }
                }
            else:
                response = {"id": req_id, "result": {}}

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError:
            continue
        except EOFError:
            break
        except KeyboardInterrupt:
            break

    logger.info("plan-mcp: Server stopped.")


def run_http(host: str = "127.0.0.1", port: int = 8123):
    """Run MCP server via HTTP transport (JSON-RPC over HTTP).

    Args:
        host: Bind address.
        port: Port number.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class MCPHandler(BaseHTTPRequestHandler):
        def _check_auth(self) -> bool:
            """Check Authorization header against PLAN_MCP_API_TOKEN."""
            token = _get_api_token()
            if not token:
                return True  # no token configured = no auth required
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {token}" or auth == f"token {token}":
                return True
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())
            return False

        def do_POST(self):
            if not self._check_auth():
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                request = json.loads(body)
                method = request.get("method", "")
                params = request.get("params", {})
                req_id = request.get("id", 0)

                if method == "list_tools":
                    # Return tool list
                    result = {"tools": [
                        {"name": "list_plans", "description": "List all plans",
                         "inputSchema": {"type": "object", "properties": {}}},
                        {"name": "get_plan", "description": "Get plan details",
                         "inputSchema": {"type": "object", "properties": {"plan_id": {"type": "string"}},
                          "required": ["plan_id"]}},
                        {"name": "get_active_plan", "description": "Get active plan",
                         "inputSchema": {"type": "object", "properties": {}}},
                    ]}
                    response = {"id": req_id, "result": result}
                elif method == "call_tool":
                    tool_name = params.get("name", "")
                    tool_args = params.get("arguments", {})
                    if tool_name == "list_plans":
                        text = list_plans(**tool_args)
                    elif tool_name == "get_plan":
                        text = get_plan(**tool_args)
                    elif tool_name == "get_active_plan":
                        text = get_active_plan()
                    else:
                        text = json.dumps({"error": f"Unknown: {tool_name}"})
                    response = {"id": req_id, "result": {"content": [{"type": "text", "text": text}]}}
                else:
                    response = {"id": req_id, "result": {}}

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                logger.error("plan-mcp: request failed: %s", e)
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Internal Server Error"}).encode())

        def log_message(self, format, *args):
            logger.debug("plan-mcp: HTTP request: %s %s", format, args)

    server = HTTPServer((host, port), MCPHandler)
    logger.info("plan-mcp: HTTP server on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("plan-mcp: HTTP server stopped.")
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="plan_follow MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="Transport protocol (default: stdio)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address")
    parser.add_argument("--port", type=int, default=8123, help="HTTP port")
    args = parser.parse_args()

    if args.transport == "http":
        run_http(args.host, args.port)
    else:
        run_stdio()
