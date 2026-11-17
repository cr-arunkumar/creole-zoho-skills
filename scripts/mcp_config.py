"""Register the Zoho Projects MCP server with each harness. Standard library only.

Writes only the harness's own config (never this repo). The URL is the user's; it may embed a key, so callers
should display it through `mask_url`. Existing config is preserved and backed up to `<file>.bak` before the
first change; re-running is idempotent.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

SERVER_NAME = "zoho-projects"
TOML_START = "# creole-zoho-skills:start"
TOML_END = "# creole-zoho-skills:end"

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

Runner = Callable[[list, Optional[Path]], "subprocess.CompletedProcess"]


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


def default_runner(cmd: list, cwd: Optional[Path] = None) -> "subprocess.CompletedProcess":
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None, timeout=60)


def _backup(path: Path) -> None:
    bak = path.with_name(path.name + ".bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)


def upsert_json_server(path: Path, entry: dict) -> str:
    """Add mcpServers.<SERVER_NAME> = entry. Returns 'added' | 'updated' | 'unchanged'."""
    data: dict = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise McpError(f"{path} is not valid JSON ({e}); fix it or add the server manually") from e
        if not isinstance(data, dict):
            raise McpError(f"{path} must contain a JSON object")
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise McpError(f"{path}: mcpServers must be an object")
    if servers.get(SERVER_NAME) == entry:
        return "unchanged"
    status = "updated" if SERVER_NAME in servers else "added"
    servers[SERVER_NAME] = entry
    _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return status


def upsert_toml_block(path: Path, url: str) -> str:
    """Manage a marked [mcp_servers.zoho-projects] block in config.toml, leaving the rest untouched."""
    block = f'{TOML_START}\n[mcp_servers.{SERVER_NAME}]\nurl = {json.dumps(url)}\n{TOML_END}\n'
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pat = re.compile(re.escape(TOML_START) + r".*?" + re.escape(TOML_END) + r"\n?", re.S)
    if pat.search(text):
        new = pat.sub(lambda _: block, text)
    elif re.search(rf"^\[mcp_servers\.{re.escape(SERVER_NAME)}\]", text, re.M):
        raise McpError(f"{path} already defines [mcp_servers.{SERVER_NAME}] by hand; edit it manually")
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    if new == text:
        return "unchanged"
    _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return "updated" if text and TOML_START in text else "added"


def snippet(harness: str, url: str) -> str:
    """Copy-paste fallback shown when auto-registration is skipped or fails."""
    if harness == "claude":
        return f"claude mcp add --transport http {SERVER_NAME} {url}"
    if harness == "cursor":
        return json.dumps({"mcpServers": {SERVER_NAME: {"url": url}}}, indent=2)
    if harness == "antigravity":
        return json.dumps({"mcpServers": {SERVER_NAME: {"httpUrl": url}}}, indent=2)
    return f'[mcp_servers.{SERVER_NAME}]\nurl = "{url}"'


def config_path(harness: str, home: Path, project: Optional[Path]) -> Optional[Path]:
    if harness == "cursor":
        return (project or home) / ".cursor" / "mcp.json"
    if harness == "antigravity":
        return (project or home) / ".gemini" / "settings.json"
    if harness == "codex":
        return home / ".codex" / "config.toml"
    return None


def register(harness: str, url: str, *, home: Path, project: Optional[Path] = None,
             dry_run: bool = False, runner: Runner = default_runner) -> str:
    """Register the server for one harness; returns a one-line human result. Raises McpError on failure."""
    url = validate_url(url)
    if harness == "claude":
        scope = "project" if project else "user"
        if dry_run:
            return f"would run: claude mcp add --scope {scope} {SERVER_NAME}"
        if shutil.which("claude") is None and runner is default_runner:
            raise McpError("`claude` CLI not found on PATH; run: " + snippet("claude", "<your-mcp-url>"))
        got = runner(["claude", "mcp", "get", SERVER_NAME], project)
        if got.returncode == 0:
            return "already registered with claude"
        res = runner(["claude", "mcp", "add", "--scope", scope, "--transport", "http", SERVER_NAME, url], project)
        if res.returncode != 0:
            raise McpError((res.stderr or res.stdout or "claude mcp add failed").strip().splitlines()[-1])
        return f"registered with claude ({scope} scope); authenticate with /mcp"
    path = config_path(harness, home, project)
    if path is None:
        raise McpError(f"unknown harness {harness!r}")
    if dry_run:
        return f"would write {path}"
    if harness == "codex":
        status = upsert_toml_block(path, url)
    else:
        key = "httpUrl" if harness == "antigravity" else "url"
        status = upsert_json_server(path, {key: url})
    return f"{status}: {path}"
