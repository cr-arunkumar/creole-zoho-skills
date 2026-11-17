import json
import shutil
from pathlib import Path

import pytest

from zoho_skills import orgs, packs
from zoho_skills.packs import PackError


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(orgs.shutil, "which", lambda name: None)
    return h


def make_pack(root: Path, slug="acme", version="1.0.0", lint=True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    mf = {"slug": slug, "display_name": slug.title(), "version": version, "org_names": [f"{slug} inc"],
          "resources": ["skills/x/SKILL.md"]}
    (root / "skills/x").mkdir(parents=True, exist_ok=True)
    (root / "skills/x/SKILL.md").write_text("rules " + version, encoding="utf-8")
    if lint:
        (root / "lint.py").write_text("raise SystemExit('must never run during add')\n", encoding="utf-8")
        mf["lint"] = "lint.py"
    (root / "pack.json").write_text(json.dumps(mf), encoding="utf-8")
    return root


class FakeRunner:
    """'Clones' by copying a fixture dir to the destination argument; records commands."""

    def __init__(self, fixture: Path):
        self.fixture, self.calls = fixture, []

    def __call__(self, cmd, cwd=None):
        self.calls.append(cmd)
        dest = Path(cmd[-1]) if cmd[0] == "git" else Path(cmd[4])
        shutil.copytree(self.fixture, dest)
        (dest / ".git").mkdir()
        (dest / ".git/HEAD").write_text("ref")


def test_add_local_installs_and_lists(tmp_path, home):
    src = make_pack(tmp_path / "src")
    p = orgs.add(str(src))
    assert p.slug == "acme" and p.path == home / ".zoho-skills/orgs/acme"
    assert "trust" in p.trust_note.lower() and not p.dry_run
    assert json.loads((p.path / ".source.json").read_text())["type"] == "local"
    rows = {r["slug"]: r for r in orgs.list_orgs()}
    assert rows["acme"]["builtin"] is False and rows["acme"]["version"] == "1.0.0"
    assert rows["creole-studios"]["builtin"] is True
    assert not list((home / ".zoho-skills/orgs").glob(".*"))  # nothing stray inside orgs/


def test_add_dry_run_validates_but_does_not_install(tmp_path, home):
    src = make_pack(tmp_path / "src")
    p = orgs.add(str(src), dry_run=True)
    assert p.slug == "acme" and p.dry_run
    assert not (home / ".zoho-skills/orgs/acme").exists()


def test_invalid_pack_is_rejected_before_install(tmp_path, home):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "pack.json").write_text(json.dumps({"slug": "../evil", "display_name": "x", "org_names": ["x"]}))
    with pytest.raises(PackError):
        orgs.add(str(bad))
    assert not (home / ".zoho-skills/orgs").exists() or not list((home / ".zoho-skills/orgs").iterdir())


def test_symlink_escaping_pack_rejected(tmp_path, home):
    src = make_pack(tmp_path / "src")
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    (src / "leak").symlink_to(secret)
    with pytest.raises(PackError, match="symlink"):
        orgs.add(str(src))
    (src / "leak").unlink()
    (src / "abs").symlink_to("/etc/hosts")
    with pytest.raises(PackError, match="symlink"):
        orgs.add(str(src))
    (src / "abs").unlink()
    (src / "ok").symlink_to("skills/x/SKILL.md")  # relative and inside: fine
    assert orgs.add(str(src)).slug == "acme"


def test_builtin_slug_cannot_be_replaced(tmp_path):
    src = make_pack(tmp_path / "src", slug="creole-studios")
    with pytest.raises(PackError, match="built-in"):
        orgs.add(str(src))


@pytest.mark.parametrize("url", ["http://github.com/o/r", "git@github.com:o/r.git", "ssh://git@github.com/o/r",
                                 "file:///tmp/x", "git://github.com/o/r", "https://user:tok@github.com/o/r"])
def test_non_https_or_credentialed_git_urls_rejected(url):
    runner = FakeRunner(Path("."))
    with pytest.raises(PackError):
        orgs.add(url, runner=runner)
    assert runner.calls == []


def test_add_git_https_uses_runner_and_strips_dot_git(tmp_path, home):
    fixture = make_pack(tmp_path / "fx")
    r = FakeRunner(fixture)
    p = orgs.add("https://github.com/acme/zoho-pack", runner=r)
    assert r.calls[0][:3] == ["git", "clone", "--depth"] and "--" in r.calls[0]
    assert r.calls[0][-2] == "https://github.com/acme/zoho-pack"
    assert not (p.path / ".git").exists()
    assert json.loads((p.path / ".source.json").read_text())["url"] == "https://github.com/acme/zoho-pack"


