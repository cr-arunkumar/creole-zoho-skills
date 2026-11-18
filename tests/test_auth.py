import asyncio
import json
import stat

import httpx
import pytest

from zoho_skills import auth, config, upstream

URL = "https://proj.zohomcp.in/mcp/bb84f19a2d1468f7b741a07e536b4f5f/message"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOHO_SKILLS_HOME", str(tmp_path / "zs"))
    monkeypatch.delenv("ZOHO_SKILLS_URL", raising=False)
    return tmp_path


def status_error(code):
    req = httpx.Request("POST", URL)
    return httpx.HTTPStatusError("x", request=req, response=httpx.Response(code, request=req))


def test_describe_error_unwraps_exception_groups_and_names_the_fix():
    grouped = ExceptionGroup("unhandled errors in a TaskGroup", [status_error(401)])
    msg = upstream.describe_error(grouped)
    assert "HTTP 401" in msg and "zoho-skills login" in msg and "TaskGroup" not in msg
    assert upstream.is_auth_error(grouped)
    assert "404" in upstream.describe_error(status_error(404)) and not upstream.is_auth_error(status_error(404))
    assert "zoho-skills login" in upstream.describe_error(auth.AuthRequired(f"expired: {auth.RELOGIN}"))


def test_redact_masks_key_in_url_path():
    out = config.redact(f"Client error for url '{URL}' failed")
    assert "bb84f19a" not in out and "/mcp/***/message" in out


def test_storage_is_private_bound_to_url_and_clearable(home):
    from mcp.shared.auth import OAuthToken
    st = auth.FileStorage(URL)
    asyncio.run(st.set_tokens(OAuthToken(access_token="A", refresh_token="R", expires_in=3600)))
    assert stat.S_IMODE(auth.token_path().stat().st_mode) == 0o600
    assert auth.is_logged_in(URL) and asyncio.run(st.get_tokens()).refresh_token == "R"
    assert not auth.is_logged_in(URL + "x")  # tokens are bound to the URL they were issued for
    assert auth.runtime_provider(URL) is not None and auth.runtime_provider(URL + "x") is None
    assert auth.logout() and not auth.is_logged_in(URL)


def test_parse_callback():
    assert auth.parse_callback("/callback?code=abc&state=s1") == ("abc", "s1")
    with pytest.raises(auth.AuthRequired):
        auth.parse_callback("/callback?error=access_denied")
    with pytest.raises(ValueError):
        auth.parse_callback("/favicon.ico")


def test_callback_server_receives_redirect_over_a_real_socket():
    async def go():
        srv = auth.CallbackServer()
        port = await srv.start()
        async with httpx.AsyncClient() as c:
            assert (await c.get(f"http://127.0.0.1:{port}/favicon.ico")).status_code == 404
            r = await c.get(f"http://127.0.0.1:{port}/callback?code=THECODE&state=S")
            assert r.status_code == 200 and "Signed in" in r.text
        assert await srv.wait(5) == ("THECODE", "S")
        await srv.close()
    asyncio.run(go())


def test_default_scopes_have_no_delete():
    assert not [s for s in auth.DEFAULT_SCOPES if s.endswith(".delete")]


def test_scope_levels_and_services():
    allsc = auth.KNOWN_SCOPES
    assert list(auth.services(allsc)) == ["zohoprojects", "workdrive"]
    read = auth.select(allsc, ["zohoprojects"], "read")
    assert "ZohoMCP.tool.execute" in read and all(auth.split_scope(s)[2] == "read" or auth.is_core(s) for s in read)
    std = auth.select(allsc, ["zohoprojects"], "standard")
    assert "zohoprojects.tasks.update" in std and "zohoprojects.timesheets.create" in std
    assert "zohoprojects.tasks.delete" not in std and "zohoprojects.projects.update" not in std
    assert not [s for s in std if s.startswith("workdrive")]
    full = auth.select(allsc, ["zohoprojects", "workdrive"], "full")
    assert "zohoprojects.tasks.delete" in full and "workdrive.files.all" in full
    assert auth.DEFAULT_SCOPES == std


def test_fetch_supported_scopes_falls_back_offline(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", boom)
    assert auth.fetch_supported_scopes(URL) == auth.KNOWN_SCOPES


def test_parse_pasted_accepts_full_redirect_url_or_query_only():
    assert auth.parse_pasted("http://127.0.0.1:5555/callback?code=abc&state=S1") == ("abc", "S1")
    assert auth.parse_pasted("  ?code=abc&state=S1 ") == ("abc", "S1")
    with pytest.raises(ValueError):
        auth.parse_pasted("https://example.com/nothing")
    with pytest.raises(auth.AuthRequired):
        auth.parse_pasted("http://127.0.0.1:1/callback?error=access_denied")
