import json
import subprocess

import pytest

from zoho_skills import harnesses as h

URL_SECRET = "https://mcp.zoho.in/mcp/SECRETKEY/message"


@pytest.fixture(autouse=True)
def fixed_command(monkeypatch):
    monkeypatch.setattr(h, "entry_command", lambda: ("/usr/local/bin/zoho-skills", ["mcp"]))


def cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


class FakeClaude:
    def __init__(self, registered=False, fail_add=False):
        self.registered, self.fail_add, self.calls = registered, fail_add, []

    def __call__(self, cmd):
        self.calls.append(cmd)
        sub = cmd[2]
        if sub == "get":
            return cp(0 if self.registered else 1)
        if sub == "add":
            if self.fail_add:
                return cp(1, err="boom\nadd failed")
            self.registered = True
            return cp()
        if sub == "remove":
            self.registered = False
            return cp()
        raise AssertionError(cmd)


def never_runner(cmd):
    raise AssertionError(f"runner must not be called: {cmd}")


JSON_HARNESSES = [("cursor", ".cursor/mcp.json"), ("antigravity", ".gemini/config/mcp_config.json")]


@pytest.mark.parametrize("harness,rel", JSON_HARNESSES)
def test_json_create_idempotent_and_no_url(tmp_path, harness, rel):
    r1 = h.register(harness, home=tmp_path)
    assert r1.startswith("added")
    path = tmp_path / rel
    data = json.loads(path.read_text())
    assert data["mcpServers"]["zoho-skills"] == {"command": "/usr/local/bin/zoho-skills", "args": ["mcp"]}
    assert "http" not in path.read_text()
    before = path.read_text()
    assert h.register(harness, home=tmp_path).startswith("unchanged")
    assert path.read_text() == before


@pytest.mark.parametrize("harness,rel", JSON_HARNESSES)
def test_json_preserves_and_backs_up_once(tmp_path, harness, rel):
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    original = {"theme": "dark", "mcpServers": {"other": {"command": "x", "args": ["1"]}}}
    path.write_text(json.dumps(original))
    h.register(harness, home=tmp_path)
    data = json.loads(path.read_text())
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == original["mcpServers"]["other"]
    bak = path.with_name(path.name + ".bak")
    assert json.loads(bak.read_text()) == original
    # a later change must not overwrite the first backup
    h.unregister(harness, home=tmp_path)
    assert json.loads(bak.read_text()) == original


@pytest.mark.parametrize("harness,rel", JSON_HARNESSES)
def test_json_invalid_untouched(tmp_path, harness, rel):
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    for fn in (h.register, h.unregister):
        with pytest.raises(h.HarnessError):
            fn(harness, home=tmp_path)
    assert path.read_text() == "{not json"
    assert not path.with_name(path.name + ".bak").exists()


@pytest.mark.parametrize("harness,rel", JSON_HARNESSES)
def test_json_unregister_removes_only_ours(tmp_path, harness, rel):
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    h.register(harness, home=tmp_path)
    assert h.unregister(harness, home=tmp_path).startswith("removed")
    assert json.loads(path.read_text()) == {"mcpServers": {"other": {"command": "x"}}}
    assert h.unregister(harness, home=tmp_path).startswith("unchanged")


@pytest.mark.parametrize("harness,rel", JSON_HARNESSES)
def test_json_dry_run_writes_nothing(tmp_path, harness, rel):
    assert h.register(harness, home=tmp_path, dry_run=True).startswith("would add")
    assert not (tmp_path / rel).exists()
    h.register(harness, home=tmp_path)
    before = (tmp_path / rel).read_text()
    assert h.unregister(harness, home=tmp_path, dry_run=True).startswith("would remove")
    assert (tmp_path / rel).read_text() == before


