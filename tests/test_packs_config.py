import json
import os
import stat

import pytest

from zoho_skills import config, packs


def test_builtin_creole_pack_loads_and_matches():
    p = packs.match("Creole Studios")
    assert p and p.slug == "creole-studios" and p.final_status == "In QA Review"
    assert packs.match("creolestudiosdotcom1").slug == p.slug and packs.match("Acme") is None
    res = packs.lint(p, {"title": "", "description": "x", "comment": "", "status": "In Progress"})
    assert res["errors"] and res["score"] is not None
    assert "Zoho Task Evaluation" in packs.rules_text(p)


def test_user_pack_discovered_and_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = tmp_path / ".zoho-skills/orgs/acme"
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({"slug": "acme", "display_name": "Acme", "org_names": ["Acme Inc"]}))
    assert packs.match("Acme Inc").slug == "acme"
    (d / "pack.json").write_text(json.dumps({"slug": "../evil", "display_name": "x", "org_names": []}))
    with pytest.raises(packs.PackError):
        packs.load_pack(d)
    (d / "pack.json").write_text(json.dumps({"slug": "acme", "display_name": "A", "org_names": ["A"],
                                             "lint": "../../../etc/passwd"}))
    with pytest.raises(packs.PackError):
        packs.load_pack(d)


def test_config_is_private_and_redacts(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOHO_SKILLS_HOME", str(tmp_path / "zs"))
    monkeypatch.delenv("ZOHO_SKILLS_URL", raising=False)
    url = "https://example.invalid/mcp/message?key=SECRET123"
    config.update(url=url, region="in")
    mode = stat.S_IMODE(os.stat(config.config_path()).st_mode)
    assert mode == 0o600 and stat.S_IMODE(os.stat(config.config_dir()).st_mode) == 0o700
    assert "SECRET123" not in config.redact(f"failed to reach {url}?x=1&token=SECRET123")
    assert config.host_matches_region("https://x.zohomcp.in/mcp", "in")
    assert not config.host_matches_region("https://x.zohomcp.com/mcp", "in")
