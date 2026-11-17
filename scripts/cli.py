#!/usr/bin/env python3
"""creole-zoho — onboarding CLI for the Zoho Projects skills. Standard library only (Python 3.9+).

  creole-zoho                       interactive onboarding (skills → harnesses → scope → MCP → install)
  creole-zoho install --yes --harness claude,cursor --global --mcp-url https://...
  creole-zoho list | doctor | update
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapters  # noqa: E402
import mcp_config  # noqa: E402

CORE = "zoho-projects-core"
HARNESS_INFO = {  # harness -> (label, executable to detect, config dir under $HOME)
    "claude": ("Claude Code / Claude Desktop", "claude", ".claude"),
    "cursor": ("Cursor", "cursor", ".cursor"),
    "antigravity": ("Antigravity / Gemini CLI", "gemini", ".gemini"),
    "codex": ("Codex / Copilot / AGENTS.md tools", "codex", ".codex"),
}
COMMANDS = ("install", "list", "doctor", "update")


# ───────────────────────────── terminal styling ─────────────────────────────
class Style:
    def __init__(self) -> None:
        self.on = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"

    def _c(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def bold(self, s): return self._c("1", s)
    def dim(self, s): return self._c("2", s)
    def accent(self, s): return self._c("38;5;80", s)
    def ok(self, s): return self._c("32", s)
    def warn(self, s): return self._c("33", s)
    def err(self, s): return self._c("31", s)


S = Style()


def banner() -> None:
    print()
    print(f"  {S.accent('◆')} {S.bold('creole-zoho')} {S.dim('· Zoho Projects skills for AI agents')}")
    print(f"  {S.dim('skills · harnesses · MCP — one onboarding')}\n")


def step(n: int, total: int, title: str) -> None:
    print(f"{S.accent(f'[{n}/{total}]')} {S.bold(title)}")


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


# ───────────────────────────── key handling / menus ─────────────────────────
def _read_key() -> str:
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            nxt = sys.stdin.read(2)
            return {"[A": "up", "[B": "down"}.get(nxt, "other")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":
            return "ctrl-c"
        return {"k": "up", "j": "down", "a": "all", "q": "ctrl-c"}.get(ch, "other")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _menu(items: list, *, multi: bool, selected: set, locked: frozenset = frozenset(),
          default_index: int = 0) -> list:
    """items: [(key, label, hint)]. Returns the chosen keys (multi) or a one-element list (single)."""
    cur = default_index
    sel = set(selected) | set(locked)
    hint = "↑/↓ move · space toggle · a all · enter confirm" if multi else "↑/↓ move · enter select"
    lines_drawn = 0
    sys.stdout.write("\033[?25l")  # hide cursor
    try:
        while True:
            if lines_drawn:
                sys.stdout.write(f"\033[{lines_drawn}F\033[J")
            out = [f"  {S.dim(hint)}"]
            for i, (key, label, sub) in enumerate(items):
                pointer = S.accent("❯") if i == cur else " "
                if multi:
                    box = S.ok("◉") if key in sel else "○"
                    lock = S.dim(" (required)") if key in locked else ""
                else:
                    box = S.ok("●") if i == cur else "○"
                    lock = ""
                name = S.bold(label) if i == cur else label
                out.append(f"  {pointer} {box} {name}{lock}")
                if sub:
                    out.append(f"      {S.dim(sub)}")
            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
            lines_drawn = len(out)
            k = _read_key()
            if k == "ctrl-c":
                raise KeyboardInterrupt
            if k == "up":
                cur = (cur - 1) % len(items)
            elif k == "down":
                cur = (cur + 1) % len(items)
            elif k == "space" and multi:
                key = items[cur][0]
                if key not in locked:
                    sel ^= {key}
            elif k == "all" and multi:
                free = {i[0] for i in items}
                sel = free if sel != free else set(locked)
            elif k == "enter":
                if multi and not sel:
                    continue
                return [i[0] for i in items if i[0] in sel] if multi else [items[cur][0]]
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def ask(prompt: str, default: str = "") -> str:
    suffix = f" {S.dim('[' + default + ']')}" if default else ""
    try:
        return input(f"  {prompt}{suffix}: ").strip() or default
    except EOFError:
        return default


def confirm(prompt: str, default: bool = True) -> bool:
    ans = ask(f"{prompt} ({'Y/n' if default else 'y/N'})", "").lower()
    return default if not ans else ans.startswith("y")


# ───────────────────────────── detection ─────────────────────────────
def detect_harnesses(home: Path) -> list:
    found = []
    for h, (_, exe, cfg) in HARNESS_INFO.items():
        if shutil.which(exe) or (home / cfg).is_dir():
            found.append(h)
    return found


def skill_rows() -> list:
    rows = []
    for n in adapters.list_skills():
        meta, _ = adapters.parse_skill(n)
        desc = meta["description"]
        rows.append((n, n, desc if len(desc) <= 92 else desc[:89].rstrip() + "…"))
    return rows


# ───────────────────────────── install flow ─────────────────────────────
def _split(value: str, valid: list, what: str) -> list:
    items = valid if value == "all" else [v.strip() for v in value.split(",") if v.strip()]
    bad = [i for i in items if i not in valid]
    if bad:
        raise SystemExit(f"unknown {what}: {', '.join(bad)}. available: {', '.join(valid)}")
    return items


def cmd_install(a: argparse.Namespace) -> int:
    home = Path.home()
    tty = interactive() and not a.yes
    total = 5
    if tty:
        banner()

    # 1 — skills
    available = adapters.list_skills()
    if a.skills:
        names = _split(a.skills, available, "skill")
    elif tty:
        step(1, total, "Choose skills")
        names = _menu(skill_rows(), multi=True, selected=set(available),
                      locked=frozenset([CORE]) if CORE in available else frozenset())
        print()
    else:
        names = list(available)
    if CORE in available and CORE not in names:
        names = [CORE] + names  # org skills require the core skill

    # 2 — harnesses
    detected = detect_harnesses(home)
    if a.harness:
        harnesses = _split(a.harness, adapters.HARNESSES, "harness")
    elif tty:
        step(2, total, "Choose harnesses")
        rows = [(h, HARNESS_INFO[h][0], "detected on this machine" if h in detected else "") for h in adapters.HARNESSES]
        harnesses = _menu(rows, multi=True, selected=set(detected) or set(adapters.HARNESSES))
        print()
    else:
        harnesses = detected or list(adapters.HARNESSES)

    # 3 — scope
    project: Optional[Path] = Path(a.project).expanduser().resolve() if a.project else None
    global_scope = bool(a.global_scope) or (project is None and not tty)
    if project is None and not a.global_scope and tty:
        step(3, total, "Where should the skills live?")
        choice = _menu([("global", "Global", f"under {home} — available in every project"),
                                 ("project", "This project", "a folder you choose")],
                       multi=False, selected=set())[0]
        print()
        if choice == "project":
            project = Path(ask("Project directory", os.getcwd())).expanduser().resolve()
        else:
            global_scope = True
    base = home if global_scope else project

    # 4 — MCP
    mcp_url = None
    if not a.no_mcp:
        mcp_url = a.mcp_url or os.environ.get("ZOHO_MCP_URL")
        if not mcp_url and tty:
            step(4, total, "Connect the Zoho Projects MCP server")
            print(f"  {S.dim('Paste your Zoho MCP URL (from Zoho MCP / Developer console). Leave blank to skip.')}")
            mcp_url = ask("MCP URL") or None
            print()
        if mcp_url:
            try:
                mcp_url = mcp_config.validate_url(mcp_url)
            except mcp_config.McpError as e:
                raise SystemExit(f"error: {e}")

    # 5 — review
    plan = [("Skills", ", ".join(names)), ("Harnesses", ", ".join(harnesses)),
            ("Scope", f"global ({home})" if global_scope else f"project ({base})"),
            ("MCP", mcp_config.mask_url(mcp_url) if mcp_url else "skipped")]
    if tty or a.dry_run:
        step(5, total, "Review" + (" (dry run)" if a.dry_run else ""))
        for k, v in plan:
            print(f"  {S.dim(k.ljust(10))} {v}")
        print()
    if tty and not a.dry_run and not confirm("Install now?"):
        print("  cancelled — nothing written.")
        return 1

    errors = 0
    for h in harnesses:
        label = HARNESS_INFO[h][0]
        if h == "cursor" and global_scope:
            print(f"  {S.warn('!')} {label}: skills skipped for --global (Cursor user rules live in its settings; "
                  "use a project install)")
        elif a.dry_run:
            print(f"  {S.dim('·')} {label}: would install {', '.join(names)} under {base}")
        else:
            for p in adapters.install(h, names, base, global_scope=global_scope):
                print(f"  {S.ok('✔')} {label}: {p}")
        if mcp_url:
            try:
                msg = mcp_config.register(h, mcp_url, home=home, project=None if global_scope else base,
                                          dry_run=a.dry_run)
                print(f"  {S.ok('✔') if not a.dry_run else S.dim('·')} {label} MCP: {msg}")
            except (mcp_config.McpError, subprocess.SubprocessError, OSError) as e:
                errors += 1
                print(f"  {S.err('✖')} {label} MCP: {e}")
                print(f"      {S.dim('manual:')} {mcp_config.snippet(h, '<your-mcp-url>')}")
    if a.dry_run:
        print(f"\n  {S.dim('dry run — nothing was written.')}")
        return 0
    print(f"\n  {S.ok('Done.')} Next:")
    if mcp_url:
        print("   • Authenticate the Zoho MCP in your harness (Claude Code: /mcp).")
    else:
        print("   • Connect the MCP: re-run `creole-zoho install` or see skills/zoho-projects-core/references/mcp-setup.md")
    print("   • Verify (read-only): ask your agent “list my Zoho portals, then the latest 5 tasks”.")
    print(f"   • Health check any time: {S.bold('creole-zoho doctor')}\n")
    return 1 if errors else 0


def cmd_list(_: argparse.Namespace) -> int:
    for name, _, desc in skill_rows():
        print(f"{S.bold(name)}\n  {desc}")
    print("\nharnesses: " + ", ".join(adapters.HARNESSES))
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    home = Path.home()
    bad = 0
    ok_py = sys.version_info >= (3, 9)
    print(f"{S.ok('✔') if ok_py else S.err('✖')} python {sys.version.split()[0]} (need ≥ 3.9)")
    bad += not ok_py
    for h, (label, exe, cfg) in HARNESS_INFO.items():
        present = shutil.which(exe) or (home / cfg).is_dir()
        proj_rel, glob_rel = adapters.SKILL_DIRS.get(h, (None, None))
        installed = [n for n in adapters.list_skills()
                     if glob_rel and (home / glob_rel / n / "SKILL.md").is_file()]
        mcp_path = mcp_config.config_path(h, home, None)
        has_mcp = False
        if h == "claude" and shutil.which("claude"):
            has_mcp = mcp_config.default_runner(["claude", "mcp", "get", mcp_config.SERVER_NAME], None).returncode == 0
        elif mcp_path and mcp_path.exists():
            has_mcp = mcp_config.SERVER_NAME in mcp_path.read_text(encoding="utf-8", errors="ignore")
        print(f"{S.ok('✔') if present else S.dim('–')} {label}: "
              f"{'found' if present else 'not found'}; skills: {', '.join(installed) or 'none (global)'}; "
              f"MCP: {'yes' if has_mcp else 'not registered'}")
    return 1 if bad else 0


def cmd_update(_: argparse.Namespace) -> int:
    script = adapters.REPO / "install.sh"
    if not script.is_file():
        print("install.sh not found; re-run the curl installer from the README.")
        return 1
    env = dict(os.environ, CZ_NO_RUN="1")
    return subprocess.run(["sh", str(script)], env=env).returncode


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="creole-zoho", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    ins = sub.add_parser("install", help="interactive onboarding (default)")
    ins.add_argument("--skills", help="comma list or 'all' (default: ask / all)")
    ins.add_argument("--harness", help=f"comma list of {', '.join(adapters.HARNESSES)} or 'all'")
    scope = ins.add_mutually_exclusive_group()
    scope.add_argument("--global", dest="global_scope", action="store_true", help="install under $HOME")
    scope.add_argument("--project", metavar="DIR", help="install into this project directory")
    ins.add_argument("--mcp-url", help="Zoho Projects MCP URL (or env ZOHO_MCP_URL)")
    ins.add_argument("--no-mcp", action="store_true", help="skip the MCP step")
    ins.add_argument("-y", "--yes", action="store_true", help="no prompts; use flags/defaults")
    ins.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    sub.add_parser("list", help="list skills and harnesses")
    sub.add_parser("doctor", help="check python, harnesses, installed skills and MCP")
    sub.add_parser("update", help="fetch the latest version of this tool")
    return ap


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "install")
    a = build_parser().parse_args(argv)
    try:
        return {"install": cmd_install, "list": cmd_list, "doctor": cmd_doctor, "update": cmd_update}[a.cmd](a)
    except KeyboardInterrupt:
        print("\n  cancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
