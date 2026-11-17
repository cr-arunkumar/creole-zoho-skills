"""Register the single `zoho-skills` MCP entry (command: `zoho-skills mcp`) with each AI harness.

The Zoho MCP URL is a credential and is never written to any harness config; only the launch command is.
User-level config only (under `home`). Existing config is preserved and backed up to `<file>.bak` once before
the first change; re-running is idempotent; unparseable config is never overwritten.

Config locations, verified against current official docs:
  claude       `claude mcp add -s user NAME -- CMD ARGS`, `claude mcp remove`, `claude mcp get`; user scope lives in
               ~/.claude.json            https://code.claude.com/docs/en/mcp
  cursor       ~/.cursor/mcp.json, {"mcpServers": {NAME: {"command", "args"}}}
                                         https://cursor.com/docs/context/mcp
  antigravity  ~/.gemini/config/mcp_config.json (shared by Antigravity CLI and IDE), {"mcpServers": {...}}.
               NOT ~/.gemini/settings.json (that is Gemini CLI) and not the older community path
               ~/.gemini/antigravity/mcp_config.json.   https://antigravity.google/docs/mcp
  codex        ~/.codex/config.toml, [mcp_servers.NAME] with command/args
                                         https://learn.chatgpt.com/docs/extend/mcp?surface=cli (was developers.openai.com/codex/mcp)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

try:  # Python >= 3.11; without it TOML is only checked structurally by our own marker handling
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

HARNESSES = ["claude", "cursor", "antigravity", "codex"]
SERVER_NAME = "zoho-skills"
TOML_START = "# zoho-skills:start"
TOML_END = "# zoho-skills:end"

Runner = Callable[[list], "subprocess.CompletedProcess"]


class HarnessError(Exception):
    pass


def default_runner(cmd: list) -> "subprocess.CompletedProcess":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def entry_command() -> tuple[str, list[str]]:
    return (shutil.which("zoho-skills") or "zoho-skills", ["mcp"])


def _json_path(harness: str, home: Path) -> Path:
    if harness == "cursor":
        return home / ".cursor" / "mcp.json"
    return home / ".gemini" / "config" / "mcp_config.json"  # antigravity


def _toml_path(home: Path) -> Path:
    return home / ".codex" / "config.toml"


def _claude_json(home: Path) -> Path:
    return home / ".claude.json"


def _check(harness: str) -> None:
    if harness not in HARNESSES:
        raise HarnessError(f"unknown harness {harness!r}; choose from: {', '.join(HARNESSES)}")


def _backup(path: Path) -> None:
    bak = path.with_name(path.name + ".bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)


def _write(path: Path, text: str) -> None:
    _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _looks_zoho(name: str, spec: object) -> bool:
    if name == SERVER_NAME:
        return False
    if "zoho" in name.lower():
        return True
    if not isinstance(spec, dict):
        return False
    for key in ("url", "httpUrl", "serverUrl"):
        if "zoho" in str(spec.get(key, "")).lower():
            return True
    command = str(spec.get("command", ""))
    if os.path.basename(command) == SERVER_NAME:
        return False
    args = spec.get("args")
    parts = [command] + [str(a) for a in args] if isinstance(args, list) else [command]
    return "zoho" in " ".join(parts).lower()


# ---------------------------------------------------------------- JSON harnesses (cursor, antigravity)

def _load_json(path: Path) -> dict:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HarnessError(f"{path} is not valid JSON ({e}); fix it or add the server manually") from e
    if not isinstance(data, dict):
        raise HarnessError(f"{path} must contain a JSON object")
    if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
        raise HarnessError(f"{path}: mcpServers must be an object")
    return data


def _json_register(harness: str, home: Path, dry_run: bool) -> str:
    path = _json_path(harness, home)
    data = _load_json(path)
    command, args = entry_command()
    entry = {"command": command, "args": args}
    servers = data.setdefault("mcpServers", {})
    if servers.get(SERVER_NAME) == entry:
        return f"unchanged: {path}"
    verb = "updated" if SERVER_NAME in servers else "added"
    if dry_run:
        return f"would {'update' if verb == 'updated' else 'add'}: {path}"
    servers[SERVER_NAME] = entry
    _write(path, json.dumps(data, indent=2) + "\n")
    return f"{verb}: {path}"


def _json_unregister(harness: str, home: Path, dry_run: bool) -> str:
    path = _json_path(harness, home)
    data = _load_json(path)
    servers = data.get("mcpServers", {})
    if SERVER_NAME not in servers:
        return f"unchanged: {SERVER_NAME} not present in {path}"
    if dry_run:
        return f"would remove: {path}"
    del servers[SERVER_NAME]
    _write(path, json.dumps(data, indent=2) + "\n")
    return f"removed: {path}"


def _json_status(harness: str, home: Path) -> dict:
    path = _json_path(harness, home)
    if not path.exists():
        return {"present": False, "path": None, "direct_zoho_entry": False}
    servers = _load_json(path).get("mcpServers", {})
    return {"present": SERVER_NAME in servers, "path": str(path),
            "direct_zoho_entry": any(_looks_zoho(n, s) for n, s in servers.items())}


# ---------------------------------------------------------------- Codex (TOML)

def _read_toml(path: Path) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if tomllib is not None and text.strip():
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise HarnessError(f"{path} is not valid TOML ({e}); fix it or add the server manually") from e
    return text


def _toml_block() -> str:
    command, args = entry_command()
    arg_list = ", ".join(json.dumps(a) for a in args)
    return (f"{TOML_START}\n[mcp_servers.{SERVER_NAME}]\ncommand = {json.dumps(command)}\n"
            f"args = [{arg_list}]\n{TOML_END}\n")


_TOML_PAT = re.compile(r"\n?" + re.escape(TOML_START) + r".*?" + re.escape(TOML_END) + r"\n?", re.S)


def _hand_defined(text: str) -> bool:
    without = _TOML_PAT.sub("", text)
    return bool(re.search(rf'^\s*\[mcp_servers\.("?){re.escape(SERVER_NAME)}\1(\.[^\]]*)?\]', without, re.M))


def _toml_register(home: Path, dry_run: bool) -> str:
    path = _toml_path(home)
    text = _read_toml(path)
    block = _toml_block()
    if _hand_defined(text):
        raise HarnessError(f"{path} already defines [mcp_servers.{SERVER_NAME}] by hand; edit it manually")
    if _TOML_PAT.search(text):
        m = _TOML_PAT.search(text)
        new = text[:m.start()] + ("\n" if m.group(0).startswith("\n") else "") + block + text[m.end():]
        verb = "updated"
    else:
        new = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
        verb = "added"
    if new == text:
        return f"unchanged: {path}"
    if dry_run:
        return f"would {'update' if verb == 'updated' else 'add'}: {path}"
    _write(path, new)
    return f"{verb}: {path}"


def _toml_unregister(home: Path, dry_run: bool) -> str:
    path = _toml_path(home)
    text = _read_toml(path)
    if not _TOML_PAT.search(text):
        return f"unchanged: {SERVER_NAME} not present in {path}"
    if dry_run:
        return f"would remove: {path}"
    new = _TOML_PAT.sub("\n", text, count=1).strip("\n")
    _write(path, new + "\n" if new else "")
    return f"removed: {path}"


def _toml_status(home: Path) -> dict:
    path = _toml_path(home)
    if not path.exists():
        return {"present": False, "path": None, "direct_zoho_entry": False}
    text = _read_toml(path)
    servers: dict = {}
    if tomllib is not None and text.strip():
        servers = tomllib.loads(text).get("mcp_servers", {})
    else:  # no parser: names only, from table headers
        servers = {m: {} for m in re.findall(r'^\s*\[mcp_servers\.("?[\w.-]+"?)\]', text, re.M)}
    present = SERVER_NAME in servers or bool(_TOML_PAT.search(text))
    direct = any(_looks_zoho(n, s) for n, s in servers.items() if isinstance(servers, dict))
    return {"present": present, "path": str(path), "direct_zoho_entry": direct}


# ---------------------------------------------------------------- Claude Code (via its own CLI)

def _claude_cmd(*tail: str) -> list:
    return ["claude", "mcp", *tail]


def _claude_available(runner: Runner) -> None:
    if runner is default_runner and shutil.which("claude") is None:
        command, args = entry_command()
        raise HarnessError("`claude` CLI not found on PATH; run: "
                           f"claude mcp add -s user {SERVER_NAME} -- {command} {' '.join(args)}")


def _claude_fail(res: "subprocess.CompletedProcess", what: str) -> HarnessError:
    msg = (res.stderr or res.stdout or what).strip().splitlines()
    return HarnessError(msg[-1] if msg else what)


def _claude_register(home: Path, runner: Runner, dry_run: bool) -> str:
    command, args = entry_command()
    add = _claude_cmd("add", "-s", "user", SERVER_NAME, "--", command, *args)
    if dry_run:
        return "would run: " + " ".join(add)
    _claude_available(runner)
    if runner(_claude_cmd("get", SERVER_NAME)).returncode == 0:
        return "unchanged: already registered with claude"
    res = runner(add)
    if res.returncode != 0:
        raise _claude_fail(res, "claude mcp add failed")
    return "added: registered with claude (user scope)"


def _claude_unregister(home: Path, runner: Runner, dry_run: bool) -> str:
    rm = _claude_cmd("remove", "-s", "user", SERVER_NAME)
    if dry_run:
        return "would run: " + " ".join(rm)
    _claude_available(runner)
    if runner(_claude_cmd("get", SERVER_NAME)).returncode != 0:
        return f"unchanged: {SERVER_NAME} not registered with claude"
    res = runner(rm)
    if res.returncode != 0:
        raise _claude_fail(res, "claude mcp remove failed")
    return "removed: unregistered from claude (user scope)"


def _claude_status(home: Path, runner: Runner) -> dict:
    present = False
    if not (runner is default_runner and shutil.which("claude") is None):
        try:
            present = runner(_claude_cmd("get", SERVER_NAME)).returncode == 0
        except (OSError, subprocess.SubprocessError):
            present = False
    path = _claude_json(home)
    direct = False
    if path.exists():
        try:
            servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
            direct = isinstance(servers, dict) and any(_looks_zoho(n, s) for n, s in servers.items())
        except (json.JSONDecodeError, AttributeError):
            pass
    return {"present": present, "path": str(path) if path.exists() else None, "direct_zoho_entry": direct}


# ---------------------------------------------------------------- public API

def register(harness: str, *, home: Path, runner: Runner = default_runner, dry_run: bool = False) -> str:
    _check(harness)
    if harness == "claude":
        return _claude_register(home, runner, dry_run)
    if harness == "codex":
        return _toml_register(home, dry_run)
    return _json_register(harness, home, dry_run)


def unregister(harness: str, *, home: Path, runner: Runner = default_runner, dry_run: bool = False) -> str:
    _check(harness)
    if harness == "claude":
        return _claude_unregister(home, runner, dry_run)
    if harness == "codex":
        return _toml_unregister(home, dry_run)
    return _json_unregister(harness, home, dry_run)


def status(harness: str, *, home: Path, runner: Runner = default_runner) -> dict:
    _check(harness)
    if harness == "claude":
        return _claude_status(home, runner)
    if harness == "codex":
        return _toml_status(home)
    return _json_status(harness, home)
