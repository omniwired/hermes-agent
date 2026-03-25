#!/usr/bin/env python3
"""
Master Agent Tools -- project and worker management via the master agent.

Exposes project lifecycle as a tool the master agent's model can call:
  - create: bootstrap a new project with its own workspace + persistent worker agent
  - list: show all registered projects and their workspaces
  - status: check worker health and queue depth for a project
  - remove: stop and unregister a project

The tool reads the current MasterAIAgent from thread-local storage set at
agent initialization time.
"""

import json
from typing import Any

from tools.registry import registry


def check_master_tools_requirements() -> bool:
    """Master tools require an active MasterAIAgent in thread-local storage."""
    from run_agent import get_master_agent
    return get_master_agent() is not None


def manage_project(
    action: str,
    project: str | None = None,
    workspace: str | None = None,
    max_workers: int = 1,
) -> str:
    """
    Manage project worker agents and their workspaces.

    Actions:
      create: Register a new project workspace and spawn a persistent worker agent.
              The agent will have its own isolated memory at
              $HERMES_HOME/workspaces/{workspace}/memories/.
              The master can then delegate tasks to this project by name.

      list: Return all registered projects with their workspaces and agent status.

      status: Return the current state of a specific project worker, including
              whether it has a running task and how many tasks are queued.

      remove: Stop the project's worker agent, shut down its thread pool,
              and remove it from the registry. The project's memory is NOT deleted.

    Args:
        action: The management action to perform ("create", "list", "status", "remove").
        project: Project name (required for create, status, remove).
        workspace: Workspace name for create. Defaults to the project name if not provided.
        max_workers: Max concurrent tasks per worker agent (create only, default 1).
                     Increase at your own risk — AIAgent.run_conversation is not
                     verified thread-safe for concurrent calls on a single instance.
    """
    from run_agent import get_master_agent, AIAgent

    master = get_master_agent()
    if master is None:
        return json.dumps({
            "success": False,
            "error": "No MasterAIAgent found in context. "
                     "manage_project must be called from within a MasterAIAgent conversation.",
        })

    effective_workspace = workspace or project

    # ---- CREATE ----
    if action == "create":
        if not project:
            return json.dumps({"success": False, "error": "project is required for create."})

        existing = master.get_agent(project)
        if existing is not None:
            return json.dumps({
                "success": False,
                "error": f"Project '{project}' already exists. "
                         f"Use action='remove' first, or use action='status' to check its state.",
            })

        master.register_workspace(project, effective_workspace)
        worker = AIAgent(workspace=effective_workspace)
        master.register_agent(project, worker, max_workers=max_workers)

        return json.dumps({
            "success": True,
            "project": project,
            "workspace": effective_workspace,
            "memory_dir": str(worker._memory_dir),
            "max_workers": max_workers,
            "message": (
                f"Project '{project}' created with workspace '{effective_workspace}'. "
                f"Memory: {worker._memory_dir}. "
                f"Delegate tasks with master.delegate_task(goal='...', project='{project}')."
            ),
        })

    # ---- LIST ----
    if action == "list":
        projects = master.list_projects()
        agents = master.list_agents()

        result = {"success": True, "projects": []}
        for name in projects:
            ws = projects[name]
            agent = agents.get(name)
            pool = master._project_pools.get(name)

            queued = 0
            if pool:
                try:
                    queued = len(pool._work_queue.queue)
                except Exception:
                    queued = -1

            is_busy = False
            if agent:
                try:
                    is_busy = getattr(agent, '_executing_tools', False)
                except Exception:
                    is_busy = None

            result["projects"].append({
                "project": name,
                "workspace": ws,
                "has_agent": agent is not None,
                "is_busy": is_busy,
                "queued_tasks": queued,
                "memory_dir": str(agent._memory_dir) if agent else None,
            })

        if not result["projects"]:
            result["message"] = "No projects registered. Use action='create' to bootstrap one."
        return json.dumps(result, ensure_ascii=False)

    # ---- STATUS ----
    if action == "status":
        if not project:
            return json.dumps({"success": False, "error": "project is required for status."})

        ws = master.get_workspace(project)
        agent = master.get_agent(project)
        pool = master._project_pools.get(project)

        if ws is None and agent is None:
            return json.dumps({
                "success": False,
                "error": f"Project '{project}' not found. Use action='list' to see all projects.",
            })

        queued = 0
        if pool:
            try:
                queued = len(pool._work_queue.queue)
            except Exception:
                queued = -1

        is_busy = False
        if agent:
            try:
                is_busy = getattr(agent, '_executing_tools', False)
            except Exception:
                is_busy = None

        return json.dumps({
            "success": True,
            "project": project,
            "workspace": ws,
            "has_agent": agent is not None,
            "is_busy": is_busy,
            "queued_tasks": queued,
            "pool_max_workers": pool._max_workers if pool else None,
            "memory_dir": str(agent._memory_dir) if agent else None,
        }, ensure_ascii=False)

    # ---- REMOVE ----
    if action == "remove":
        if not project:
            return json.dumps({"success": False, "error": "project is required for remove."})

        ws = master.get_workspace(project)
        agent = master.get_agent(project)

        if ws is None and agent is None:
            return json.dumps({
                "success": False,
                "error": f"Project '{project}' not found.",
            })

        pool = master._project_pools.pop(project, None)
        if pool:
            pool.shutdown(wait=False)

        master.unregister_agent(project)
        master._project_workspace_registry.pop(project, None)

        return json.dumps({
            "success": True,
            "project": project,
            "workspace": ws,
            "message": (
                f"Project '{project}' removed. "
                f"Its memory at $HERMES_HOME/workspaces/{ws or project}/memories/ is preserved. "
                f"Use action='create' to re-bootstrap."
            ),
        })

    return json.dumps({
        "success": False,
        "error": f"Unknown action '{action}'. Use: create, list, status, remove.",
    })


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

