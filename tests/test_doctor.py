import asyncio
import sys
import types

import pytest

import zoho_skills
from zoho_skills import doctor, upstream

SECRET = "SUPERSECRETKEY123"
URL = f"https://abc.zohomcp.in/mcp/{SECRET}/message?key={SECRET}"


class Tool:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    zh = tmp_path / "zh"
    home.mkdir()
    zh.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ZOHO_SKILLS_HOME", str(zh))
    monkeypatch.delenv("ZOHO_SKILLS_URL", raising=False)
    monkeypatch.delenv("ZOHO_SKILLS_READONLY", raising=False)
    monkeypatch.delattr(zoho_skills, "harnesses", raising=False)
    monkeypatch.setitem(sys.modules, "zoho_skills.harnesses", None)  # simulate "not written yet"
    return types.SimpleNamespace(home=home, zh=zh)


def fake_harnesses(monkeypatch, states):
    mod = types.ModuleType("zoho_skills.harnesses")
    mod.HARNESSES = list(states)
    mod.status = lambda h, home: states[h]
    monkeypatch.setitem(sys.modules, "zoho_skills.harnesses", mod)
    monkeypatch.setattr(zoho_skills, "harnesses", mod, raising=False)


def by_name(checks):
    return {c.name: c for c in checks}


def write_config(zh, mode, region="in", url=URL):
    import json
    p = zh / "config.json"
    p.write_text(json.dumps({"url": url, "region": region}))
    p.chmod(mode)
    return p


def assert_no_secret(checks):
    for c in checks:
        assert SECRET not in c.detail and SECRET not in c.fix, c
    assert SECRET not in doctor.render(checks)


def test_fresh_install_warns_and_skips(env):
    c = by_name(doctor.run_checks(env.home))
    assert c["python"].status == "ok"
    assert c["config file"].status == "warn" and "onboard" in c["config file"].fix
    assert c["MCP URL"].status == "warn"
    assert c["upstream"].status == "skip"
    assert c["harnesses"].status == "skip" and c["harnesses"].detail == "harness writers not available yet"
    assert "creole-studios" in c["org packs"].detail
    assert c["read-only mode"].detail.startswith("off")


def test_good_config_upstream_ok_and_secret_never_printed(env, monkeypatch):
    write_config(env.zh, 0o600)
    seen = []

    async def fake(url=None, command=None):
        seen.append(url)
        return [Tool(n) for n in ("get_portals", "get_projects_list", "get_tasks_by_project", "get_task_details",
                                  "create_a_task", "update_a_task")]

    monkeypatch.setattr(upstream, "list_tools_once", fake)
    checks = doctor.run_checks(env.home)
    c = by_name(checks)
    assert seen == [URL]
    assert c["config file"].status == "ok" and c["MCP URL"].status == "ok" and c["region"].status == "ok"
    assert c["upstream"].status == "ok" and "6 tools" in c["upstream"].detail and "read-only" in c["upstream"].detail
    assert_no_secret(checks)


def test_loose_permissions_warn(env):
    write_config(env.zh, 0o644)
    c = by_name(doctor.run_checks(env.home, upstream_check=False))
    assert c["config file"].status == "warn" and "chmod 600" in c["config file"].fix
    assert c["upstream"].status == "skip"
    assert_no_secret(list(c.values()))


def test_region_mismatch_warns(env):
    write_config(env.zh, 0o600, region="com")  # URL host is .in
    checks = doctor.run_checks(env.home, upstream_check=False)
    c = by_name(checks)
    assert c["region"].status == "warn" and "com" in c["region"].detail
    assert_no_secret(checks)


def test_upstream_failure_is_redacted(env, monkeypatch):
    write_config(env.zh, 0o600)

    async def boom(url=None, command=None):
        raise RuntimeError(f"connect failed for {url} and https://other.example/x?token={SECRET}")

    monkeypatch.setattr(upstream, "list_tools_once", boom)
    checks = doctor.run_checks(env.home)
    up = by_name(checks)["upstream"]
    assert up.status == "fail" and "RuntimeError" in up.detail
    assert_no_secret(checks)


def test_upstream_timeout(env, monkeypatch):
    write_config(env.zh, 0o600)

    async def hang(url=None, command=None):
        await asyncio.sleep(10)

    monkeypatch.setattr(upstream, "list_tools_once", hang)
    monkeypatch.setattr(doctor, "UPSTREAM_TIMEOUT", 0.05)
    up = by_name(doctor.run_checks(env.home))["upstream"]
    assert up.status == "fail" and "no response" in up.detail


def test_env_url_and_readonly_flag(env, monkeypatch):
    monkeypatch.setenv("ZOHO_SKILLS_URL", URL)
    monkeypatch.setenv("ZOHO_SKILLS_READONLY", "1")
    checks = doctor.run_checks(env.home, upstream_check=False)
    c = by_name(checks)
    assert c["MCP URL"].status == "ok" and c["read-only mode"].detail.startswith("ON")
    assert_no_secret(checks)


def test_harness_checks_present_missing_and_direct_entry(env, monkeypatch):
    fake_harnesses(monkeypatch, {
        "claude": {"present": True, "path": "/h/.claude.json", "direct_zoho_entry": False},
        "cursor": {"present": False, "path": None, "direct_zoho_entry": False},
        "codex": {"present": True, "path": "/h/.codex/config.toml", "direct_zoho_entry": True},
    })
    c = by_name(doctor.run_checks(env.home))
    assert c["harness claude"].status == "ok"
    assert c["harness cursor"].status == "warn" and c["harness cursor"].fix == "zoho-skills onboard"
    assert c["harness codex"].status == "ok"
    assert c["harness codex direct entry"].status == "warn" and "write gate" in c["harness codex direct entry"].detail
    assert "harnesses" not in c


def test_render_marks_and_no_ansi(env):
    checks = [doctor.Check("a", "ok", "fine"), doctor.Check("b", "warn", "hmm", "do x"),
              doctor.Check("c", "fail", "bad", "do y"), doctor.Check("d", "skip", "n/a")]
    out = doctor.render(checks).splitlines()
    assert out[0].startswith("✔ a") and out[1].startswith("! b") and "fix: do x" in out[2]
    assert out[3].startswith("✖ c") and out[-1].startswith("– d")
    assert "\x1b" not in "\n".join(out)