@pytest.mark.parametrize("harness,rel", JSON_HARNESSES)
def test_json_status_and_direct_zoho(tmp_path, harness, rel):
    assert h.status(harness, home=tmp_path) == {"present": False, "path": None, "direct_zoho_entry": False}
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"zoho-projects": {"url": URL_SECRET}}}))
    s = h.status(harness, home=tmp_path)
    assert s["present"] is False and s["direct_zoho_entry"] is True
    h.register(harness, home=tmp_path)
    s = h.status(harness, home=tmp_path)
    assert s["present"] is True and s["path"] == str(path) and s["direct_zoho_entry"] is True
    h.unregister(harness, home=tmp_path)
    path.write_text(json.dumps({"mcpServers": {"x": {"httpUrl": "https://mcp.zoho.com/y"},
                                               "zoho-skills": {"command": "zoho-skills", "args": ["mcp"]}}}))
    assert h.status(harness, home=tmp_path)["direct_zoho_entry"] is True
    path.write_text(json.dumps({"mcpServers": {"y": {"command": "npx", "args": ["mcp-remote", URL_SECRET]},
                                               "zoho-skills": {"command": "zoho-skills", "args": ["mcp"]}}}))
    assert h.status(harness, home=tmp_path)["direct_zoho_entry"] is True
    path.write_text(json.dumps({"mcpServers": {"zoho-skills": {"command": "zoho-skills", "args": ["mcp"]},
                                               "github": {"command": "gh"}}}))
    assert h.status(harness, home=tmp_path)["direct_zoho_entry"] is False


def test_url_never_written_to_any_config(tmp_path):
    for harness in ("cursor", "antigravity", "codex"):
        h.register(harness, home=tmp_path)
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert "zoho.in" not in p.read_text() and "SECRET" not in p.read_text()


# ---------------------------------------------------------------- codex

CODEX = ".codex/config.toml"


def test_codex_create_idempotent(tmp_path):
    assert h.register("codex", home=tmp_path).startswith("added")
    text = (tmp_path / CODEX).read_text()
    assert h.TOML_START in text and h.TOML_END in text
    assert '[mcp_servers.zoho-skills]\ncommand = "/usr/local/bin/zoho-skills"\nargs = ["mcp"]' in text
    assert h.register("codex", home=tmp_path).startswith("unchanged")
    assert (tmp_path / CODEX).read_text() == text


def test_codex_preserves_backup_and_unregister_only_ours(tmp_path):
    path = tmp_path / CODEX
    path.parent.mkdir(parents=True)
    original = 'model = "o3"\n\n[mcp_servers.other]\ncommand = "x"\nargs = ["a"]\n'
    path.write_text(original)
    h.register("codex", home=tmp_path)
    text = path.read_text()
    assert text.startswith(original.rstrip("\n")) and "[mcp_servers.other]" in text
    assert path.with_name("config.toml.bak").read_text() == original
    h.unregister("codex", home=tmp_path)
    assert path.read_text().strip() == original.strip()
    assert path.with_name("config.toml.bak").read_text() == original


def test_codex_update_replaces_block(tmp_path, monkeypatch):
    h.register("codex", home=tmp_path)
    monkeypatch.setattr(h, "entry_command", lambda: ("/new/zoho-skills", ["mcp"]))
    assert h.register("codex", home=tmp_path).startswith("updated")
    text = (tmp_path / CODEX).read_text()
    assert text.count(h.TOML_START) == 1 and "/new/zoho-skills" in text and "/usr/local" not in text


def test_codex_invalid_toml_untouched(tmp_path):
    path = tmp_path / CODEX
    path.parent.mkdir(parents=True)
    path.write_text("[broken\nx =")
    with pytest.raises(h.HarnessError):
        h.register("codex", home=tmp_path)
    with pytest.raises(h.HarnessError):
        h.unregister("codex", home=tmp_path)
    assert path.read_text() == "[broken\nx ="


