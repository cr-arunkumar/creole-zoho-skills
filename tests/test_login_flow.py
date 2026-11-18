"""End-to-end OAuth sign-in against a fake Zoho MCP server: 401 challenge -> discovery -> dynamic registration ->
browser redirect to our localhost callback -> token exchange -> authenticated tools/list -> tokens stored 0600."""
import asyncio
import json
import stat
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from zoho_skills import auth, upstream


class FakeZoho(BaseHTTPRequestHandler):
    log: list = []
    base = ""

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj).encode(), extra=extra)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/.well-known/oauth-protected-resource":
            return self._json(200, {"resource": self.base + "/mcp/KEY/message", "authorization_servers": [self.base],
                                    "scopes_supported": ["zohoprojects.tasks.read", "ZohoMCP.tool.execute"]})
        if u.path == "/.well-known/oauth-authorization-server":
            return self._json(200, {"issuer": self.base, "authorization_endpoint": self.base + "/authorize",
                                    "token_endpoint": self.base + "/token", "registration_endpoint": self.base + "/register",
                                    "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
                                    "code_challenge_methods_supported": ["S256"]})
        if u.path == "/authorize":
            q = parse_qs(u.query)
            FakeZoho.log.append(("authorize", q.get("scope", [""])[0]))
            loc = f"{q['redirect_uri'][0]}?code=GOODCODE&state={q['state'][0]}"
            return self._send(302, extra={"Location": loc})
        self._send(405)

    def do_DELETE(self):
        self._send(200)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if self.path == "/register":
            meta = json.loads(raw)
            return self._json(201, {**meta, "client_id": "CID", "client_secret": "CSECRET"})
        if self.path == "/token":
            form = parse_qs(raw.decode())
            FakeZoho.log.append(("token", form["grant_type"][0], form.get("code", [""])[0]))
            return self._json(200, {"access_token": "AT", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "RT"})
        if self.path.startswith("/mcp/KEY/message"):
            if self.headers.get("Authorization") != "Bearer AT":
                return self._send(401, b"Authentication required", "text/plain", {
                    "WWW-Authenticate": f'Bearer resource_metadata="{self.base}/.well-known/oauth-protected-resource"'})
            msg = json.loads(raw)
            if msg.get("method") == "initialize":
                return self._json(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {
                    "protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-zoho", "version": "1"}}})
            if msg.get("method") == "tools/list":
                return self._json(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [
                    {"name": "get_portals", "inputSchema": {"type": "object"}}]}})
            return self._send(202)
        self._send(404)


@pytest.fixture
def fake_zoho(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOHO_SKILLS_HOME", str(tmp_path / "zs"))
    FakeZoho.log = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeZoho)
    FakeZoho.base = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield FakeZoho.base + "/mcp/KEY/message"
    srv.shutdown()


def test_unauthenticated_gives_a_sign_in_error(fake_zoho):
    with pytest.raises(BaseException) as e:
        asyncio.run(upstream.list_tools_once(fake_zoho))
    assert upstream.is_auth_error(e.value) and "zoho-skills login" in upstream.describe_error(e.value)


def test_full_login_flow_stores_tokens_and_then_serves_authenticated_calls(fake_zoho):
    messages = []

    def announce(m):
        messages.append(m)
        if "http://127.0.0.1" in m and "/authorize" in m:  # act as the browser: open the authorize URL
            url = m.split()[-1]
            threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=10).read(), daemon=True).start()

    n = asyncio.run(asyncio.wait_for(auth.login(fake_zoho, scopes=["zohoprojects.tasks.read", "ZohoMCP.tool.execute"],
                                                open_browser=False, announce=announce, timeout=20), 60))
    assert n == 1
    assert any("Waiting for you to approve" in m for m in messages) and any("collecting your access token" in m for m in messages)
    assert ("authorize", "zohoprojects.tasks.read ZohoMCP.tool.execute") in FakeZoho.log
    assert ("token", "authorization_code", "GOODCODE") in FakeZoho.log
    assert auth.is_logged_in(fake_zoho) and stat.S_IMODE(auth.token_path().stat().st_mode) == 0o600
    # a later (non-interactive) run reuses the stored token with no browser
    tools = asyncio.run(asyncio.wait_for(upstream.list_tools_once(fake_zoho), 30))
    assert [t.name for t in tools] == ["get_portals"]
