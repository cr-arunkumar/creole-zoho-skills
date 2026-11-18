"""zoho-skills — onboarding + MCP server for Zoho Projects automation skills. Python 3.9+.

  zoho-skills                       guided onboarding (harnesses → scope → org packs → Zoho URL → review → install)
  zoho-skills mcp                   run the MCP server (stdio): org rules + write-gated Zoho proxy
  zoho-skills connect               (re)set the Zoho MCP URL
  zoho-skills login                 sign in to Zoho (OAuth, browser) — required once after connect
  zoho-skills logout                forget the stored Zoho URL and sign-in
  zoho-skills disconnect            remove the zoho-skills MCP entry from harnesses (keeps skills)
  zoho-skills org add|list|update|remove
  zoho-skills install | lint | doctor | update | uninstall | list
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import adapters, config, mcp_config, packs, tui
from .tui import BACK, S

CORE = "zoho-projects-core"
HARNESS_INFO = {  # harness -> (label, executable to detect, config dir under $HOME)
    "claude": ("Claude Code / Desktop", "claude", ".claude"),
    "cursor": ("Cursor", "cursor", ".cursor"),
    "antigravity": ("Antigravity / Gemini CLI", "gemini", ".gemini"),
    "codex": ("Codex / Copilot (AGENTS.md)", "codex", ".codex"),
}
COMMANDS = ("onboard", "install", "connect", "login", "logout", "disconnect", "mcp", "org", "lint", "doctor", "update", "uninstall", "list")
PROMPTED, SKIPPED = "prompted", "skipped"


def version() -> str:
    try:
        from importlib.metadata import version as _v
        return _v("zoho-skills")
    except Exception:  # not installed as a distribution (dev checkout)
        try:
            return json.loads((adapters.DATA / ".claude-plugin" / "plugin.json").read_text())["version"]
        except (OSError, ValueError, KeyError):
            return "dev"


# ───────────────────────────── helpers ─────────────────────────────
def detect_harnesses(home: Path) -> list:
    return [h for h, (_, exe, cfg) in HARNESS_INFO.items() if shutil.which(exe) or (home / cfg).is_dir()]


def skill_rows() -> list:
    return [(n, n, adapters.parse_skill(n)[0]["description"]) for n in adapters.list_skills()]


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
    skill_names: list = field(default_factory=list)   # explicit skill list (legacy `install`)
    pack_slugs: list = field(default_factory=list)
    harnesses: list = field(default_factory=list)
    project: Optional[Path] = None
    global_scope: bool = True
    url: Optional[str] = None
    region: str = mcp_config.DEFAULT_REGION
    scopes: Optional[list] = None   # Zoho permissions chosen for the post-install sign-in

    @property
    def base(self) -> Path:
        return self.home if self.global_scope else self.project

    @property
    def names(self) -> list:
        """Skill folders to install: explicit list, else core + the skills of the chosen packs."""
        if self.skill_names:
            return self.skill_names
        names = [CORE] if CORE in adapters.list_skills() else []
        for p in packs.discover():
            if p.slug in self.pack_slugs:
                names += [s for s in p.skills if s not in names]
        return names


# ───────────────────────────── wizard steps ─────────────────────────────
# Each step returns PROMPTED (asked the user), SKIPPED (answer came from flags/defaults) or BACK (esc).
def step_skills(st: State) -> object:
    """Legacy `install`: pick raw skill folders."""
    available = adapters.list_skills()
    locked = [CORE] if CORE in available else []
    if st.args.skills:
        st.skill_names = _split(st.args.skills, available, "skill")
        res = SKIPPED
    elif st.tty:
        pick = tui.choose("Choose skills", skill_rows(), multi=True, selected=available, locked=locked,
                          can_back=st.can_back, summary=lambda r: ", ".join(r))
        if pick is BACK:
            return BACK
        st.skill_names, res = pick, PROMPTED
    else:
        st.skill_names, res = list(available), SKIPPED
    if CORE in available and CORE not in st.skill_names:
        st.skill_names = [CORE] + st.skill_names
    return res


def step_harnesses(st: State, step: str = "1/6") -> object:
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


def step_scope(st: State, step: str = "2/6") -> object:
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
        multi=False, can_back=st.can_back, step=step, summary=lambda r: "global" if r == "global" else "project")
    if pick is BACK:
        return BACK
    if pick == "project":
        d = tui.text("Project directory", default=os.getcwd(), hint="'<' to go back", step=step, summary=lambda v: v)
        if d is BACK:
            return BACK
        st.project, st.global_scope = Path(d).expanduser().resolve(), False
    else:
        st.global_scope = True
    return PROMPTED


def step_packs(st: State, step: str = "3/6") -> object:
    available = packs.discover()
    slugs = [p.slug for p in available]
    if st.args.packs:
        st.pack_slugs = _split(st.args.packs, slugs, "pack")
        return SKIPPED
    if st.tty and available:
        rows = [("core", "Core rules", "generic Zoho workflow + safety rules (always installed)")] + [
            (p.slug, p.display_name,
             f"{'built-in' if p.builtin else 'installed'} org pack · matches portal org: {', '.join(p.org_names)}")
            for p in available]
        pick = tui.choose("Choose org packs", rows, multi=True, selected=["core"] + slugs, locked=["core"],
                          can_back=st.can_back, step=step,
                          summary=lambda r: ", ".join(x for x in r if x != "core") or "core only")
        if pick is BACK:
            return BACK
        st.pack_slugs = [x for x in pick if x != "core"]
        return PROMPTED
    st.pack_slugs = slugs
    return SKIPPED


def verify_url(url: str) -> tuple:
    """Read-only reachability check (tools/list). Returns (ok, message) with secrets redacted. A 401 sign-in challenge
    means the server is there; the access picker and browser sign-in follow in the next step."""
    from . import upstream
    try:
        tools = asyncio.run(asyncio.wait_for(upstream.list_tools_once(url), 20))
        return True, f"reachable — {len(tools)} tools (read-only check)"
    except Exception as e:  # noqa: BLE001 — any failure is reported, never raised
        if upstream.is_auth_error(e):
            return True, "reachable — Zoho asks you to sign in (you'll choose access and sign in next)"
        return False, config.redact(upstream.describe_error(e))


def run_login(url: str, scopes: Optional[list], open_browser: bool) -> tuple:
    """Browser OAuth sign-in: opens Zoho's consent page, waits for the redirect back to this terminal, stores the
    token and records what was granted. Returns (ok, message)."""
    import datetime
    from . import auth, upstream
    scopes = scopes or auth.DEFAULT_SCOPES
    print(f"  {S.dim('Requesting ' + str(len(scopes)) + ' Zoho permission(s): ' + ', '.join(scopes))}")
    try:
        n = asyncio.run(auth.login(url, scopes=scopes, open_browser=open_browser, allow_paste=sys.stdin.isatty(),
                                   announce=lambda m: print(f"  {S.accent('›')} {m}")))
    except Exception as e:  # noqa: BLE001
        return False, config.redact(upstream.describe_error(e))
    config.update(signin={"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "scopes": scopes})
    return True, f"signed in — {n} tools visible. Token stored owner-only in {auth.token_path()}"


def guided_url(st: State, step: str) -> object:
    """Official-console walkthrough. Returns a URL, '' to skip, or BACK."""
    region = st.args.region or config.load().get("region")
    if not region:
        keys = list(mcp_config.REGIONS)
        rows = [(r, mcp_config.REGIONS[r].replace("https://", "").rstrip("/"),
                 "India data centre (default)" if r == mcp_config.DEFAULT_REGION else "") for r in keys]
        region = tui.choose("Zoho data centre", rows, multi=False, default_index=keys.index(mcp_config.DEFAULT_REGION),
                            can_back=st.can_back, step=step, summary=lambda r: mcp_config.REGIONS[r])
        if region is BACK:
            return BACK
    st.region = region
    console = mcp_config.console_url(region)
    tui.info(S.bold("Get your MCP URL") + S.dim("  (official Zoho MCP console)"))
    tui.info(f"1. Open {S.accent(console)} and sign in")
    tui.info("2. Create MCP Server → Tools → Add Tools → Zoho Projects, and add at least:")
    tui.info(S.dim("   " + ", ".join(mcp_config.REQUIRED_TOOLS)))
    tui.info("3. Open the Connect tab and copy the MCP URL " + S.dim("(treat it like a password)"))
    print(S.dim("└"))
    nxt = tui.choose("Next", [("open", "Open the console in my browser", ""), ("have", "I already have the URL", ""),
                              ("skip", "Skip — I'll connect later (zoho-skills connect)", "")],
                     multi=False, can_back=True,
                     summary=lambda r: {"open": "opened browser", "have": "have URL", "skip": "skip"}[r])
    if nxt is BACK:
        return BACK
    if nxt == "skip":
        return ""
    if nxt == "open":
        webbrowser.open(console)
    return tui.text("Paste MCP URL", hint="input hidden · enter to skip · '<' back", secret=True, step=step,
                    summary=lambda v: mcp_config.mask_url(v) if v else "skipped")


def step_mcp(st: State, step: str = "4/6") -> object:
    a = st.args
    if a.no_mcp:
        return SKIPPED
    st.region = a.region or config.load().get("region") or mcp_config.DEFAULT_REGION
    url = a.mcp_url or os.environ.get("ZOHO_SKILLS_URL")
    res = SKIPPED
    if not url and st.tty and not config.get_url():
        url = guided_url(st, step)
        if url is BACK:
            return BACK
        res = PROMPTED
    if url:
        try:
            st.url = mcp_config.validate_url(url)
        except mcp_config.McpError as e:
            if st.tty:
                print(f"{S.err('✖')} {e}")
                return step_mcp(st, step)
            raise SystemExit(f"error: {e}")
        if not config.host_matches_region(st.url, st.region):
            print(f"{S.warn('!')} URL host does not look like the {st.region!r} data centre "
                  f"({mcp_config.REGIONS[st.region]}). Double-check the region.")
        if not a.no_verify:
            ok, msg = verify_url(st.url)
            print(f"{S.ok('✔') if ok else S.warn('!')} Zoho MCP: {msg}")
            if not ok and st.tty and not tui.confirm("Save this URL anyway?", default=False):
                st.url = None
                return step_mcp(st, step)
    return res


def step_access(st: State, step: str = "5/6") -> object:
    """Choose which Zoho services/permissions to grant — before the browser sign-in that follows the install."""
    from . import auth
    url = st.url or (None if st.args.no_mcp else config.get_url())
    if not url or not st.tty:
        return SKIPPED
    if auth.is_logged_in(url) and not st.url:
        if not tui.confirm("Already signed in to Zoho. Change the access you granted?", default=False):
            return SKIPPED
    tui.info(S.bold("Zoho access") + S.dim(f"  {step} · you approve this in the browser after the install"))
    st.scopes = pick_scopes(url, numbered=False) or None
    return PROMPTED if st.scopes else SKIPPED


def plan_rows(st: State) -> list:
    return [("Harnesses", ", ".join(HARNESS_INFO[h][0] for h in st.harnesses)),
            ("Skills", ", ".join(st.names)),
            ("Scope", f"global · {st.home}" if st.global_scope else f"project · {st.project}"),
            ("MCP", ("one entry `zoho-skills mcp` per harness · Zoho " + mcp_config.mask_url(st.url))
             if st.url else ("one entry `zoho-skills mcp` per harness"
                             if not st.args.no_mcp else "skipped")),
            *([("Zoho login", f"{len(st.scopes)} permission(s) requested · browser sign-in after install")]
              if st.scopes else [])]


def step_review(st: State) -> object:
    if not st.tty:
        return SKIPPED
    tui.box([f"{S.dim(k.ljust(10))} {v}" for k, v in plan_rows(st)], title="Review")
    pick = tui.choose("Ready?", [("go", "Install now", ""), ("back", "Go back and change something", ""),
                                 ("cancel", "Cancel", "nothing will be written")],
                      multi=False, can_back=True, step="6/6",
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
                sp.warn(f"{label}: skills skipped for --global (Cursor user rules live in its settings; "
                        "use a project install)")
            elif dry_run:
                sp.ok(f"{label}: would install {', '.join(st.names)} under {st.base}")
            else:
                written = adapters.install(h, st.names, st.base, global_scope=st.global_scope)
                sp.ok(f"{label}: {len(written)} file(s) → {_short(written[0].parent, st.home)}")


def register_entries(st: State, dry_run: bool) -> int:
    from . import harnesses
    errors = 0
    for h in st.harnesses:
        label = HARNESS_INFO[h][0]
        with tui.Spinner(f"{label}: adding MCP entry") as sp:
            try:
                sp.ok(f"{label} MCP — {harnesses.register(h, home=st.home, dry_run=dry_run)}")
            except harnesses.HarnessError as e:
                errors += 1
                sp.fail(f"{label} MCP — {e}")
    return errors


def finish(st: State, errors: int) -> None:
    steps = []
    if st.url or config.get_url():
        steps.append("Restart your harness so it starts the " + S.bold("zoho-skills") + " MCP server")
        from . import auth
        if not auth.is_logged_in(st.url or config.get_url()):
            steps.append(f"Sign in to Zoho:  {S.bold('zoho-skills login')}")
    else:
        steps.append(f"Connect Zoho:  {S.bold('zoho-skills connect')}")
    steps.append("Try it (read-only): " + S.dim("“list my Zoho portals, then the latest 5 tasks”"))
    steps.append(f"Health check any time:  {S.bold('zoho-skills doctor')}")
    print()
    tui.box([f"{S.accent(str(i))}  {t}" for i, t in enumerate(steps, 1)],
            title="All set" if not errors else "Finished with issues", color=S.ok if not errors else S.warn)
    print()


def _flow(a: argparse.Namespace, steps: list) -> tuple:
    st = State(a, Path.home(), tty=tui.interactive() and not a.yes)
    if st.tty:
        tui.banner(version())
    run_wizard(steps, st)
    if a.dry_run and not st.tty:
        tui.box([f"{S.dim(k.ljust(10))} {v}" for k, v in plan_rows(st)], title="Plan (dry run)")
    if st.tty:
        print()
    return st


def sign_in_after(st: State) -> None:
    """Run the browser sign-in with the permissions chosen in the access step (interactive runs only)."""
    url = st.url or config.get_url()
    if not (st.scopes and url):
        return
    ok, msg = run_login(url, st.scopes, True)
    print(f"{S.ok('✔') if ok else S.warn('!')} Zoho sign-in — {msg}"
          + ("" if ok else f"\n  {S.dim('retry any time: zoho-skills login')}"))


def cmd_onboard(a: argparse.Namespace) -> int:
    st = _flow(a, [step_harnesses, step_scope, step_packs, step_mcp, step_access, step_review])
    install_skills(st, a.dry_run)
    errors = 0
    if not a.no_mcp:
        if st.url and not a.dry_run:
            config.update(url=st.url, region=st.region)
            print(f"{S.ok('✔')} Zoho URL saved to {_short(config.config_path(), st.home)} {S.dim('(owner-only, never in harness configs)')}")
        elif st.url:
            print(f"{S.dim('·')} would save the Zoho URL to {_short(config.config_path(), st.home)}")
        elif not a.dry_run and not config.get_url():
            config.update(region=st.region)
        errors = register_entries(st, a.dry_run)
    if a.dry_run:
        print(f"\n  {S.dim('dry run — nothing was written.')}")
        return 0
    sign_in_after(st)
    finish(st, errors)
    return 1 if errors else 0


def cmd_install(a: argparse.Namespace) -> int:
    """Skills only (no MCP entries) — for CI / dotfiles."""
    a.no_mcp, a.region, a.mcp_url, a.packs, a.no_verify = True, None, None, None, True
    st = _flow(a, [step_skills, step_harnesses, step_scope, step_review])
    install_skills(st, a.dry_run)
    if a.dry_run:
        print(f"\n  {S.dim('dry run — nothing was written.')}")
        return 0
    finish(st, 0)
    return 0


def cmd_connect(a: argparse.Namespace) -> int:
    """(Re)set the Zoho MCP URL used by the server. Harness entries are untouched."""
    a.no_mcp = False
    st = State(a, Path.home(), tty=tui.interactive() and not a.yes)
    if st.tty:
        tui.banner(version())
    run_wizard([lambda s: step_mcp(s, "1/2"), lambda s: step_access(s, "2/2")], st)
    if not st.url:
        print(f"  Create your MCP server at {mcp_config.console_url(a.region or config.region())} "
              "(Connect tab → copy URL), then run: zoho-skills connect --mcp-url <url>")
        return 1
    if a.dry_run:
        print(f"  {S.dim('·')} would save the URL to {config.config_path()}")
        return 0
    config.update(url=st.url, region=st.region)
    from . import auth
    print(f"\n  {S.ok('Done.')} URL saved (owner-only).")
    sign_in_after(st)
    if auth.is_logged_in(st.url):
        print("  Restart your harness to reconnect.\n")
    else:
        print(f"  Next: {S.bold('zoho-skills login')} {S.dim('(Zoho needs a one-time browser sign-in)')}\n")
    return 0


def cmd_serve(_: argparse.Namespace) -> int:
    from . import mcp_server  # lazy: needs the `mcp` SDK
    return mcp_server.main()


def cmd_lint(a: argparse.Namespace) -> int:
    task = json.load(sys.stdin)
    pack = packs.match(a.org)
    if not pack:
        print("no org pack matched; pass --org NAME (see: zoho-skills org list)", file=sys.stderr)
        return 2
    res = packs.lint(pack, task)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"{pack.display_name} — estimated score (heuristic): {res['score']}")
        for kind, items in (("ERROR", res["errors"]), ("WARN", res["warnings"]), ("note", res["notes"])):
            for m in items:
                print(f"{kind:5} {m}")
    return 1 if res["errors"] else 0


def cmd_org(a: argparse.Namespace) -> int:
    from . import orgs
    if a.org_cmd == "list":
        for o in orgs.list_orgs():
            print(f"{S.bold(o['slug'])}  {o['display_name']}  v{o['version'] or '?'}  "
                  f"{S.dim('built-in' if o['builtin'] else str(o['path']))}")
        return 0
    try:
        if a.org_cmd == "add":
            p = orgs.add(a.source, dry_run=a.dry_run)
            print(f"{S.ok('✔')} {'would add' if a.dry_run else 'added'} pack {p.slug} ({p.display_name})")
            print(S.dim("  note: the pack's lint code runs locally when you lint — only add packs you trust."))
        elif a.org_cmd == "update":
            for line in orgs.update(a.slug, dry_run=a.dry_run):
                print(line)
        elif a.org_cmd == "remove":
            print(orgs.remove(a.slug, dry_run=a.dry_run))
    except (packs.PackError, OSError, ValueError, RuntimeError) as e:
        print(f"{S.err('✖')} {e}", file=sys.stderr)
        return 1
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    for name, _, desc in skill_rows():
        print(f"{S.bold(name)}\n  {S.dim(tui.clip(desc, tui.cols() - 4))}")
    print("\nharnesses: " + ", ".join(adapters.HARNESSES))
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    from . import doctor
    checks = doctor.run_checks(Path.home(), upstream_check=not a.offline)
    marks = {"ok": S.ok("✔"), "warn": S.warn("!"), "fail": S.err("✖"), "skip": S.dim("–")}
    home = str(Path.home())
    width = tui.cols() - 8
    rows = [tui.clip(f"{marks[c.status]} {c.name.ljust(20)} {c.detail.replace(home, '~')}", width + 12) for c in checks]
    print()
    tui.box(rows, title=f"zoho-skills doctor · v{version()}")
    fixes = [c for c in checks if c.fix and c.status in ("warn", "fail")]
    if fixes:
        print("\n  " + S.bold("Fix:"))
        for c in fixes:
            print(f"   {S.accent('›')} {c.name}: {c.fix}")
    print()
    return 1 if any(c.status == "fail" for c in checks) else 0


def pick_scopes(url: str, numbered: bool = True) -> object:
    """Interactive access picker: which Zoho services, at what level. Returns a scope list or BACK/None on cancel."""
    from . import auth
    with tui.Spinner("Reading the permissions your Zoho MCP server offers") as sp:
        offered = auth.fetch_supported_scopes(url)
        svcs = auth.services(offered)
        sp.ok(f"{len(offered)} permissions across {len(svcs)} service(s)")
    rows = [(k, auth.service_label(k), f"{len(v)} permission(s): " + ", ".join(sorted({auth.split_scope(x)[1] for x in v}))[:90])
            for k, v in svcs.items()]
    chosen = tui.choose("Which Zoho services may zoho-skills use?", rows, multi=True,
                        selected=[k for k in svcs if k == "zohoprojects"], can_back=False, step="1/2" if numbered else "",
                        summary=lambda ks: ", ".join(auth.service_label(k) for k in ks) or "none")
    if not chosen:
        return None
    level = tui.choose("Access level", [(k, v[0], v[1]) for k, v in auth.LEVELS.items()], multi=False,
                       default_index=1, can_back=False, step="2/2" if numbered else "", summary=lambda k: auth.LEVELS[k][0])
    scopes = auth.select(offered, chosen, "standard" if level == "custom" else level)
    if level == "custom":
        pool = [sc for sc in offered if auth.split_scope(sc)[0] in chosen and not auth.is_core(sc)]
        picked = tui.choose("Permissions", [(sc, sc, "") for sc in pool], multi=True,
                            selected=[sc for sc in scopes if sc in pool], can_back=False,
                            summary=lambda ks: f"{len(ks)} selected")
        scopes = [sc for sc in offered if auth.is_core(sc)] + list(picked)
    print(f"  {S.dim('ZohoMCP.tool.execute is always requested — without it the server cannot run any tool.')}")
    return scopes


def cmd_login(a: argparse.Namespace) -> int:
    """Sign in to Zoho (OAuth, in the browser). Needed once; tokens refresh automatically afterwards."""
    from . import auth
    url = config.get_url()
    if not url:
        print(f"  No Zoho MCP URL yet. Create one at {mcp_config.console_url(config.region())}, then: "
              "zoho-skills connect")
        return 1
    scopes = a.scopes.split(",") if a.scopes else None
    if scopes is None and (a.level or a.services):
        offered = auth.fetch_supported_scopes(url)
        svcs = a.services.split(",") if a.services else ["zohoprojects"]
        unknown = [x for x in svcs if x not in auth.services(offered)]
        if unknown or (a.level or "standard") not in ("read", "standard", "full"):
            print(f"{S.err('✖')} services: {', '.join(auth.services(offered))}; levels: read, standard, full", file=sys.stderr)
            return 2
        scopes = auth.select(offered, svcs, a.level or "standard")
    elif scopes is None and tui.interactive() and not a.yes:
        scopes = pick_scopes(url)
        if not scopes:
            print("cancelled — nothing requested.")
            return 1
    ok, msg = run_login(url, scopes, not a.no_browser)
    print(f"  {S.ok('✔') if ok else S.err('✖')} {msg}")
    if ok:
        print(f"  {S.dim('Restart your harness so it picks up the session.')}")
    return 0 if ok else 1


def cmd_logout(a: argparse.Namespace) -> int:
    """Forget the stored Zoho URL (it is the credential). Harness entries and skills stay; the server then serves
    org rules only until `zoho-skills connect`."""
    from . import auth
    cfg = config.load()
    if not cfg.get("url") and not auth.token_path().exists():
        print("  not logged in — no Zoho URL stored" + (" (ZOHO_SKILLS_URL is set in your environment)"
                                                       if os.environ.get("ZOHO_SKILLS_URL") else "."))
        return 0
    if a.dry_run:
        print(f"  {S.dim('·')} would remove the stored Zoho URL and sign-in tokens")
        return 0
    if not a.yes and tui.interactive() and not tui.confirm("Remove the stored Zoho URL and sign-in tokens?", default=True):
        print("cancelled.")
        return 1
    cfg.pop("url", None)
    cfg.pop("signin", None)
    if config.config_path().exists():
        config.save(cfg)
    auth.logout()
    print(f"  {S.ok('✔')} logged out — Zoho URL and sign-in tokens removed. Reconnect any time: {S.bold('zoho-skills connect')}")
    print(f"  {S.dim('Revoke the MCP server in the Zoho console (' + mcp_config.console_url(config.region()) + ') to invalidate the key itself.')}")
    return 0


def cmd_disconnect(a: argparse.Namespace) -> int:
    """Remove the zoho-skills MCP entry from harnesses; skills stay installed. --logout also forgets the URL."""
    from . import harnesses
    home = Path.home()
    targets = _split(a.harness, adapters.HARNESSES, "harness") if a.harness else adapters.HARNESSES
    errors = 0
    for h in targets:
        try:
            print(f"{S.ok('✔')} {HARNESS_INFO[h][0]} MCP — {harnesses.unregister(h, home=home, dry_run=a.dry_run)}")
        except harnesses.HarnessError as e:
            errors += 1
            print(f"{S.err('✖')} {HARNESS_INFO[h][0]} MCP — {e}")
    if a.logout:
        cmd_logout(argparse.Namespace(yes=a.yes, dry_run=a.dry_run))
    if not a.dry_run:
        print(f"\n  Restart your harness. Re-add later with: {S.bold('zoho-skills onboard')}\n")
    return 1 if errors else 0


def _installed_global_harnesses(home: Path) -> list:
    return [h for h, (_, glob) in adapters.SKILL_DIRS.items() if (home / glob / CORE).is_dir()]


REPO_SLUG = "cr-arunkumar/creole-zoho-skills"


def _vtuple(v: str) -> tuple:
    """'v0.2.10' -> (0, 2, 10); unparsable parts become 0."""
    return tuple(int(x) if x.isdigit() else 0 for x in v.lstrip("v").split(".")[:3])


def latest_release() -> Optional[str]:
    """Latest GitHub release tag (e.g. 'v0.2.7'), or None if it can't be read. GitHub, not npm: it is published
    automatically by CI and needs no approval."""
    try:
        import httpx
        r = httpx.get(f"https://api.github.com/repos/{REPO_SLUG}/releases/latest", timeout=10)
        tag = r.json().get("tag_name")
        return tag if isinstance(tag, str) and tag.startswith("v") else None
    except Exception:  # noqa: BLE001 — offline / rate-limited: caller falls back
        return None


def cmd_update(a: argparse.Namespace) -> int:
    """Upgrade to the latest GitHub release, refresh org packs and re-copy installed skills."""
    before, home = version(), Path.home()
    if not a.skills_only:
        latest = latest_release()
        if a.check:
            state = ("up to date" if latest and _vtuple(latest) <= _vtuple(before)
                     else f"update available: {latest}" if latest else "could not read the latest release")
            print(f"zoho-skills {before} — {state}")
            return 0
        uv = shutil.which("uv")
        if not (uv and subprocess.run([uv, "tool", "list"], capture_output=True, text=True).stdout.count("zoho-skills")):
            print("Not installed with uv here. Update with: curl -fsSL https://raw.githubusercontent.com/"
                  f"{REPO_SLUG}/main/install.sh | sh   (or: npx --yes --prefer-online zoho-skills@latest)")
            return 1
        if latest and _vtuple(latest) <= _vtuple(before):
            print(f"{S.ok('✔')} already on the latest release ({latest})")
        else:
            wheel = (f"https://github.com/{REPO_SLUG}/releases/download/{latest}/zoho_skills-{latest[1:]}-py3-none-any.whl"
                     if latest else None)
            ok = bool(wheel) and subprocess.run([uv, "tool", "install", "--force", wheel]).returncode == 0
            if not ok and subprocess.run([uv, "tool", "upgrade", "zoho-skills"]).returncode != 0:
                print(f"{S.err('✖')} upgrade failed (network?). Try: uv tool install --force git+https://github.com/{REPO_SLUG}")
                return 1
    # after an upgrade run the freshly installed binary (this process is the old version); else this interpreter
    exe = [shutil.which("zoho-skills")] if not a.skills_only and shutil.which("zoho-skills") else [sys.executable, "-m", "zoho_skills"]
    after = subprocess.run([*exe, "--version"], capture_output=True, text=True).stdout.strip() or f"zoho-skills {before}"
    print(f"{S.ok('✔')} {after}" + (S.dim(f"  (was {before})") if f"zoho-skills {before}" != after else ""))
    for line in (subprocess.run([*exe, "org", "update"], capture_output=True, text=True).stdout.splitlines() if not a.skills_only else []):
        print(f"  {line}")
    for h in _installed_global_harnesses(home):
        r = subprocess.run([*exe, "install", "--yes", "--harness", h, "--global"], capture_output=True, text=True)
        print(f"{S.ok('✔') if r.returncode == 0 else S.err('✖')} {HARNESS_INFO[h][0]}: skills refreshed")
    print(f"  {S.dim('Restart your harness to load the new MCP server.')}")
    return 0


def cmd_uninstall(a: argparse.Namespace) -> int:
    from . import harnesses
    home = Path.home()
    targets = _split(a.harness, adapters.HARNESSES, "harness") if a.harness else adapters.HARNESSES
    project = Path(a.project).expanduser().resolve() if a.project else None
    base, glob = (project, False) if project else (home, True)
    names = adapters.list_skills()
    print(S.bold("This removes:") + " the zoho-skills MCP entry and installed skills for "
          + ", ".join(targets) + (" (and ~/.zoho-skills with --purge)" if a.purge else ""))
    if not a.yes and not a.dry_run and tui.interactive() and not tui.confirm("Continue?", default=False):
        print("cancelled — nothing removed.")
        return 1
    for h in targets:
        try:
            print(f"{S.ok('✔')} {HARNESS_INFO[h][0]} MCP — {harnesses.unregister(h, home=home, dry_run=a.dry_run)}")
        except harnesses.HarnessError as e:
            print(f"{S.err('✖')} {HARNESS_INFO[h][0]} MCP — {e}")
        if a.dry_run:
            print(f"{S.dim('·')} {HARNESS_INFO[h][0]}: would remove installed skills")
        else:
            for p in adapters.uninstall(h, names, base, global_scope=glob):
                print(f"{S.ok('✔')} removed {_short(p, home)}")
    if a.purge and not a.dry_run:
        d = config.config_dir()
        if d.exists() and (a.yes or not tui.interactive() or tui.confirm(f"Delete {d} (config, packs, history)?", False)):
            shutil.rmtree(d)
            print(f"{S.ok('✔')} removed {d}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="zoho-skills", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"zoho-skills {version()}")
    sub = ap.add_subparsers(dest="cmd")

    def common(p, *, mcp: bool) -> None:
        p.add_argument("--harness", help=f"comma list of {', '.join(adapters.HARNESSES)} or 'all'")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--global", dest="global_scope", action="store_true", help="install under $HOME (default)")
        g.add_argument("--project", metavar="DIR", help="install skills into this project directory")
        p.add_argument("-y", "--yes", action="store_true", help="no prompts; use flags/defaults")
        p.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
        if mcp:
            p.add_argument("--packs", help="comma list of org pack slugs (default: all installed)")
            p.add_argument("--mcp-url", help="Zoho MCP URL (or env ZOHO_SKILLS_URL); stored only in ~/.zoho-skills")
            p.add_argument("--region", choices=list(mcp_config.REGIONS), help="Zoho data centre (default: in)")
            p.add_argument("--no-mcp", action="store_true", help="skip MCP entries and the Zoho URL")
            p.add_argument("--no-verify", action="store_true", help="don't test the URL with a read-only tools/list")

    on = sub.add_parser("onboard", help="guided onboarding (default)")
    common(on, mcp=True)
    ins = sub.add_parser("install", help="skills only, no MCP (CI / dotfiles)")
    common(ins, mcp=False)
    ins.add_argument("--skills", help="comma list or 'all'")
    c = sub.add_parser("connect", help="(re)set the Zoho MCP URL")
    c.add_argument("--mcp-url")
    c.add_argument("--region", choices=list(mcp_config.REGIONS))
    c.add_argument("--no-verify", action="store_true")
    c.add_argument("-y", "--yes", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    li = sub.add_parser("login", help="sign in to Zoho (OAuth in your browser)")
    li.add_argument("--scopes", help="comma list of OAuth scopes (default: least-privilege set, no deletes)")
    li.add_argument("--services", help="comma list of services to allow, e.g. zohoprojects,workdrive (default: zohoprojects)")
    li.add_argument("--level", choices=["read", "standard", "full"],
                    help="access level: read | standard (read + create/update work items) | full (incl. delete)")
    li.add_argument("-y", "--yes", action="store_true", help="no prompts; use the default least-privilege set")
    li.add_argument("--no-browser", action="store_true", help="print the authorisation URL instead of opening it")
    lo = sub.add_parser("logout", help="forget the stored Zoho URL and sign-in")
    dc = sub.add_parser("disconnect", help="remove the MCP entry from harnesses (keeps skills)")
    dc.add_argument("--harness")
    dc.add_argument("--logout", action="store_true", help="also forget the stored Zoho URL")
    for x in (lo, dc):
        x.add_argument("-y", "--yes", action="store_true")
        x.add_argument("--dry-run", action="store_true")
    sub.add_parser("mcp", help="run the MCP server (stdio): org rules + gated Zoho proxy")
    o = sub.add_parser("org", help="manage org rule packs")
    osub = o.add_subparsers(dest="org_cmd", required=True)
    osub.add_parser("list")
    oa = osub.add_parser("add")
    oa.add_argument("source", help="local dir, https git URL, or owner/repo")
    ou = osub.add_parser("update")
    ou.add_argument("slug", nargs="?")
    orr = osub.add_parser("remove")
    orr.add_argument("slug")
    for x in (oa, ou, orr):
        x.add_argument("--dry-run", action="store_true")
    ln = sub.add_parser("lint", help="lint a task JSON from stdin with an org pack")
    ln.add_argument("--org", help="org name or pack slug")
    ln.add_argument("--json", action="store_true")
    d = sub.add_parser("doctor", help="check uv/python, config, harness entries and Zoho reachability")
    d.add_argument("--offline", action="store_true", help="skip the read-only upstream check")
    up = sub.add_parser("update", help="upgrade zoho-skills, org packs and installed skills")
    up.add_argument("--skills-only", action="store_true", help="skip the upgrade; just refresh installed skills")
    up.add_argument("--check", action="store_true", help="only report whether a newer release exists")
    u = sub.add_parser("uninstall", help="remove our MCP entries and installed skills")
    u.add_argument("--harness")
    u.add_argument("--project", metavar="DIR")
    u.add_argument("--purge", action="store_true", help="also delete ~/.zoho-skills (config, packs, history)")
    u.add_argument("-y", "--yes", action="store_true")
    u.add_argument("--dry-run", action="store_true")
    sub.add_parser("list", help="list skills and harnesses")
    return ap


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "onboard")
    a = build_parser().parse_args(argv)
    handlers = {"onboard": cmd_onboard, "install": cmd_install, "connect": cmd_connect, "login": cmd_login, "logout": cmd_logout,
                "disconnect": cmd_disconnect, "mcp": cmd_serve,
                "org": cmd_org, "lint": cmd_lint, "doctor": cmd_doctor, "update": cmd_update,
                "uninstall": cmd_uninstall, "list": cmd_list}
    try:
        return handlers[a.cmd](a)
    except KeyboardInterrupt:
        print(f"\n{S.dim('│')}\n{S.dim('└')} cancelled — nothing was written after this point.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
