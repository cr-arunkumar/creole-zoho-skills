"""Stand-in for the Zoho Projects MCP server: read tool + write tools that record every call to $CALLS_FILE."""
import json
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fake-zoho")


def _record(tool, args):
    with open(os.environ["CALLS_FILE"], "a") as f:
        f.write(json.dumps({"tool": tool, "args": args}) + "\n")


@mcp.tool()
def get_portals() -> str:
    """List portals."""
    _record("get_portals", {})
    return json.dumps([{"org_name": "Creole Studios", "portal_name": "creolestudiosdotcom1"}])


@mcp.tool()
def create_a_task(name: str, description: str = "") -> str:
    """Create a task."""
    _record("create_a_task", {"name": name, "description": description})
    return "created 42"


@mcp.tool()
def update_a_task(task_id: str, status: str = "") -> str:
    """Update a task."""
    _record("update_a_task", {"task_id": task_id, "status": status})
    return "updated"


@mcp.tool()
def create_task_comment(task_id: str, content: str, project_id: str = "") -> str:
    """Add a comment to a task."""
    _record("create_task_comment", {"task_id": task_id, "content": content, "project_id": project_id})
    return "commented"


if __name__ == "__main__":
    mcp.run("stdio")