MANAGE_PROJECT_SCHEMA = {
    "name": "manage_project",
    "description": (
        "Create, list, inspect, and remove project worker agents. "
        "Use this to build your team of specialized agents.\n\n"
        "Typical workflow:\n"
        "1. 'create' a project for each codebase or workstream you want a dedicated agent to handle.\n"
        "2. 'list' to see your full team at a glance.\n"
        "3. 'status' to check if a project worker is busy or has queued tasks.\n"
        "4. 'remove' to tear down a project when done (memory is preserved).\n\n"
        "After creating a project, delegate tasks to it using delegate_task "
        "with the project parameter (handled by the master agent's routing).\n"
        "Each project worker has its own isolated memory at "
        "$HERMES_HOME/workspaces/{workspace}/memories/."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "status", "remove"],
                "description": (
                    "The management action to perform:\n"
                    "  create — bootstrap a new project with its own workspace and worker agent\n"
                    "  list — show all registered projects, their workspaces, and busy status\n"
                    "  status — inspect a specific project's worker (busy? queued tasks?)\n"
                    "  remove — stop and unregister a project (memory preserved)"
                ),
            },
            "project": {
                "type": "string",
                "description": (
                    "The project name. Required for create, status, and remove. "
                    "Example: 'hermes', 'checkout-api', 'data-pipeline'"
                ),
            },
            "workspace": {
                "type": "string",
                "description": (
                    "The workspace name for the project's isolated memory. "
                    "Maps to $HERMES_HOME/workspaces/{workspace}/memories/. "
                    "Defaults to the project name if not specified."
                ),
            },
            "max_workers": {
                "type": "integer",
                "description": (
                    "Max concurrent tasks the project's worker agent can handle. "
                    "Default: 1 (tasks are queued sequentially). "
                    "Increase to allow parallel task handling within a project, "
                    "at your own risk — AIAgent.run_conversation is not verified "
                    "thread-safe for concurrent calls on a single instance."
                ),
                "default": 1,
            },
        },
        "required": ["action"],
    },
}


# --- Registry ---
registry.register(
    name="manage_project",
    toolset="delegation",
    schema=MANAGE_PROJECT_SCHEMA,
    handler=lambda args, **kw: manage_project(
        action=args["action"],
        project=args.get("project"),
        workspace=args.get("workspace"),
        max_workers=args.get("max_workers", 1),
    ),
    check_fn=check_master_tools_requirements,
    emoji="🏢",
)
