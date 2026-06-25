"""handlers_git."""
from __future__ import annotations

import logging

from .. import plan_core
from .._fmt import fmt_err, fmt_info, fmt_ok

logger = logging.getLogger("plan_follow")
def plan_git_branch_tool(args: dict, **kwargs) -> str:
    """Manage branches in configured repos.

    Parameters:
    - action (str, required): 'current', 'list', 'create', 'switch', 'delete'
    - name (str, optional): Branch name (for create/switch/delete)
    - start_point (str, optional): Start point for branch creation
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    action = args.get("action", "current")
    name = args.get("name", "")
    start_point = args.get("start_point", "")

    results = []
    for repo in repos:
        results.append(plan_core.git_branch(repo, action, name, start_point))
    return fmt_ok({"results": results})


def plan_git_init_tool(args: dict, **kwargs) -> str:
    """Initialize a Git repo in ~/.hermes/plans/ for plan versioning.

    Also creates an initial commit with all existing plans.
    This is optional — plans work fine without Git.

    Parameters:
    - commit_message (str, optional): Initial commit message (default: 'plan: initial')
    """

    git_dir = plan_core.PLANS_DIR / ".git"
    if git_dir.exists():
        return fmt_info("Git-Versionierung bereits aktiv in ~/.hermes/plans/")

    commit_msg = args.get("commit_message", "plan: initial commit")

    import subprocess
    try:
        # git init
        init = subprocess.run(
            ["git", "init"],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        if init.returncode != 0:
            return fmt_err(f"git init failed: {init.stderr[:200]}")

        # .gitignore for temp files
        gitignore = plan_core.PLANS_DIR / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*.tmp\n.session-logs/\n", encoding="utf-8")

        # git add + initial commit
        subprocess.run(
            ["git", "add", "--", "."],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=30,
        )

        return fmt_ok({
            "status": "initialized",
            "path": str(plan_core.PLANS_DIR),
            "commits": "1 initial commit with all existing plans",
            "message": "Git-Versionierung aktiviert. Pläne werden jetzt automatisch versioniert.",
        })
    except Exception as e:
        return fmt_err(f"Git init failed: {e}")


def plan_git_push_tool(args: dict, **kwargs) -> str:
    """Git-push to remote for the task's repos.

    Parameters:
    - remote (str, optional): Remote name (default: origin)
    - branch (str, optional): Branch to push (default: current branch)
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    remote = args.get("remote", "origin")
    branch = args.get("branch", None)

    result = plan_core.auto_push(repos, remote, branch)
    return fmt_ok(result)


def plan_git_stash_tool(args: dict, **kwargs) -> str:
    """Stash or unstash changes in configured repos.

    Parameters:
    - action (str, required): 'push' (stash), 'pop' (restore), 'list' (show)
    - message (str, optional): Stash message (push only)
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    action = args.get("action", "push")
    message = args.get("message", "")

    results = []
    for repo in repos:
        results.append(plan_core.git_stash(repo, action, message))
    return fmt_ok({"results": results})


def plan_git_status_tool(args: dict, **kwargs) -> str:
    """Show git status for all configured repos.

    Returns branch, dirty flag, ahead/behind, last commit per repo.
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    results = []
    for repo in repos:
        results.append(plan_core.get_git_status(repo))

    return fmt_ok({"status": "ok", "repos": results})


def plan_git_sync_tool(args: dict, **kwargs) -> str:
    """Pull → add → commit → push in one step for all configured repos.

    Parameters:
    - remote (str, optional): Remote name (default: origin)
    - branch (str, optional): Branch to push (default: current branch)
    - push (bool, optional): Whether to push after commit (default: true)
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    task_id = plan.get("current_task", "unknown")
    task = plan.get("tasks", {}).get(task_id, {})
    files = task.get("files", []) if task else []

    remote = args.get("remote", "origin")
    branch = args.get("branch", None)
    push = args.get("push", True)

    results = []
    for repo in repos:
        results.append(plan_core.git_sync(repo, task_id, files, remote, branch, push))

    return fmt_ok({"status": "ok", "results": results})


def plan_git_tag_tool(args: dict, **kwargs) -> str:
    """Create or manage git tags in configured repos.

    Parameters:
    - action (str, required): 'create', 'list', 'delete'
    - tag_name (str, optional): Tag name (required for create/delete)
    - message (str, optional): Tag annotation message (create only)
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    action = args.get("action", "create")
    tag_name = args.get("tag_name", "")
    message = args.get("message", "")

    results = []
    for repo in repos:
        results.append(plan_core.git_tag(repo, tag_name, message, action))
    return fmt_ok({"results": results})


def plan_pr_create_tool(args: dict, **kwargs) -> str:
    """Create a Pull Request via Forgejo API for all configured repos.

    Parameters:
    - title (str, required): PR title
    - body (str, optional): PR description
    - head (str, optional): Source branch (default: current branch)
    - base (str, optional): Target branch (default: main)
    - owner (str, optional): Repo owner (default: from git remote)
    - repo_name (str, optional): Repo name (default: from git remote)
    """

    plan = plan_core._get_active_plan()
    if not plan:
        return fmt_err("No active plan.")

    repos = plan_core._get_repos(plan)
    if not repos:
        return fmt_err("No repos configured in plan.")

    title = args.get("title", "")
    if not title:
        return fmt_err("title is required for PR creation.")
    body = args.get("body", "")
    head = args.get("head", None)
    base = args.get("base", "main")

    import os as _os
    token = None
    for env_var in ["BOT_FORGEJO_TOKEN", "FORGEJO_TOKEN", "GITEA_TOKEN"]:
        val = _os.environ.get(env_var)
        if val:
            token = val
            break
    if not token:
        return fmt_err(
            "No Forgejo token found. Set BOT_FORGEJO_TOKEN, FORGEJO_TOKEN, "
            "or GITEA_TOKEN environment variable."
        )

    import json as _json
    import re
    import subprocess
    import urllib.request as _ur
    results = []
    for repo in repos:
        if not _os.path.isdir(_os.path.join(repo, ".git")):
            results.append({"status": "skipped", "repo": repo,
                            "message": "No .git in repo."})
            continue

        try:
            remote_url = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo, capture_output=True, text=True, timeout=10,
            ).stdout.strip()

            owner = args.get("owner", "")
            repo_name = args.get("repo_name", "")
            if not owner or not repo_name:
                m = re.search(r'[:/]([^/]+)/([^/]+?)(?:\.git)?$', remote_url)
                if m:
                    owner = owner or m.group(1)
                    repo_name = repo_name or m.group(2).replace(".git", "")

            if not owner or not repo_name:
                results.append({"status": "failed", "repo": repo,
                                "message": "Could not detect owner/repo."})
                continue

            if not head:
                br = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=repo, capture_output=True, text=True, timeout=10,
                )
                head = br.stdout.strip()

            api_base = _os.environ.get("FORGEJO_API_BASE", "https://git.agentiker.de")
            api_url = f"{api_base}/api/v1/repos/{owner}/{repo_name}/pulls"

            payload = _json.dumps({
                "title": title,
                "body": body or "",
                "head": head,
                "base": base,
            }).encode()

            req = _ur.Request(
                api_url, data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"token {token}",
                },
            )
            resp = _ur.urlopen(req, timeout=30)
            response_data = _json.loads(resp.read())

            results.append({
                "status": "created",
                "repo": repo,
                "pr_url": response_data.get("html_url", ""),
                "pr_number": response_data.get("number", ""),
            })
        except Exception as e:
            results.append({"status": "error", "repo": repo,
                            "message": str(e)[:200]})

    return fmt_ok({"results": results})
