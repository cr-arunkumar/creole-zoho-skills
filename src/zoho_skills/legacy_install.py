#!/usr/bin/env python3
"""Install the Zoho skills into an AI harness. Standard library only.

  python3 scripts/install.py --harness claude --global
  python3 scripts/install.py --harness all --project ~/code/my-app
  python3 scripts/install.py --harness cursor --project . --skills zoho-projects-core,creole-studios-zoho
  python3 scripts/install.py --harness all --project . --dry-run
Harnesses: claude | cursor | antigravity | codex (Codex/Copilot/others via AGENTS.md) | all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


from . import adapters


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--harness", required=True, choices=adapters.HARNESSES + ["all"])
    scope = ap.add_mutually_exclusive_group(required=True)
    scope.add_argument("--global", dest="global_scope", action="store_true", help="install under $HOME")
    scope.add_argument("--project", metavar="DIR", help="install into this project directory")
    ap.add_argument("--skills", default="all", help="comma list of skill names, or 'all' (default)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be written; change nothing")
    a = ap.parse_args(argv)

    available = adapters.list_skills()
    names = available if a.skills == "all" else [s.strip() for s in a.skills.split(",") if s.strip()]
    bad = [n for n in names if n not in available]
    if bad:
        print(f"unknown skill(s): {', '.join(bad)}. available: {', '.join(available)}", file=sys.stderr)
        return 2
    if "zoho-projects-core" in available and "zoho-projects-core" not in names:
        names = ["zoho-projects-core"] + names  # org skills require the core skill
    for n in names:
        adapters.parse_skill(n)  # validate frontmatter before writing anything

    base = Path.home() if a.global_scope else Path(a.project).expanduser().resolve()
    targets = adapters.HARNESSES if a.harness == "all" else [a.harness]
    if a.global_scope and "cursor" in targets and a.harness == "all":
        targets = [t for t in targets if t != "cursor"]
        print("note: skipping cursor for --global (Cursor user rules live in its settings)")
    for h in targets:
        if a.dry_run:
            print(f"[dry-run] {h}: would install {', '.join(names)} under {base}")
            continue
        for p in adapters.install(h, names, base, global_scope=a.global_scope):
            print(f"{h}: wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