def test_owner_repo_uses_gh_when_available_else_git(tmp_path, monkeypatch):
    fixture = make_pack(tmp_path / "fx")
    r = FakeRunner(fixture)
    orgs.add("acme/zoho-pack", runner=r)
    assert r.calls[0][0] == "git" and "https://github.com/acme/zoho-pack" in r.calls[0]
    monkeypatch.setattr(orgs.shutil, "which", lambda name: "/usr/bin/gh")
    r2 = FakeRunner(fixture)
    orgs.add("acme/zoho-pack", runner=r2)
    assert r2.calls[0][:4] == ["gh", "repo", "clone", "acme/zoho-pack"]


def test_failed_clone_leaves_nothing_behind(tmp_path, home):
    def boom(cmd, cwd=None):
        raise PackError("git failed: nope")

    with pytest.raises(PackError):
        orgs.add("https://github.com/acme/zoho-pack", runner=boom)
    assert not list((home / ".zoho-skills/.staging").iterdir())


def test_reinstall_replaces_atomically(tmp_path, home):
    src = make_pack(tmp_path / "src", version="1.0.0")
    orgs.add(str(src))
    make_pack(src, version="1.1.0")
    p = orgs.add(str(src))
    assert p.version == "1.1.0"
    assert "1.1.0" in (p.path / "skills/x/SKILL.md").read_text()
    assert not list((home / ".zoho-skills/.staging").iterdir())


def test_update_git_and_local_and_unknown(tmp_path, home):
    fx = make_pack(tmp_path / "fx", slug="gitpack", version="1.0.0")
    orgs.add("https://github.com/o/gitpack", runner=FakeRunner(fx))
    loc = make_pack(tmp_path / "loc", slug="localpack", version="1.0.0")
    orgs.add(str(loc))
    nosrc = make_pack(home / ".zoho-skills/orgs/manual", slug="manual")

    make_pack(fx, slug="gitpack", version="2.0.0")
    make_pack(loc, slug="localpack", version="1.5.0")
    dry = orgs.update(dry_run=True, runner=FakeRunner(fx))
    assert any("would update" in line and "gitpack" in line for line in dry)
    assert packs.load_pack(home / ".zoho-skills/orgs/gitpack").version == "1.0.0"

    lines = orgs.update(runner=FakeRunner(fx))
    assert any("gitpack: updated 1.0.0 -> 2.0.0" in line for line in lines)
    assert any("localpack: updated 1.0.0 -> 1.5.0" in line for line in lines)
    assert any("manual: skipped" in line for line in lines) and nosrc.exists()
    assert orgs.update("gitpack", runner=FakeRunner(fx))[0].startswith("gitpack:")
    with pytest.raises(PackError):
        orgs.update("nope")


def test_update_refuses_slug_change(tmp_path, home):
    fx = make_pack(tmp_path / "fx", slug="gitpack")
    orgs.add("https://github.com/o/gitpack", runner=FakeRunner(fx))
    make_pack(fx, slug="other")
    line = orgs.update("gitpack", runner=FakeRunner(fx))[0]
    assert "failed" in line and not (home / ".zoho-skills/orgs/other").exists()


def test_remove(tmp_path, home):
    orgs.add(str(make_pack(tmp_path / "src")))
    assert "would remove" in orgs.remove("acme", dry_run=True)
    assert (home / ".zoho-skills/orgs/acme").exists()
    assert orgs.remove("acme") == "removed acme"
    assert not (home / ".zoho-skills/orgs/acme").exists()


def test_remove_refuses_builtin_invalid_missing_and_symlink(tmp_path, home):
    with pytest.raises(PackError, match="built-in"):
        orgs.remove("creole-studios")
    for bad in ("../x", "", "A/B", ".."):
        with pytest.raises(PackError):
            orgs.remove(bad)
    with pytest.raises(PackError):
        orgs.remove("ghost")
    outside = tmp_path / "outside"
    make_pack(outside)
    root = home / ".zoho-skills/orgs"
    root.mkdir(parents=True)
    (root / "evil").symlink_to(outside)
    with pytest.raises(PackError, match="symlink"):
        orgs.remove("evil")
    assert outside.exists() and (outside / "pack.json").exists()


def test_add_never_executes_pack_code(tmp_path):
    src = make_pack(tmp_path / "src")  # lint.py raises SystemExit if imported/run
    assert orgs.add(str(src)).lint_path.name == "lint.py"
