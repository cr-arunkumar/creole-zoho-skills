"""`zoho-skills doctor`: read-only health checks. Never prints the MCP URL or any key; upstream is probed with tools/list only."""
from __future__ import annotations

import asyncio
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config, mcp_config, packs, upstream

UPSTREAM_TIMEOUT = 15
_MARKS = {"ok": "✔", "warn": "!", "fail": "✖", "skip": "–"}
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I)


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    detail: str = ""
    fix: str = ""


def _scrub(text: str) -> str:
    """Remove the configured URL, key-looking query values and any other URL from text destined for output."""
    return _URL_RE.sub("<url>", config.redact(str(text)))


def _check_python() -> Check:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 9):
        return Check("python", "ok", ver)
    return Check("python", "fail", f"{ver} is too old (need >= 3.9)", "install Python 3.9 or newer")


def _check_uv(runner) -> Check:
    path = shutil.which("uv")
    if not path:
        return Check("uv", "warn", "not found on PATH", "install uv: https://docs.astral.sh/uv/ (lets harnesses run zoho-skills via uvx)")
    detail = "found"
    if runner:
        try:
            out = runner(["uv", "--version"])
            detail = (getattr(out, "stdout", out) or "found").strip().splitlines()[0]
        except Exception:
            pass
    return Check("uv", "ok", detail)


def _check_config() -> list:
    path = config.config_path()
    checks = []
    if not path.exists():
        checks.append(Check("config file", "warn", f"{path} not found", "zoho-skills onboard"))
    else:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            checks.append(Check("config file", "warn", f"{path} has mode {mode:03o}; it can hold a credential",
                                f"chmod 600 {path}"))
        else:
            checks.append(Check("config file", "ok", f"{path} (mode {mode:03o})"))
    url = config.get_url()
    if not url:
        checks.append(Check("MCP URL", "warn", "not configured", "zoho-skills onboard"))
        return checks
    checks.append(Check("MCP URL", "ok", f"set ({config.redact(url)})"))
    region = config.region()
    if config.host_matches_region(url, region):
        checks.append(Check("region", "ok", region))
    else:
        checks.append(Check("region", "warn", f"configured region '{region}' does not match the MCP URL's data centre",
                            "zoho-skills onboard (re-pick the region), or fix the URL"))
    return checks


def _check_packs() -> Check:
    try:
        found = packs.discover()
    except Exception as e:
        return Check("org packs", "fail", _scrub(e))
    if not found:
        return Check("org packs", "warn", "none installed", "zoho-skills orgs add <folder|git-url|owner/repo>")
    return Check("org packs", "ok", ", ".join(p.slug + (" (built-in)" if p.builtin else "") for p in found))


def _harness_name(h) -> str:
    if isinstance(h, str):
        return h
    if isinstance(h, dict):
        return str(h.get("name") or h.get("key") or h)
    return str(getattr(h, "name", None) or getattr(h, "key", None) or h)


def _check_harnesses(home: Path) -> list:
    try:
        from . import harnesses
    except ImportError:
        return [Check("harnesses", "skip", "harness writers not available yet")]
    out = []
    for h in harnesses.HARNESSES:
        name = _harness_name(h)
        try:
            st = harnesses.status(h, home=home)
        except Exception as e:
            out.append(Check(f"harness {name}", "warn", f"could not read config ({_scrub(e)})"))
            continue
        if st.get("present"):
            out.append(Check(f"harness {name}", "ok", f"zoho-skills entry present ({st.get('path') or 'n/a'})"))
        else:
            out.append(Check(f"harness {name}", "warn", "zoho-skills entry missing", "zoho-skills onboard"))
        if st.get("direct_zoho_entry"):
            out.append(Check(f"harness {name} direct entry", "warn",
                             "a direct Zoho MCP entry bypasses the write gate",
                             "remove the direct zoho entry from the harness config and run zoho-skills onboard"))
    return out


def _check_upstream(url: Optional[str], enabled: bool) -> Check:
    if not url:
        return Check("upstream", "skip", "no MCP URL configured")
    if not enabled:
        return Check("upstream", "skip", "upstream check disabled")

    async def probe():
        return await asyncio.wait_for(upstream.list_tools_once(url), UPSTREAM_TIMEOUT)

    try:
        tools = asyncio.run(probe())
    except asyncio.TimeoutError:
        return Check("upstream", "fail", f"no response within {UPSTREAM_TIMEOUT}s",
                     "check network access and that the Zoho MCP server is enabled")
    except Exception as e:
        msg = _scrub(upstream.describe_error(e))
        fix = ("zoho-skills login" if upstream.is_auth_error(e)
               else "check the MCP URL and region; zoho-skills connect to re-enter it")
        return Check("upstream", "fail", msg, fix)
    names = {getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None) for t in tools}
    missing = [t for t in mcp_config.REQUIRED_TOOLS if t not in names]
    detail = f"reachable; {len(tools)} tools (read-only tools/list, nothing was changed)"
    if missing:
        return Check("upstream", "warn", f"{detail}; missing required: {', '.join(missing)}",
                     "add these tools to the server in the Zoho MCP console")
    return Check("upstream", "ok", detail)


def _check_readonly() -> Check:
    if config.readonly():
        return Check("read-only mode", "ok", "ON: all Zoho writes are blocked")
    return Check("read-only mode", "ok", "off: writes need a dry-run preview and explicit confirmation")


def run_checks(home: Path, *, upstream_check: bool = True, runner=None) -> list:
    home = Path(home)
    checks = [_check_python(), _check_uv(runner)]
    checks += _check_config()
    checks.append(_check_packs())
    checks += _check_harnesses(home)
    checks.append(_check_upstream(config.get_url(), upstream_check))
    checks.append(_check_readonly())
    return checks


def render(checks: list) -> str:
    lines = []
    for c in checks:
        line = f"{_MARKS.get(c.status, '?')} {c.name}" + (f": {c.detail}" if c.detail else "")
        lines.append(line)
        if c.fix and c.status in ("warn", "fail"):
            lines.append(f"    fix: {c.fix}")
    return "\n".join(lines)
