"""Zoho MCP console regions and URL helpers. The URL is the user's and may embed a credential, so display it only
through `mask_url`. (Harness entries live in harnesses.py; the URL itself is kept in config.py.)"""
from __future__ import annotations

from urllib.parse import urlparse

# Official Zoho MCP console, per data centre. This is where the user creates their MCP server, adds the Zoho
# Projects tools and copies the MCP URL from the "Connect" tab. The default matches the portal in use (India).
REGIONS = {
    "in": "https://mcp.zoho.in/",
    "com": "https://mcp.zoho.com/",
    "eu": "https://mcp.zoho.eu/",
    "com.au": "https://mcp.zoho.com.au/",
    "jp": "https://mcp.zoho.jp/",
}
DEFAULT_REGION = "in"
# Tools the skills call; add these (Zoho Projects service) when creating the server in the console.
REQUIRED_TOOLS = ["get_portals", "get_projects_list", "get_tasks_by_project", "get_task_details",
                  "create_a_task", "update_a_task"]

class McpError(Exception):
    pass


def console_url(region: str) -> str:
    if region not in REGIONS:
        raise McpError(f"unknown region {region!r}; choose from: {', '.join(REGIONS)}")
    return REGIONS[region]


def validate_url(url: str) -> str:
    url = url.strip()
    p = urlparse(url)
    local = p.hostname in ("localhost", "127.0.0.1", "::1")
    if p.scheme not in ("https", "http") or not p.netloc or (p.scheme == "http" and not local):
        raise McpError("MCP URL must be https:// (http:// only for localhost)")
    return url


def mask_url(url: str) -> str:
    """Show scheme://host/... only, since Zoho MCP URLs can carry a secret key in the path or query."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/…" if (p.path.strip("/") or p.query) else f"{p.scheme}://{p.netloc}"