def test_codex_hand_defined_entry_refused(tmp_path):
    path = tmp_path / CODEX
    path.parent.mkdir(parents=True)
    path.write_text('[mcp_servers.zoho-skills]\ncommand = "mine"\n')
    with pytest.raises(h.HarnessError):
        h.register("codex", home=tmp_path)
    assert path.read_text() == '[mcp_servers.zoho-skills]\ncommand = "mine"\n'


def test_codex_dry_run_and_status(tmp_path):
    assert h.register("codex", home=tmp_path, dry_run=True).startswith("would add")
    assert not (tmp_path / "codex").exists() and not (tmp_path / CODEX).exists()
    assert h.status("codex", home=tmp_path)["present"] is False
    path = tmp_path / CODEX
    path.parent.mkdir(parents=True)
    path.write_text(f'[mcp_servers.zoho-projects]\nurl = "{URL_SECRET}"\n')
    assert h.status("codex", home=tmp_path) == {"present": False, "path": str(path), "direct_zoho_entry": True}
    h.register("codex", home=tmp_path)
    s = h.status("codex", home=tmp_path)
    assert s["present"] is True and s["direct_zoho_entry"] is True
    h.unregister("codex", home=tmp_path, dry_run=True)
    assert h.status("codex", home=tmp_path)["present"] is True
    h.unregister("codex", home=tmp_path)
    assert h.status("codex", home=tmp_path)["present"] is False


# ---------------------------------------------------------------- claude

def test_claude_register_idempotent(tmp_path):
    run = FakeClaude()
    assert h.register("claude", home=tmp_path, runner=run).startswith("added")
    assert ["claude", "mcp", "add", "-s", "user", "zoho-skills", "--", "/usr/local/bin/zoho-skills", "mcp"] in run.calls
    assert h.register("claude", home=tmp_path, runner=run).startswith("unchanged")
    assert sum(c[2] == "add" for c in run.calls) == 1


def test_claude_unregister_and_status(tmp_path):
    run = FakeClaude(registered=True)
    assert h.status("claude", home=tmp_path, runner=run)["present"] is True
    assert h.unregister("claude", home=tmp_path, runner=run).startswith("removed")
    assert ["claude", "mcp", "remove", "-s", "user", "zoho-skills"] in run.calls
    assert h.status("claude", home=tmp_path, runner=run)["present"] is False
    assert h.unregister("claude", home=tmp_path, runner=run).startswith("unchanged")


def test_claude_dry_run_never_calls_runner(tmp_path):
    assert h.register("claude", home=tmp_path, runner=never_runner, dry_run=True).startswith("would run: claude mcp add")
    assert h.unregister("claude", home=tmp_path, runner=never_runner, dry_run=True).startswith("would run: claude mcp remove")


def test_claude_add_failure_raises(tmp_path):
    with pytest.raises(h.HarnessError, match="add failed"):
        h.register("claude", home=tmp_path, runner=FakeClaude(fail_add=True))


def test_claude_missing_cli_gives_manual_command(tmp_path, monkeypatch):
    monkeypatch.setattr(h.shutil, "which", lambda name: None)
    with pytest.raises(h.HarnessError, match=r"claude mcp add -s user zoho-skills -- "):
        h.register("claude", home=tmp_path)
    assert h.status("claude", home=tmp_path)["present"] is False


def test_claude_direct_zoho_from_claude_json(tmp_path):
    (tmp_path / ".claude.json").write_text(json.dumps(
        {"mcpServers": {"zoho-projects": {"type": "http", "url": URL_SECRET}}, "projects": {}}))
    s = h.status("claude", home=tmp_path, runner=FakeClaude(registered=True))
    assert s == {"present": True, "path": str(tmp_path / ".claude.json"), "direct_zoho_entry": True}
    (tmp_path / ".claude.json").write_text("{bad json")
    assert h.status("claude", home=tmp_path, runner=FakeClaude())["direct_zoho_entry"] is False


def test_unknown_harness(tmp_path):
    with pytest.raises(h.HarnessError):
        h.register("vim", home=tmp_path)
