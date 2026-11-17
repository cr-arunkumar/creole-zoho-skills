"""Shared logic for turning skills/ (open Agent Skills format) into per-harness layouts. Standard library only."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / "skills"
MARK_START = "<!-- creole-zoho-skills:start -->"
MARK_END = "<!-- creole-zoho-skills:end -->"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")

# harness -> (project-relative skills dir, global skills dir relative to $HOME)
SKILL_DIRS = {
    "claude": (".claude/skills", ".claude/skills"),
    "antigravity": (".agent/skills", ".gemini/antigravity/skills"),
    "codex": (".agents/skills", ".codex/skills"),
}
HARNESSES = ["claude", "cursor", "antigravity", "codex"]


def list_skills() -> list[str]:
    return sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))


def parse_skill(name: str) -> tuple[dict, str]:
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{name}/SKILL.md has no frontmatter")
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    if not meta.get("name") or not meta.get("description"):
        raise ValueError(f"{name}/SKILL.md frontmatter needs name and description")
    if meta["name"] != name:
        raise ValueError(f"frontmatter name {meta['name']!r} != folder {name!r}")
    return meta, m.group(2).lstrip("\n")


def copy_skill(name: str, dest_root: Path) -> Path:
    dest = dest_root / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SKILLS_DIR / name, dest, ignore=IGNORE)
    return dest


def render_mdc(name: str) -> str:
    """Cursor rule: description-triggered (agent-requested), body + references inlined (rules can't follow relative links)."""
    meta, body = parse_skill(name)
    desc = meta["description"].replace('"', "'")
    parts = [f'---\ndescription: "{desc}"\nglobs:\nalwaysApply: false\n---\n', body]
    for ref in sorted((SKILLS_DIR / name / "references").glob("*.md")):
        parts.append(f"\n\n---\n<!-- reference: {name}/references/{ref.name} -->\n{ref.read_text(encoding='utf-8')}")
    scripts = SKILLS_DIR / name / "scripts"
    if scripts.is_dir():
        parts.append(f"\n\n(Helper scripts for this skill live in the repo at skills/{name}/scripts/.)\n")
    return "".join(parts)


def write_cursor(names: list[str], rules_dir: Path) -> list[Path]:
    rules_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for n in names:
        p = rules_dir / f"{n}.mdc"
        p.write_text(render_mdc(n), encoding="utf-8")
        out.append(p)
    return out


def agents_block(names: list[str], skills_rel: str) -> str:
    lines = [MARK_START, "## Zoho Projects automation (creole-zoho-skills)", "",
             "When the task involves Zoho Projects, first read the core skill, then the org skill that matches the "
             "Zoho portal's organisation. Org rules override core defaults. Never write to Zoho without a dry-run and "
             "explicit user confirmation.", ""]
    for n in names:
        meta, _ = parse_skill(n)
        lines.append(f"- `{skills_rel}/{n}/SKILL.md` — {meta['description']}")
    lines += ["", MARK_END, ""]
    return "\n".join(lines)


def upsert_block(file: Path, block: str) -> None:
    """Insert or replace our managed block, leaving the rest of the file untouched."""
    file.parent.mkdir(parents=True, exist_ok=True)
    text = file.read_text(encoding="utf-8") if file.exists() else ""
    pat = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END) + r"\n?", re.S)
    if pat.search(text):
        text = pat.sub(lambda _: block, text)
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    file.write_text(text, encoding="utf-8")


def install(harness: str, names: list[str], base: Path, *, global_scope: bool) -> list[Path]:
    """base = $HOME for global scope, or the target project directory."""
    written: list[Path] = []
    if harness == "cursor":
        if global_scope:
            raise SystemExit("Cursor user rules are managed in Cursor settings; use --project DIR for .cursor/rules")
        return write_cursor(names, base / ".cursor" / "rules")
    proj_rel, glob_rel = SKILL_DIRS[harness]
    root = base / (glob_rel if global_scope else proj_rel)
    root.mkdir(parents=True, exist_ok=True)
    written += [copy_skill(n, root) for n in names]
    if harness in ("codex", "antigravity"):
        agents = base / ".codex" / "AGENTS.md" if (global_scope and harness == "codex") else \
            base / ("GEMINI.md" if harness == "antigravity" and not global_scope else "AGENTS.md")
        if global_scope and harness == "antigravity":
            return written  # Antigravity reads global skills from its skills dir directly
        rel = str(root) if global_scope else proj_rel
        upsert_block(agents, agents_block(names, rel))
        written.append(agents)
    return written
