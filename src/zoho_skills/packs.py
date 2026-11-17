"""Org rule packs: a folder with pack.json + skills. Built-in packs ship in <data>/packs; the user's live in
~/.zoho-skills/orgs/<slug>/. A pack supplies the org's lint function, its rule documents and its final status."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import adapters

REQUIRED = ("slug", "display_name", "org_names")


class PackError(Exception):
    pass


@dataclass
class Pack:
    slug: str
    display_name: str
    org_names: list
    path: Path
    skills: list = field(default_factory=list)
    lint_path: Optional[Path] = None
    final_status: str = ""
    resources: list = field(default_factory=list)
    builtin: bool = False
    version: str = ""


def load_pack(path: Path, builtin: bool = False) -> Pack:
    mf = path / "pack.json"
    try:
        raw = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PackError(f"{mf}: cannot read pack.json ({e})") from e
    missing = [k for k in REQUIRED if not raw.get(k)]
    if missing:
        raise PackError(f"{mf}: missing {', '.join(missing)}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", raw["slug"]):
        raise PackError(f"{mf}: slug must be lowercase letters, digits and dashes")
    if not isinstance(raw["org_names"], list):
        raise PackError(f"{mf}: org_names must be a list")
    lint = raw.get("lint")
    lint_path = (path / lint).resolve() if lint else None
    if lint_path and (path.resolve() not in lint_path.parents or not lint_path.is_file()):
        raise PackError(f"{mf}: lint entry must be a file inside the pack")
    return Pack(slug=raw["slug"], display_name=raw["display_name"], org_names=list(raw["org_names"]), path=path,
                skills=list(raw.get("skills", [])), lint_path=lint_path, final_status=raw.get("final_status", ""),
                resources=list(raw.get("resources", [])), builtin=builtin, version=str(raw.get("version", "")))


def discover(user: bool = True) -> list:
    found, seen = [], set()
    roots = [(adapters.PACKS_DIR, True)] + ([(adapters.user_orgs_dir(), False)] if user else [])
    for root, builtin in roots:
        for mf in sorted(root.glob("*/pack.json")):
            try:
                p = load_pack(mf.parent, builtin)
            except PackError:
                continue
            if p.slug not in seen:  # built-in wins over a same-slug user pack
                seen.add(p.slug)
                found.append(p)
    return found


def match(org_name: Optional[str], packs: Optional[list] = None) -> Optional[Pack]:
    packs = discover() if packs is None else packs
    if not org_name:
        return packs[0] if len(packs) == 1 else None
    key = org_name.strip().lower()
    for p in packs:
        if key == p.slug or key in (n.lower() for n in p.org_names):
            return p
    return None


def lint(pack: Pack, task: dict) -> dict:
    """Run the pack's linter in-process and return {errors, warnings, score, notes}."""
    if not pack.lint_path:
        return {"errors": [], "warnings": [], "score": None, "notes": ["this pack has no linter"]}
    name = f"zoho_pack_lint_{pack.slug.replace('-', '_')}"
    mod = sys.modules.get(name)
    if mod is None or getattr(mod, "__file__", None) != str(pack.lint_path):
        spec = importlib.util.spec_from_file_location(name, pack.lint_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod  # dataclasses in the linter look their module up here
        spec.loader.exec_module(mod)
    r = mod.lint(task)
    return {"errors": list(r.errors), "warnings": list(r.warnings), "score": getattr(r, "score", None),
            "notes": list(getattr(r, "notes", []))}


def read_resource_files(pack: Pack) -> dict:
    out = {}
    for rel in pack.resources:
        f = (pack.path / rel).resolve()
        if pack.path.resolve() in f.parents and f.is_file():
            out[rel] = f.read_text(encoding="utf-8")
    return out


def rules_text(pack: Pack) -> str:
    docs = read_resource_files(pack)
    return "\n\n---\n\n".join(f"<!-- {rel} -->\n{txt}" for rel, txt in docs.items()) or f"(no rule documents in pack {pack.slug})"
