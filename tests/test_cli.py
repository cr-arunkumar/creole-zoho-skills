import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
CLI = REPO / "scripts" / "cli.py"
CORE, CREOLE = "zoho-projects-core", "creole-studios-zoho"
URL = "https://example.invalid/mcp/message?key=SECRET"


def run(*args, home):
    env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin")  # no real `claude` on PATH
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


def test_yes_install_with_mcp_for_non_claude_harnesses(tmp_path):
    r = run("--yes", "--harness", "antigravity,codex", "--global", "--mcp-url", URL, home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / ".gemini/antigravity/skills" / CORE / "SKILL.md").is_file()
    gem = json.loads((tmp_path / ".gemini/settings.json").read_text())
    assert gem["mcpServers"]["zoho-projects"]["httpUrl"] == URL
    assert URL in (tmp_path / ".codex/config.toml").read_text()
    assert "SECRET" not in r.stdout  # URL is masked in output


def test_project_cursor_install_writes_rules_and_mcp(tmp_path):
    proj = tmp_path / "app"
    proj.mkdir()
    r = run("--yes", "--harness", "cursor", "--project", str(proj), "--mcp-url", URL, home=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (proj / ".cursor/rules" / f"{CREOLE}.mdc").is_file()
    assert json.loads((proj / ".cursor/mcp.json").read_text())["mcpServers"]["zoho-projects"]["url"] == URL


def test_org_skill_alone_pulls_in_core(tmp_path):
    r = run("--yes", "--harness", "antigravity", "--global", "--skills", CREOLE, "--no-mcp", home=tmp_path)
    assert r.returncode == 0
    assert (tmp_path / ".gemini/antigravity/skills" / CORE / "SKILL.md").is_file()


def test_no_mcp_flag_and_missing_url_skip_mcp(tmp_path):
    r = run("--yes", "--harness", "antigravity", "--global", home=tmp_path)
    assert r.returncode == 0 and not (tmp_path / ".gemini/settings.json").exists()
    assert "creole-zoho install" in r.stdout  # tells the user how to connect later


def test_dry_run_writes_nothing(tmp_path):
    r = run("--yes", "--harness", "all", "--global", "--mcp-url", URL, "--dry-run", home=tmp_path)
    assert r.returncode == 0 and not any(tmp_path.iterdir())


def test_bad_inputs_rejected(tmp_path):
    assert run("--yes", "--harness", "nope", "--global", home=tmp_path).returncode != 0
    assert run("--yes", "--skills", "nope", "--global", home=tmp_path).returncode != 0
    assert run("--yes", "--harness", "codex", "--global", "--mcp-url", "http://evil.example/x", home=tmp_path).returncode != 0


def test_list_and_doctor(tmp_path):
    assert CREOLE in run("list", home=tmp_path).stdout
    assert run("doctor", home=tmp_path).returncode == 0


def test_install_sh_is_valid_posix_sh():
    assert subprocess.run(["sh", "-n", str(REPO / "install.sh")]).returncode == 0
