import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
INSTALL = REPO / "scripts" / "install.py"
CORE, CREOLE = "zoho-projects-core", "creole-studios-zoho"


def run(*args, home=None):
    env = dict(os.environ)
    if home:
        env["HOME"] = str(home)
    return subprocess.run([sys.executable, str(INSTALL), *args], capture_output=True, text=True, env=env)


def test_project_install_all_harnesses(tmp_path):
    r = run("--harness", "all", "--project", str(tmp_path))
    assert r.returncode == 0, r.stderr
    for base in (".claude/skills", ".agent/skills", ".agents/skills"):
        for n in (CORE, CREOLE):
            assert (tmp_path / base / n / "SKILL.md").is_file()
    assert (tmp_path / ".cursor/rules" / f"{CREOLE}.mdc").is_file()
    assert (tmp_path / "AGENTS.md").read_text().count("creole-zoho-skills:start") == 1
    assert CREOLE in (tmp_path / "GEMINI.md").read_text()
    assert not list(tmp_path.rglob("__pycache__"))


def test_reinstall_is_idempotent_and_preserves_user_content(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# My project rules\n\nKeep tests green.\n")
    for _ in range(2):
        assert run("--harness", "codex", "--project", str(tmp_path)).returncode == 0
    text = agents.read_text()
    assert text.startswith("# My project rules") and "Keep tests green." in text
    assert text.count("creole-zoho-skills:start") == 1 and text.count("creole-zoho-skills:end") == 1


def test_org_skill_pulls_in_core(tmp_path):
    assert run("--harness", "claude", "--project", str(tmp_path), "--skills", CREOLE).returncode == 0
    assert (tmp_path / ".claude/skills" / CORE / "SKILL.md").is_file()


def test_global_install_uses_home(tmp_path):
    r = run("--harness", "all", "--global", home=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".claude/skills" / CREOLE / "SKILL.md").is_file()
    assert (tmp_path / ".gemini/antigravity/skills" / CORE / "SKILL.md").is_file()
    assert (tmp_path / ".codex/AGENTS.md").is_file()
    assert "skipping cursor" in r.stdout


def test_dry_run_writes_nothing(tmp_path):
    r = run("--harness", "all", "--project", str(tmp_path), "--dry-run")
    assert r.returncode == 0 and not any(tmp_path.iterdir())


def test_unknown_skill_rejected(tmp_path):
    assert run("--harness", "claude", "--project", str(tmp_path), "--skills", "nope").returncode == 2


def test_committed_adapters_are_current():
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "build_adapters.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_every_skill_has_valid_frontmatter():
    sys.path.insert(0, str(REPO / "scripts"))
    import adapters
    names = adapters.list_skills()
    assert {CORE, CREOLE} <= set(names)
    for n in names:
        meta, body = adapters.parse_skill(n)
        assert len(meta["description"]) > 40 and body.strip()
