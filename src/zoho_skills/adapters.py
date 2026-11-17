"""Shared logic for turning skills/ (open Agent Skills format) into per-harness layouts. Standard library only."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

PKG = Path(__file__).resolve().parent
# Installed wheel: data is bundled under _data/. Dev checkout: the repo root two levels up.
DATA = PKG / "_data" if (PKG / "_data").is_dir() else PKG.parents[1]
REPO = DATA
SKILLS_DIR = DATA / "skills"
PACKS_DIR = DATA / "packs"
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


def user_orgs_dir() -> Path:
    return Path.home() / ".zoho-skills" / "orgs"


def skill_roots(user: bool = True) -> list[Path]:
    """Directories that hold skill folders: core, built-in packs and (optionally) the user's installed packs."""
    roots = [SKILLS_DIR] + sorted(PACKS_DIR.glob("*/skills"))
    if user:
        roots += sorted(user_orgs_dir().glob("*/skills"))
    return roots


def skill_map(user: bool = True) -> dict:
    return {p.parent.name: p.parent for root in skill_roots(user) for p in root.glob("*/SKILL.md")}


def skill_path(name: str, user: bool = True) -> Path:
    try:
        return skill_map(user)[name]
    except KeyError:
        raise ValueError(f"unknown skill {name!r}") from None


def list_skills(user: bool = True) -> list[str]:
    return sorted(skill_map(user))


def parse_skill(name: str) -> tuple[dict, str]:
    text = (skill_path(name) / "SKILL.md").read_text(encoding="utf-8")
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
    shutil.copytree(skill_path(name), dest, ignore=IGNORE)
    return dest


def render_mdc(name: str) -> str:
    """Cursor rule: description-triggered (agent-requested), body + references inlined (rules can't follow relative links)."""
    meta, body = parse_skill(name)
    desc = meta["description"].replace('"', "'")
    parts = [f'---\ndescription: "{desc}"\nglobs:\nalwaysApply: false\n---\n', body]
    for ref in sorted((skill_path(name) / "references").glob("*.md")):
        parts.append(f"\n\n---\n<!-- reference: {name}/references/{ref.name} -->\n{ref.read_text(encoding='utf-8')}")
    scripts = skill_path(name) / "scripts"
    if scripts.is_dir():
        parts.append(f"\n\n(Helper scripts for this skill ship with the installed skill folder ({name}/scripts/).)\n")
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


def remove_block(file: Path) -> bool:
    """Remove our managed block from an AGENTS.md-style file, leaving the rest untouched. Returns True if changed."""
    if not file.exists():
        return False
    text = file.read_text(encoding="utf-8")
    pat = re.compile(r"\n*" + re.escape(MARK_START) + r".*?" + re.escape(MARK_END) + r"\n?", re.S)
    new = pat.sub("\n", text).strip("\n")
    if new == text.strip("\n"):
        return False
    if new:
        file.write_text(new + "\n", encoding="utf-8")
    else:
        file.unlink()  # the file only ever held our block
    return True


def uninstall(harness: str, names: list[str], base: Path, *, global_scope: bool) -> list[Path]:
    """Remove what `install` wrote for these skill names. Returns the paths removed/changed."""
    removed: list[Path] = []
    if harness == "cursor":
        for n in names:
            p = base / ".cursor" / "rules" / f"{n}.mdc"
            if p.exists():
                p.unlink()
                removed.append(p)
        return removed
    proj_rel, glob_rel = SKILL_DIRS[harness]
    root = base / (glob_rel if global_scope else proj_rel)
    for n in names:
        if (root / n).is_dir():
            shutil.rmtree(root / n)
            removed.append(root / n)
    if harness in ("codex", "antigravity") and not (global_scope and harness == "antigravity"):
        agents = base / ".codex" / "AGENTS.md" if (global_scope and harness == "codex") else \
            base / ("GEMINI.md" if harness == "antigravity" else "AGENTS.md")
        if remove_block(agents):
            removed.append(agents)
    return removed
