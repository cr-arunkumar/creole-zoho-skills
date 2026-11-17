#!/usr/bin/env python3
"""creole-zoho — onboarding CLI for the Zoho Projects skills. Standard library only (Python 3.9+).

  creole-zoho                       interactive onboarding (skills → harnesses → scope → MCP → review → install)
  creole-zoho mcp                   guided: only (re)connect the Zoho Projects MCP server
  creole-zoho install --yes --harness claude,cursor --global --mcp-url https://...
  creole-zoho list | doctor | update
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapters  # noqa: E402
import mcp_config  # noqa: E402
import tui  # noqa: E402
from tui import BACK, S  # noqa: E402

CORE = "zoho-projects-core"
HARNESS_INFO = {  # harness -> (label, executable to detect, config dir under $HOME)
    "claude": ("Claude Code / Desktop", "claude", ".claude"),
    "cursor": ("Cursor", "cursor", ".cursor"),
    "antigravity": ("Antigravity / Gemini CLI", "gemini", ".gemini"),
    "codex": ("Codex / Copilot (AGENTS.md)", "codex", ".codex"),
}
COMMANDS = ("install", "mcp", "list", "doctor", "update")
PROMPTED, SKIPPED = "prompted", "skipped"


def version() -> str:
    try:
        return json.loads((adapters.REPO / ".claude-plugin" / "plugin.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "dev"


# ───────────────────────────── helpers ─────────────────────────────
def detect_harnesses(home: Path) -> list:
    return [h for h, (_, exe, cfg) in HARNESS_INFO.items() if shutil.which(exe) or (home / cfg).is_dir()]


def skill_rows() -> list:
    rows = []
    for n in adapters.list_skills():
        meta, _ = adapters.parse_skill(n)
        rows.append((n, n, meta["description"]))
    return rows


def harness_rows(detected: list) -> list:
    return [(h, HARNESS_INFO[h][0], "detected on this machine" if h in detected else "not detected — install anyway")
            for h in adapters.HARNESSES]


def _split(value: str, valid: list, what: str) -> list:
    items = valid if value == "all" else [v.strip() for v in value.split(",") if v.strip()]
    bad = [i for i in items if i not in valid]
    if bad:
        raise SystemExit(f"unknown {what}: {', '.join(bad)}. available: {', '.join(valid)}")
    return items


@dataclass
class State:
    args: argparse.Namespace
    home: Path
    tty: bool
    can_back: bool = False
    names: list = field(default_factory=list)
    harnesses: list = field(default_factory=list)
    project: Optional[Path] = None
    global_scope: bool = True
    mcp_url: Optional[str] = None

    @property
    def base(self) -> Path:
        return self.home if self.global_scope else self.project


# ───────────────────────────── wizard steps ─────────────────────────────
# Each step returns PROMPTED (asked the user), SKIPPED (answer came from flags/defaults) or BACK (esc).
def step_skills(st: State) -> object:
    available = adapters.list_skills()
    locked = [CORE] if CORE in available else []
    if st.args.skills:
        st.names = _split(st.args.skills, available, "skill")
        res = SKIPPED
    elif st.tty:
        pick = tui.choose("Choose skills", skill_rows(), multi=True, selected=available, locked=locked,
                          can_back=st.can_back, step="1/5", summary=lambda r: ", ".join(r))
        if pick is BACK:
            return BACK
        st.names, res = pick, PROMPTED
    else:
        st.names, res = list(available), SKIPPED
    if CORE in available and CORE not in st.names:
        st.names = [CORE] + st.names  # org skills require the core skill
    return res


def step_harnesses(st: State, step: str = "2/5") -> object:
    detected = detect_harnesses(st.home)
    if st.args.harness:
        st.harnesses = _split(st.args.harness, adapters.HARNESSES, "harness")
        return SKIPPED
    if st.tty:
        pick = tui.choose("Choose harnesses", harness_rows(detected), multi=True,
                          selected=detected or adapters.HARNESSES, can_back=st.can_back, step=step,
                          summary=lambda r: ", ".join(HARNESS_INFO[h][0] for h in r))
        if pick is BACK:
            return BACK
        st.harnesses = pick
        return PROMPTED
    st.harnesses = detected or list(adapters.HARNESSES)
    return SKIPPED


def step_scope(st: State) -> object:
    a = st.args
    if a.project:
        st.project, st.global_scope = Path(a.project).expanduser().resolve(), False
        return SKIPPED
    if a.global_scope or not st.tty:
        st.global_scope = True
        return SKIPPED
    pick = tui.choose("Where should skills live?", [
        ("global", "Global", f"under {st.home} — available in every project"),
        ("project", "A project", "a folder you choose (committable, shared with your team)")],
        multi=False, can_back=st.can_back, step="3/5",
        summary=lambda r: "global" if r == "global" else "project")
    if pick is BACK:
        return BACK
    if pick == "project":
        d = tui.text("Project directory", default=os.getcwd(), hint="'<' to go back", step="3/5",
                     summary=lambda v: v)
        if d is BACK:
            return BACK
        st.project, st.global_scope = Path(d).expanduser().resolve(), False
    else:
        st.global_scope = True
    return PROMPTED


def guided_mcp_url(st: State, step: str) -> object:
    """Official-console walkthrough. Returns a URL, '' to skip, or BACK."""
    region = st.args.region
    if not region:
        keys = list(mcp_config.REGIONS)
        rows = [(r, mcp_config.REGIONS[r].replace("https://", "").rstrip("/"),
                 "India data centre (default)" if r == mcp_config.DEFAULT_REGION else "") for r in keys]
        region = tui.choose("Zoho data centre", rows, multi=False, default_index=keys.index(mcp_config.DEFAULT_REGION),
                            can_back=st.can_back, step=step, summary=lambda r: mcp_config.REGIONS[r])
        if region is BACK:
            return BACK
    console = mcp_config.console_url(region)
    tui.info(S.bold("Get your MCP URL") + S.dim("  (official Zoho MCP console)"))
    tui.info(f"1. Open {S.accent(console)} and sign in")
    tui.info("2. Create MCP Server → Tools → Add Tools → Zoho Projects, and add at least:")
    tui.info(S.dim("   " + ", ".join(mcp_config.REQUIRED_TOOLS)))
    tui.info("3. Open the Connect tab and copy the MCP URL " + S.dim("(treat it like a password)"))
    print(S.dim("└"))
    nxt = tui.choose("Next", [("open", "Open the console in my browser", ""),
                              ("have", "I already have the URL", ""),
                              ("skip", "Skip — I'll connect later (creole-zoho mcp)", "")],
                     multi=False, can_back=True, summary=lambda r: {"open": "opened browser", "have": "have URL",
                                                                    "skip": "skip"}[r])
    if nxt is BACK:
        return BACK
    if nxt == "skip":
        return ""
    if nxt == "open":
        webbrowser.open(console)
    return tui.text("Paste MCP URL", hint="input hidden · enter to skip · '<' back", secret=True, step=step,
                    summary=lambda v: mcp_config.mask_url(v) if v else "skipped")


def step_mcp(st: State, step: str = "4/5") -> object:
    a = st.args
    if a.no_mcp:
        return SKIPPED
    url = a.mcp_url or os.environ.get("ZOHO_MCP_URL")
    res = SKIPPED
    if not url and st.tty:
        url = guided_mcp_url(st, step)
        if url is BACK:
            return BACK
        res = PROMPTED
    if url:
        try:
            st.mcp_url = mcp_config.validate_url(url)
        except mcp_config.McpError as e:
            if st.tty:
                print(f"{S.err('✖')} {e}")
                return step_mcp(st, step)
            raise SystemExit(f"error: {e}")
    return res


def plan_rows(st: State) -> list:
    return [("Skills", ", ".join(st.names)),
            ("Harnesses", ", ".join(HARNESS_INFO[h][0] for h in st.harnesses)),
            ("Scope", f"global · {st.home}" if st.global_scope else f"project · {st.project}"),
            ("MCP", mcp_config.mask_url(st.mcp_url) if st.mcp_url else "skipped")]


def step_review(st: State) -> object:
    if not st.tty:
        return SKIPPED
    tui.box([f"{S.dim(k.ljust(10))} {v}" for k, v in plan_rows(st)], title="Review")
    pick = tui.choose("Ready?", [("go", "Install now", ""), ("back", "Go back and change something", ""),
                                 ("cancel", "Cancel", "nothing will be written")],
                      multi=False, can_back=True, step="5/5",
                      summary=lambda r: {"go": "installing", "back": "back", "cancel": "cancelled"}[r])
    if pick is BACK or pick == "back":
        return BACK
    if pick == "cancel":
        raise KeyboardInterrupt
    return PROMPTED


def run_wizard(steps: list, st: State) -> None:
    hist: list = []
    i = 0
    while i < len(steps):
        st.can_back = bool(hist)
        r = steps[i](st)
        if r is BACK:
            i = hist.pop() if hist else i
            continue
        if r == PROMPTED:
            hist.append(i)
        i += 1


# ───────────────────────────── execution ─────────────────────────────
def register_all(st: State, dry_run: bool) -> int:
    errors = 0
    project = None if st.global_scope else st.base
    for h in st.harnesses:
        label = HARNESS_INFO[h][0]
        with tui.Spinner(f"{label}: connecting MCP") as sp:
            try:
                msg = mcp_config.register(h, st.mcp_url, home=st.home, project=project, dry_run=dry_run)
                sp.ok(f"{label} MCP — {msg}")
            except (mcp_config.McpError, subprocess.SubprocessError, OSError) as e:
                errors += 1
                sp.fail(f"{label} MCP — {e}")
                print(f"  {S.dim('manual:')} {mcp_config.snippet(h, '<your-mcp-url>')}")
    return errors


def _short(p: Path, home: Path) -> str:
    try:
        return "~/" + str(p.relative_to(home))
    except ValueError:
        return str(p)


def install_skills(st: State, dry_run: bool) -> None:
    for h in st.harnesses:
        label = HARNESS_INFO[h][0]
        with tui.Spinner(f"{label}: installing skills") as sp:
            if h == "cursor" and st.global_scope:
                sp.warn(f"{label}: skills skipped for --global (Cursor user rules live in its settings; use a project install)")
            elif dry_run:
                sp.ok(f"{label}: would install {', '.join(st.names)} under {st.base}")
            else:
                written = adapters.install(h, st.names, st.base, global_scope=st.global_scope)
                sp.ok(f"{label}: {len(written)} file(s) → {_short(written[0].parent, st.home)}")


def finish(st: State, errors: int) -> None:
    steps = []
    if st.mcp_url:
        steps.append("Authenticate the Zoho MCP in your harness " + S.dim("(Claude Code: /mcp)"))
    else:
        steps.append(f"Connect the Zoho MCP:  {S.bold('creole-zoho mcp')}")
    steps.append("Try it (read-only): " + S.dim("“list my Zoho portals, then the latest 5 tasks”"))
    steps.append(f"Health check any time:  {S.bold('creole-zoho doctor')}")
    print()
    tui.box([f"{S.accent(str(i))}  {t}" for i, t in enumerate(steps, 1)],
            title="All set" if not errors else "Finished with issues", color=S.ok if not errors else S.warn)
    print()


def cmd_install(a: argparse.Namespace) -> int:
    st = State(a, Path.home(), tty=tui.interactive() and not a.yes)
    if st.tty:
        tui.banner(version())
    run_wizard([step_skills, step_harnesses, step_scope, step_mcp, step_review], st)
    if a.dry_run and not st.tty:
        tui.box([f"{S.dim(k.ljust(10))} {v}" for k, v in plan_rows(st)], title="Plan (dry run)")
    if st.tty:
        print()
    install_skills(st, a.dry_run)
    errors = register_all(st, a.dry_run) if st.mcp_url else 0
    if a.dry_run:
        print(f"\n  {S.dim('dry run — nothing was written.')}")
        return 0
    finish(st, errors)
    return 1 if errors else 0


def cmd_mcp(a: argparse.Namespace) -> int:
    """Connect (or reconnect) only the Zoho Projects MCP server, without touching skills."""
    st = State(a, Path.home(), tty=tui.interactive() and not a.yes)
    if a.project:
        st.project, st.global_scope = Path(a.project).expanduser().resolve(), False
    if st.tty:
        tui.banner(version())
    run_wizard([lambda s: step_harnesses(s, "1/2"), lambda s: step_mcp(s, "2/2")], st)
    if not st.mcp_url:
        print(f"  Create your MCP server at {mcp_config.console_url(a.region or mcp_config.DEFAULT_REGION)} "
              "(Connect tab → copy URL), then run: creole-zoho mcp --mcp-url <url>")
        return 1
    errors = register_all(st, a.dry_run)
    if not a.dry_run and not errors:
        print(f"\n  {S.ok('Done.')} Authenticate in your harness (Claude Code: /mcp).\n")
    return 1 if errors else 0


def cmd_list(_: argparse.Namespace) -> int:
    for name, _, desc in skill_rows():
        print(f"{S.bold(name)}\n  {S.dim(tui.clip(desc, tui.cols() - 4))}")
    print("\nharnesses: " + ", ".join(adapters.HARNESSES))
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    home = Path.home()
    ok_py = sys.version_info >= (3, 9)
    rows = [f"{S.ok('✔') if ok_py else S.err('✖')} {'python'.ljust(26)} {sys.version.split()[0]}"
            + ("" if ok_py else "  (need ≥ 3.9)")]
    hints = []
    for h, (label, exe, cfg) in HARNESS_INFO.items():
        present = bool(shutil.which(exe) or (home / cfg).is_dir())
        _, glob_rel = adapters.SKILL_DIRS.get(h, (None, None))
        installed = [n for n in adapters.list_skills() if glob_rel and (home / glob_rel / n / "SKILL.md").is_file()]
        mcp_path = mcp_config.config_path(h, home, None)
        if h == "claude" and shutil.which("claude"):
            has_mcp = mcp_config.default_runner(["claude", "mcp", "get", mcp_config.SERVER_NAME], None).returncode == 0
        else:
            has_mcp = bool(mcp_path and mcp_path.exists() and
                           mcp_config.SERVER_NAME in mcp_path.read_text(encoding="utf-8", errors="ignore"))
        mark = S.ok("✔") if present and installed and has_mcp else (S.warn("!") if present else S.dim("–"))
        skills = f"{len(installed)} skill(s)" if installed else "no skills"
        rows.append(f"{mark} {label.ljust(26)} {S.dim('found' if present else 'not found')} · {skills} · "
                    f"MCP {'on' if has_mcp else 'off'}")
        if present and not has_mcp:
            hints.append(f"{label}: creole-zoho mcp --harness {h}")
        if present and not installed and h != "cursor":
            hints.append(f"{label}: creole-zoho install --harness {h} --global")
    print()
    tui.box(rows, title="creole-zoho doctor")
    if hints:
        print("\n  " + S.bold("Fix:"))
        for h in hints:
            print(f"   {S.accent('›')} {h}")
    print()
    return 0 if ok_py else 1


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
    ap.add_argument("--version", action="version", version=f"creole-zoho {version()}")
    sub = ap.add_subparsers(dest="cmd")
    ins = sub.add_parser("install", help="interactive onboarding (default)")
    ins.add_argument("--skills", help="comma list or 'all' (default: ask / all)")
    ins.add_argument("--harness", help=f"comma list of {', '.join(adapters.HARNESSES)} or 'all'")
    scope = ins.add_mutually_exclusive_group()
    scope.add_argument("--global", dest="global_scope", action="store_true", help="install under $HOME")
    scope.add_argument("--project", metavar="DIR", help="install into this project directory")
    ins.add_argument("--mcp-url", help="Zoho Projects MCP URL (or env ZOHO_MCP_URL)")
    ins.add_argument("--region", choices=list(mcp_config.REGIONS), help="Zoho data centre for the MCP console")
    ins.add_argument("--no-mcp", action="store_true", help="skip the MCP step")
    ins.add_argument("-y", "--yes", action="store_true", help="no prompts; use flags/defaults")
    ins.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    m = sub.add_parser("mcp", help="connect only the Zoho Projects MCP server (guided)")
    m.add_argument("--harness", help="comma list or 'all'")
    m.add_argument("--project", metavar="DIR", help="register in this project instead of globally")
    m.add_argument("--mcp-url")
    m.add_argument("--region", choices=list(mcp_config.REGIONS))
    m.add_argument("--no-mcp", action="store_true", help=argparse.SUPPRESS)
    m.add_argument("-y", "--yes", action="store_true")
    m.add_argument("--dry-run", action="store_true")
    sub.add_parser("list", help="list skills and harnesses")
    sub.add_parser("doctor", help="check python, harnesses, installed skills and MCP")
    sub.add_parser("update", help="fetch the latest version of this tool")
    return ap


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "install")
    a = build_parser().parse_args(argv)
    try:
        return {"install": cmd_install, "mcp": cmd_mcp, "list": cmd_list, "doctor": cmd_doctor,
                "update": cmd_update}[a.cmd](a)
    except KeyboardInterrupt:
        print(f"\n{S.dim('│')}\n{S.dim('└')} cancelled — nothing was written after this point.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
