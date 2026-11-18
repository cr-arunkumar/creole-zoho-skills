import json
import os
import pathlib
import re
import stat
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
CORE, CREOLE = "zoho-projects-core", "creole-studios-zoho"
URL = "https://example.invalid/mcp/message?key=SECRET"


def run(*args, home, stdin=None):
    env = dict(os.environ, HOME=str(home), ZOHO_SKILLS_HOME=str(home / ".zoho-skills"),
               PATH="/usr/bin:/bin", PYTHONPATH=str(REPO / "src"))  # no real `claude` on PATH
    env.pop("ZOHO_SKILLS_URL", None)
    return subprocess.run([sys.executable, "-m", "zoho_skills", *args], capture_output=True, text=True, env=env,
                          input=stdin, stdin=None if stdin else subprocess.DEVNULL)


def test_install_is_skills_only(tmp_path):
    r = run("install", "--yes", "--harness", "antigravity,codex", "--global", home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / ".gemini/antigravity/skills" / CORE / "SKILL.md").is_file()
    assert (tmp_path / ".gemini/antigravity/skills" / CREOLE / "SKILL.md").is_file()
    assert not (tmp_path / ".gemini/settings.json").exists() and not (tmp_path / ".codex/config.toml").exists()


def test_org_skill_alone_pulls_in_core(tmp_path):
    r = run("install", "--yes", "--harness", "antigravity", "--global", "--skills", CREOLE, home=tmp_path)
    assert r.returncode == 0
    assert (tmp_path / ".gemini/antigravity/skills" / CORE / "SKILL.md").is_file()


