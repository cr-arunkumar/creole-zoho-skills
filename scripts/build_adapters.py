#!/usr/bin/env python3
"""Regenerate the committed in-repo adapters from skills/ so they never drift.

  python3 scripts/build_adapters.py          # write .claude/skills, .agent/skills, .cursor/rules, AGENTS.md block
  python3 scripts/build_adapters.py --check  # exit 1 if committed adapters are stale (use in CI)

skills/ is the single source of truth; never hand-edit the generated copies.
"""
from __future__ import annotations

import argparse
import filecmp
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adapters  # noqa: E402


def build(dest: Path) -> None:
    names = adapters.list_skills()
    for n in names:
        adapters.parse_skill(n)
    # Only the three adapter folders are generated. Root AGENTS.md / GEMINI.md are hand-written and
    # point at skills/ directly, so they are never touched here.
    for harness in ("claude", "antigravity"):
        root = dest / adapters.SKILL_DIRS[harness][0]
        root.mkdir(parents=True, exist_ok=True)
        for n in names:
            adapters.copy_skill(n, root)
    adapters.write_cursor(names, dest / ".cursor" / "rules")


def _same(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(_same(a / d, b / d) for d in cmp.common_dirs)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if not a.check:
        build(adapters.REPO)
        print("adapters regenerated")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        build(t)
        stale = [d for d in (".claude/skills", ".agent/skills", ".cursor/rules")
                 if not (adapters.REPO / d).exists() or not _same(t / d, adapters.REPO / d)]
    if stale:
        print("stale adapters: " + ", ".join(stale) + " — run: python3 scripts/build_adapters.py", file=sys.stderr)
        return 1
    print("adapters up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
