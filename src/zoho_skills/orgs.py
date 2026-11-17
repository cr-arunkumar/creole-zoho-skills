"""Manage the user's installed org packs (~/.zoho-skills/orgs/<slug>): add from a folder or git repo, list, update, remove.

Trust model: adding a pack only copies files and validates pack.json; no pack code runs during add/update/remove. A pack's
lint function is executed later, in-process, when a task is linted, so install packs only from sources you trust."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from . import adapters, packs
from .packs import PackError

TRUST_NOTE = ("Trust note: a pack's lint function runs as Python code when tasks are linted; "
              "only install packs from sources you trust.")
SOURCE_FILE = ".source.json"
_OWNER_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
_GIT_TIMEOUT = 120


def default_runner(cmd: list, cwd: Optional[Path] = None) -> "subprocess.CompletedProcess":
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="https")
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None,
                              timeout=_GIT_TIMEOUT, check=True, env=env)
    except subprocess.CalledProcessError as e:
        raise PackError(f"{cmd[0]} failed: {(e.stderr or '').strip()[:300]}") from e
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PackError(f"could not run {cmd[0]}: {e}") from e


# ---- source classification -------------------------------------------------------------------------------------------

def _check_https_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        raise PackError("git sources must be https:// URLs (ssh, git, http and file URLs are refused)")
    if p.username or p.password:
        raise PackError("git URL must not embed credentials")
    if re.search(r"\s", url) or url.startswith("-"):
        raise PackError("invalid git URL")
    return url


def _classify(source: str) -> dict:
    """Return the source record: {'type': 'local'|'git', ...}. Local directories win over owner/repo shorthand."""
    source = (source or "").strip()
    if not source:
        raise PackError("no source given")
    if "://" in source or source.startswith("git@"):
        return {"type": "git", "url": _check_https_url(source)}
    local = Path(source).expanduser()
    if local.is_dir():
        return {"type": "local", "path": str(local.resolve())}
    if _OWNER_REPO.fullmatch(source):
        rec = {"type": "git", "url": f"https://github.com/{source}", "spec": source}
        if shutil.which("gh"):
            rec["via"] = "gh"
        return rec
    raise PackError(f"{source!r} is not a directory, an https:// git URL or an owner/repo name")


# ---- staging & validation --------------------------------------------------------------------------------------------

def _staging_root() -> Path:
    root = adapters.user_orgs_dir().parent / ".staging"  # sibling of orgs/, so it is never discovered as a pack
    root.mkdir(parents=True, exist_ok=True)
    return root


def _check_symlinks(root: Path) -> None:
    base = root.resolve()
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(dirpath) / name
            if not p.is_symlink():
                continue
            target = os.readlink(p)
            resolved = (p.parent / target).resolve()
            if os.path.isabs(target) or (resolved != base and base not in resolved.parents):
                raise PackError(f"refusing pack: symlink {p.relative_to(root)} points outside the pack")


def _fetch(rec: dict, dest: Path, runner) -> None:
    """Materialise the source into dest (which must not exist)."""
    if rec["type"] == "local":
        src = Path(rec["path"])
        shutil.copytree(src, dest, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", SOURCE_FILE))
        return
    if rec.get("via") == "gh" and shutil.which("gh"):
        runner(["gh", "repo", "clone", rec["spec"], str(dest), "--", "--depth", "1"], None)
    else:
        runner(["git", "clone", "--depth", "1", "--", rec["url"], str(dest)], None)
    if not dest.is_dir():
        raise PackError("clone produced no directory")
    shutil.rmtree(dest / ".git", ignore_errors=True)
    (dest / SOURCE_FILE).unlink(missing_ok=True)


def _stage(rec: dict, runner) -> tuple:
    """Fetch + validate into a temp dir. Returns (tmp_root, staged_pack_dir, Pack). Caller removes tmp_root."""
    tmp = Path(tempfile.mkdtemp(prefix="add-", dir=_staging_root()))
    try:
        dest = tmp / "pack"
        _fetch(rec, dest, runner)
        _check_symlinks(dest)
        pack = packs.load_pack(dest)  # validates pack.json, slug and lint path; executes nothing
        return tmp, dest, pack
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _builtin_slugs() -> set:
    return {p.slug for p in packs.discover(user=False)}


def _install(rec: dict, runner, dry_run: bool, expect_slug: Optional[str] = None) -> packs.Pack:
    tmp, stage, pack = _stage(rec, runner)
    try:
        if expect_slug and pack.slug != expect_slug:
            raise PackError(f"source now provides slug {pack.slug!r}, expected {expect_slug!r}; refusing")
        if pack.slug in _builtin_slugs():
            raise PackError(f"{pack.slug!r} is a built-in pack and cannot be replaced")
        orgs = adapters.user_orgs_dir()
        target = orgs / pack.slug
        if dry_run:
            pack.trust_note = TRUST_NOTE
            pack.dry_run = True
            return pack
        (stage / SOURCE_FILE).write_text(json.dumps(dict(rec, slug=pack.slug), indent=2) + "\n", encoding="utf-8")
        orgs.mkdir(parents=True, exist_ok=True)
        backup = None
        if target.exists() or target.is_symlink():
            backup = tmp / "previous"
            os.replace(target, backup)
        try:
            os.replace(stage, target)  # atomic: same filesystem as ~/.zoho-skills/orgs
        except BaseException:
            if backup:
                os.replace(backup, target)
            raise
        installed = packs.load_pack(target)
        installed.trust_note = TRUST_NOTE
        installed.dry_run = False
        return installed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- public API ------------------------------------------------------------------------------------------------------

def add(source: str, *, dry_run: bool = False, runner=default_runner) -> packs.Pack:
    """Install a pack from a local dir, an https git URL or owner/repo. With dry_run the source is still fetched into a
    temp dir and validated (so errors surface), but nothing is installed. The result carries .trust_note and .dry_run."""
    return _install(_classify(source), runner, dry_run)


def list_orgs() -> list:
    return [{"slug": p.slug, "display_name": p.display_name, "version": p.version, "builtin": p.builtin,
             "path": str(p.path)} for p in packs.discover()]


def _user_pack_dirs() -> list:
    root = adapters.user_orgs_dir()
    return sorted(d for d in root.iterdir() if d.is_dir() and not d.is_symlink() and (d / "pack.json").is_file()) \
        if root.is_dir() else []


def update(slug: Optional[str] = None, *, dry_run: bool = False, runner=default_runner) -> list:
    """Re-pull git-sourced user packs and re-copy local-dir packs. Returns one status line per pack."""
    dirs = _user_pack_dirs()
    if slug is not None:
        if slug in _builtin_slugs():
            raise PackError(f"{slug!r} is a built-in pack; it updates with zoho-skills itself")
        dirs = [d for d in dirs if d.name == slug]
        if not dirs:
            raise PackError(f"no installed user pack {slug!r}")
    out = []
    for d in dirs:
        name = d.name
        try:
            rec = json.loads((d / SOURCE_FILE).read_text(encoding="utf-8"))
            if rec.get("type") == "git":
                _check_https_url(rec.get("url", ""))
            elif rec.get("type") == "local":
                if not Path(rec.get("path", "")).is_dir():
                    raise PackError(f"source folder {rec.get('path')} no longer exists")
            else:
                raise ValueError("unknown source type")
        except (OSError, ValueError):
            out.append(f"{name}: skipped (no recorded source; re-add it with `orgs add`)")
            continue
        except PackError as e:
            out.append(f"{name}: skipped ({e})")
            continue
        try:
            old = packs.load_pack(d).version
            new = _install(rec, runner, dry_run, expect_slug=name)
        except PackError as e:
            out.append(f"{name}: failed ({e})")
            continue
        verb = "would update" if dry_run else "updated"
        out.append(f"{name}: {verb} {old or '?'} -> {new.version or '?'} from {rec.get('url') or rec.get('path')}")
    return out


def remove(slug: str, *, dry_run: bool = False) -> str:
    if not _SLUG.fullmatch(slug or ""):
        raise PackError(f"invalid pack slug {slug!r}")
    if slug in _builtin_slugs():
        raise PackError(f"{slug!r} is a built-in pack and cannot be removed")
    root = adapters.user_orgs_dir()
    target = root / slug
    if target.is_symlink() or not target.is_dir():
        raise PackError(f"no installed user pack {slug!r}" if not target.is_symlink()
                        else f"refusing to remove {slug!r}: it is a symlink")
    if target.resolve().parent != root.resolve():
        raise PackError(f"refusing to remove {target}: outside {root}")
    if dry_run:
        return f"would remove {target}"
    shutil.rmtree(target)
    return f"removed {slug}"
