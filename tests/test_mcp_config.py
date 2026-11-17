import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import mcp_config as m  # noqa: E402

URL = "https://example.invalid/mcp?key=SECRET"


def test_json_merge_preserves_other_servers_and_backs_up(tmp_path):
    f = tmp_path / "mcp.json"
    f.write_text(json.dumps({"mcpServers": {"other": {"url": "https://o"}}, "theme": "dark"}))
    assert m.upsert_json_server(f, {"url": URL}) == "added"
    data = json.loads(f.read_text())
    assert data["mcpServers"]["other"] == {"url": "https://o"} and data["theme"] == "dark"
    assert json.loads((tmp_path / "mcp.json.bak").read_text())["mcpServers"] == {"other": {"url": "https://o"}}
    assert m.upsert_json_server(f, {"url": URL}) == "unchanged"
    assert m.upsert_json_server(f, {"url": "https://new.example/mcp"}) == "updated"


def test_invalid_json_is_never_overwritten(tmp_path):
    f = tmp_path / "mcp.json"
    f.write_text("{not json")
    with pytest.raises(m.McpError):
        m.upsert_json_server(f, {"url": URL})
    assert f.read_text() == "{not json"


def test_toml_block_idempotent_and_preserves_content(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('model = "x"\n')
    assert m.upsert_toml_block(f, URL) == "added"
    assert m.upsert_toml_block(f, URL) == "unchanged"
    assert m.upsert_toml_block(f, "https://new.example/mcp") == "updated"
    text = f.read_text()
    assert text.startswith('model = "x"') and text.count(m.TOML_START) == 1 and "new.example" in text


def test_handwritten_toml_entry_is_not_clobbered(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[mcp_servers.zoho-projects]\nurl = "https://mine"\n')
    with pytest.raises(m.McpError):
        m.upsert_toml_block(f, URL)


def test_claude_register_uses_injected_runner(tmp_path):
    calls = []

    def fake(cmd, cwd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[2] == "get" else 0, "", "")

    msg = m.register("claude", URL, home=tmp_path, runner=fake)
    assert "registered" in msg
    assert calls[1][:6] == ["claude", "mcp", "add", "--scope", "user", "--transport"] and calls[1][-1] == URL


def test_claude_already_registered_is_skipped(tmp_path):
    ok = lambda cmd, cwd: subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    assert "already" in m.register("claude", URL, home=tmp_path, runner=ok)


@pytest.mark.parametrize("bad", ["", "ftp://x", "http://example.com/mcp", "not a url"])
def test_url_validation(bad):
    with pytest.raises(m.McpError):
        m.validate_url(bad)


def test_mask_url_hides_key():
    assert "SECRET" not in m.mask_url(URL)


def test_console_urls_default_to_india_and_reject_unknown():
    assert m.console_url(m.DEFAULT_REGION) == "https://mcp.zoho.in/"
    assert m.console_url("com") == "https://mcp.zoho.com/"
    with pytest.raises(m.McpError):
        m.console_url("mars")