def test_onboard_writes_one_entry_per_harness_and_keeps_url_in_private_config(tmp_path):
    r = run("onboard", "--yes", "--harness", "antigravity,codex", "--global", "--mcp-url", URL, "--no-verify",
            home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = tmp_path / ".zoho-skills" / "config.json"
    assert json.loads(cfg.read_text())["url"] == URL
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert "SECRET" not in r.stdout + r.stderr
    for f in sorted(tmp_path.rglob("*")):
        if f.is_file() and f != cfg:
            assert "SECRET" not in f.read_text(errors="ignore"), f  # URL lives only in the private config
    assert "zoho-skills" in (tmp_path / ".codex/config.toml").read_text()
    assert (tmp_path / ".gemini/antigravity/skills" / CORE / "SKILL.md").is_file()


def test_onboard_no_mcp_writes_no_entries_or_config(tmp_path):
    r = run("onboard", "--yes", "--harness", "antigravity", "--global", "--no-mcp", home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (tmp_path / ".gemini/settings.json").exists() and not (tmp_path / ".zoho-skills").exists()


def test_onboard_dry_run_writes_nothing(tmp_path):
    r = run("onboard", "--yes", "--harness", "all", "--global", "--mcp-url", URL, "--no-verify", "--dry-run",
            home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any(tmp_path.iterdir())


def test_bad_inputs_rejected(tmp_path):
    assert run("onboard", "--yes", "--harness", "nope", "--global", home=tmp_path).returncode != 0
    assert run("install", "--yes", "--skills", "nope", "--global", home=tmp_path).returncode != 0
    assert run("onboard", "--yes", "--harness", "codex", "--global", "--mcp-url", "http://evil.example/x",
               "--no-verify", home=tmp_path).returncode != 0


def test_connect_saves_url_privately(tmp_path):
    r = run("connect", "--yes", "--mcp-url", URL, "--no-verify", home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((tmp_path / ".zoho-skills/config.json").read_text())["url"] == URL
    assert "SECRET" not in r.stdout


def test_connect_without_url_points_to_india_console(tmp_path):
    r = run("connect", "--yes", home=tmp_path)
    assert r.returncode == 1 and "https://mcp.zoho.in/" in r.stdout


def test_lint_uses_org_pack(tmp_path):
    task = json.dumps({"title": "", "description": "x", "comment": "", "status": "In Progress"})
    r = run("lint", "--org", "Creole Studios", "--json", home=tmp_path, stdin=task)
    assert r.returncode == 1 and json.loads(r.stdout)["errors"]
    assert run("lint", "--org", "Nope", home=tmp_path, stdin=task).returncode == 2


def test_list_and_version(tmp_path):
    assert CREOLE in run("list", home=tmp_path).stdout
    assert re.search(r"zoho-skills \d+\.\d+\.\d+", run("--version", home=tmp_path).stdout)


def test_install_sh_is_valid_posix_sh():
    assert subprocess.run(["sh", "-n", str(REPO / "install.sh")]).returncode == 0


def test_versions_stay_in_sync_and_npm_bin_exists():
    pkg = json.loads((REPO / "package.json").read_text())
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    pyproject = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M).group(1)
    assert pkg["version"] == plugin["version"] == pyproject
    assert (REPO / pkg["bin"]["zoho-skills"]).is_file()


def test_logout_removes_only_the_url(tmp_path):
    run("connect", "--yes", "--mcp-url", URL, "--no-verify", home=tmp_path)
    cfg = tmp_path / ".zoho-skills/config.json"
    assert run("logout", "--dry-run", home=tmp_path).returncode == 0 and "url" in json.loads(cfg.read_text())
    r = run("logout", "--yes", home=tmp_path)
    assert r.returncode == 0 and "logged out" in r.stdout and "SECRET" not in r.stdout
    assert "url" not in json.loads(cfg.read_text()) and stat.S_IMODE(cfg.stat().st_mode) == 0o600
    assert "not logged in" in run("logout", "--yes", home=tmp_path).stdout


def test_disconnect_removes_entry_but_keeps_skills(tmp_path):
    run("onboard", "--yes", "--harness", "codex", "--global", "--mcp-url", URL, "--no-verify", home=tmp_path)
    toml = tmp_path / ".codex/config.toml"
    assert "zoho-skills" in toml.read_text()
    r = run("disconnect", "--yes", "--harness", "codex", "--logout", home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "zoho-skills" not in (toml.read_text() if toml.exists() else "")
    assert (tmp_path / ".codex/skills" / CORE / "SKILL.md").is_file()
    assert "url" not in json.loads((tmp_path / ".zoho-skills/config.json").read_text())


def test_update_skills_only_refreshes_installed_skills(tmp_path):
    run("install", "--yes", "--harness", "claude", "--global", home=tmp_path)
    skill = tmp_path / ".claude/skills" / CORE / "SKILL.md"
    skill.write_text("stale")
    r = subprocess.run([sys.executable, "-c", "from zoho_skills import cli; raise SystemExit(cli.main(['update','--skills-only']))"],
                       capture_output=True, text=True, env=dict(os.environ, HOME=str(tmp_path), PYTHONPATH=str(REPO / "src")))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skills refreshed" in r.stdout and skill.read_text() != "stale"


def test_login_without_url_points_to_connect(tmp_path):
    r = run("login", home=tmp_path)
    assert r.returncode == 1 and "zoho-skills connect" in r.stdout


def test_release_script_is_valid_sh_and_rejects_bad_versions():
    script = str(REPO / "scripts" / "release.sh")
    assert subprocess.run(["sh", "-n", script]).returncode == 0
    assert subprocess.run(["sh", script, "nope"], capture_output=True).returncode != 0


def test_version_compare_and_release_tag_parsing():
    from zoho_skills import cli
    assert cli._vtuple("v0.2.10") > cli._vtuple("0.2.9") and cli._vtuple("v1.0.0") > cli._vtuple("v0.9.9")
    assert cli._vtuple("0.2.6") == cli._vtuple("v0.2.6")


def test_update_check_reports_without_changing_anything(tmp_path, monkeypatch):
    from zoho_skills import cli
    monkeypatch.setattr(cli, "latest_release", lambda: "v99.0.0")
    monkeypatch.setattr(cli, "version", lambda: "0.2.6")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert cli.main(["update", "--check"]) == 0
