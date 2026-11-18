"""OAuth sign-in for the Zoho MCP server.

Zoho's MCP endpoint answers an unauthenticated request with `401 + WWW-Authenticate: Bearer resource_metadata=…`:
the URL alone is not a credential, the standard MCP OAuth flow (dynamic client registration + PKCE) is required.
`zoho-skills login` runs that flow once in the browser; the proxy then reuses and refreshes the stored tokens.
Tokens live in ~/.zoho-skills/oauth.json (owner-only), bound to the MCP URL they were issued for.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from . import config

# Scopes advertised by Zoho's MCP server for Projects + WorkDrive (fallback when the live list can't be fetched).
KNOWN_SCOPES = [
    "zohoprojects.portals.read", "zohoprojects.portals.create", "zohoprojects.portals.update", "zohoprojects.portals.delete",
    "zohoprojects.projects.read", "zohoprojects.projects.create", "zohoprojects.projects.update", "zohoprojects.projects.delete",
    "zohoprojects.projectgroups.read", "zohoprojects.projectgroups.create", "zohoprojects.projectgroups.update",
    "zohoprojects.projectgroups.delete",
    "zohoprojects.tasklists.read", "zohoprojects.tasklists.create", "zohoprojects.tasklists.update", "zohoprojects.tasklists.delete",
    "zohoprojects.tasks.read", "zohoprojects.tasks.create", "zohoprojects.tasks.update", "zohoprojects.tasks.delete",
    "zohoprojects.timesheets.read", "zohoprojects.timesheets.create", "zohoprojects.timesheets.update",
    "zohoprojects.milestones.read", "zohoprojects.milestones.create", "zohoprojects.milestones.update",
    "zohoprojects.milestones.delete",
    "zohoprojects.bugs.read", "zohoprojects.bugs.create", "zohoprojects.bugs.update", "zohoprojects.bugs.delete",
    "zohoprojects.tags.read", "zohoprojects.tags.create", "zohoprojects.tags.update", "zohoprojects.tags.delete",
    "zohoprojects.custom_fields.read", "zohoprojects.custom_fields.create", "zohoprojects.custom_fields.update",
    "zohoprojects.custom_fields.delete",
    "zohoprojects.users.read", "zohoprojects.users.create",
    "workdrive.workspace.all", "workdrive.files.all", "workdrive.team.all",
    "ZohoMCP.tool.execute",
]
SERVICE_LABELS = {"zohoprojects": "Zoho Projects", "workdrive": "Zoho WorkDrive", "zohomail": "Zoho Mail",
                  "zohocliq": "Zoho Cliq", "zohocrm": "Zoho CRM", "zohocalendar": "Zoho Calendar"}
WORK_ITEMS = {"tasks", "timesheets", "bugs", "tasklists", "milestones", "tags"}  # what "standard" may create/update
LEVELS = {
    "read": ("Read only", "view data; never create, change or delete"),
    "standard": ("Read + work items", "read everything; create/update tasks, time logs, bugs, task lists, milestones, tags; no deletes"),
    "full": ("Everything", "all permissions the server offers, including delete (and WorkDrive, which has no read-only scope)"),
    "custom": ("Custom", "pick individual permissions"),
}


def split_scope(scope: str) -> tuple:
    """'zohoprojects.tasks.read' -> ('zohoprojects', 'tasks', 'read')."""
    parts = scope.split(".")
    return parts[0].lower(), ".".join(parts[1:-1]), parts[-1].lower() if len(parts) > 1 else ""


def is_core(scope: str) -> bool:
    return scope.startswith("ZohoMCP.")  # lets the MCP server run tools at all; always requested


def services(scopes: list) -> dict:
    """service key -> its scopes (core ZohoMCP scopes excluded)."""
    out: dict = {}
    for sc in scopes:
        if not is_core(sc):
            out.setdefault(split_scope(sc)[0], []).append(sc)
    return out


def service_label(key: str) -> str:
    return SERVICE_LABELS.get(key, key.capitalize())


def select(scopes: list, chosen_services: list, level: str) -> list:
    """Scopes for the chosen services at an access level (+ the core scope the server always needs)."""
    out = [sc for sc in scopes if is_core(sc)]
    for sc in scopes:
        svc, res, action = split_scope(sc)
        if is_core(sc) or svc not in chosen_services:
            continue
        if level == "full" or (level == "read" and action == "read") or (
                level == "standard" and (action == "read" or (action in ("create", "update") and res in WORK_ITEMS))):
            out.append(sc)
    return out


DEFAULT_SCOPES = select(KNOWN_SCOPES, ["zohoprojects"], "standard")


def fetch_supported_scopes(url: str, timeout: float = 10) -> list:
    """Scopes the user's MCP server offers (public OAuth metadata); falls back to the known Zoho Projects list."""
    import httpx
    p = urlparse(url)
    try:
        r = httpx.get(f"{p.scheme}://{p.netloc}/.well-known/oauth-protected-resource", timeout=timeout)
        found = [x for x in r.json().get("scopes_supported", []) if isinstance(x, str)]
        if found:
            return found
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return list(KNOWN_SCOPES)


RELOGIN = "run `zoho-skills login`"


class AuthRequired(Exception):
    """No usable Zoho sign-in; the user must run `zoho-skills login`."""


def token_path():
    return config.config_dir() / "oauth.json"


class FileStorage:
    """TokenStorage backed by a 0600 JSON file, valid only for the MCP URL it was created for."""

    def __init__(self, url: str) -> None:
        self._server = hashlib.sha256(url.encode()).hexdigest()[:16]

    def _load(self) -> dict:
        try:
            d = json.loads(token_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) and d.get("server") == self._server else {}

    def _save(self, d: dict) -> None:
        d["server"] = self._server
        directory = config.config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".oauth-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, token_path())
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def has_tokens(self) -> bool:
        return bool(self._load().get("tokens"))

    def clear(self) -> None:
        if token_path().exists():
            token_path().unlink()

    async def get_tokens(self) -> Optional[OAuthToken]:
        t = self._load().get("tokens")
        return OAuthToken.model_validate(t) if t else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        d = self._load()
        d["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        self._save(d)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        c = self._load().get("client_info")
        return OAuthClientInformationFull.model_validate(c) if c else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        d = self._load()
        d["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        self._save(d)


def is_logged_in(url: str) -> bool:
    return FileStorage(url).has_tokens()


def logout(url: Optional[str] = None) -> bool:
    """Delete stored OAuth tokens. Returns True if a file was removed."""
    had = token_path().exists()
    FileStorage(url or "").clear()
    return had


def _metadata(redirect: str, scopes: list) -> OAuthClientMetadata:
    return OAuthClientMetadata(redirect_uris=[redirect], client_name="zoho-skills", scope=" ".join(scopes))


def runtime_provider(url: str) -> Optional[OAuthClientProvider]:
    """Non-interactive provider for the MCP server / doctor. None when never signed in (so no stray client
    registrations are created at Zoho); if a refresh later fails it raises AuthRequired instead of opening a browser."""
    storage = FileStorage(url)
    if not storage.has_tokens():
        return None

    async def no_browser(_auth_url: str) -> None:
        raise AuthRequired(f"Zoho session expired or revoked: {RELOGIN}")

    async def no_callback():
        raise AuthRequired(f"Zoho session expired or revoked: {RELOGIN}")

    return OAuthClientProvider(url, _metadata("http://127.0.0.1:0/callback", DEFAULT_SCOPES), storage,
                               no_browser, no_callback)


def parse_callback(request_target: str) -> tuple:
    """(code, state) from the browser's redirect, e.g. '/callback?code=…&state=…'. Raises AuthRequired on error."""
    u = urlparse(request_target)
    q = parse_qs(u.query)
    if u.path != "/callback" or not ("code" in q or "error" in q):
        raise ValueError("not the OAuth callback")
    if "error" in q:
        raise AuthRequired(f"Zoho authorization was not granted: {q['error'][0]}")
    return q["code"][0], (q.get("state") or [None])[0]


def parse_pasted(text: str) -> tuple:
    """(code, state) from what the user pasted: the full redirect URL from the browser's address bar."""
    text = text.strip()
    if "code=" not in text and "error=" not in text:
        raise ValueError("paste the full address of the page you were sent to (it contains ?code=…&state=…)")
    u = urlparse(text if "://" in text else "http://x" + (text if text.startswith("/") else "/callback?" + text.lstrip("?")))
    return parse_callback(f"/callback?{u.query}")


class PasteListener:
    """Fallback when the browser can't reach this machine's localhost (SSH, container, remote desktop): read the
    redirect URL from the terminal. A daemon thread, so it never blocks interpreter exit."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.fut: asyncio.Future = loop.create_future()
        import threading
        threading.Thread(target=self._read, args=(loop,), daemon=True).start()

    def _read(self, loop) -> None:
        while not self.fut.done():
            try:
                line = input()
            except EOFError:
                return
            if not line.strip():
                continue
            try:
                result = parse_pasted(line)
            except (ValueError, AuthRequired) as e:
                print(f"  {e}")
                continue
            loop.call_soon_threadsafe(lambda r=result: self.fut.done() or self.fut.set_result(r))
            return


class CallbackServer:
    """One-shot localhost listener that receives the OAuth redirect."""

    PAGE = ("<html><body style='font-family:sans-serif;padding:3em'><h2>zoho-skills</h2>"
            "<p>{msg} You can close this tab and return to the terminal.</p></body></html>")

    async def start(self) -> int:
        self._fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._srv = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._srv.sockets[0].getsockname()[1]
        return self.port

    async def _handle(self, reader, writer) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 10)).decode("latin1").split()
            while (await asyncio.wait_for(reader.readline(), 10)) not in (b"\r\n", b"\n", b""):
                pass
            try:
                result, msg, status = parse_callback(line[1] if len(line) > 1 else ""), "Signed in.", "200 OK"
                if not self._fut.done():
                    self._fut.set_result(result)
            except AuthRequired as e:
                msg, status = str(e), "400 Bad Request"
                if not self._fut.done():
                    self._fut.set_exception(e)
            except ValueError:
                msg, status = "Nothing to do here.", "404 Not Found"
            body = self.PAGE.format(msg=msg).encode()
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/html\r\nContent-Length: {len(body)}\r\n"
                         f"Connection: close\r\n\r\n".encode() + body)
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    async def wait(self, timeout: float) -> tuple:
        return await asyncio.wait_for(self._fut, timeout)

    async def close(self) -> None:
        self._srv.close()
        await self._srv.wait_closed()


async def login(url: str, *, scopes: Optional[list] = None, open_browser: bool = True,
                announce: Callable[[str], None] = print, timeout: float = 300, allow_paste: bool = False) -> int:
    """Interactive OAuth sign-in. Waits for Zoho's redirect back to a localhost listener (or, with allow_paste, a URL
    pasted into the terminal), exchanges the code for tokens and returns how many Zoho tools are then visible."""
    from . import upstream  # lazy: upstream imports this module
    srv = CallbackServer()
    port = await srv.start()
    storage = FileStorage(url)
    storage.clear()  # register a fresh client for this run's redirect port

    async def redirect_handler(auth_url: str) -> None:
        opened = False
        if open_browser:
            import webbrowser
            opened = webbrowser.open(auth_url)
        announce(("Opened your browser to authorise Zoho." if opened else "Open this URL in your browser to authorise Zoho:")
                 + ("" if opened else f"\n  {auth_url}"))

    async def callback_handler() -> tuple:
        announce(f"Waiting for you to approve in the browser (up to {int(timeout // 60)} min, Ctrl+C to cancel)…")
        waiters = [asyncio.ensure_future(srv.wait(timeout))]
        if allow_paste:
            announce("Different machine than your browser? Paste the final page's full address here and press Enter:")
            waiters.append(PasteListener(asyncio.get_running_loop()).fut)
        done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for w in pending:
            w.cancel()
        result = done.pop().result()
        announce("Approved in Zoho — collecting your access token…")
        return result

    provider = OAuthClientProvider(url, _metadata(f"http://127.0.0.1:{port}/callback", scopes or DEFAULT_SCOPES),
                                   storage, redirect_handler, callback_handler, timeout)
    try:
        async with upstream.connect(url, auth=provider) as session:
            return len((await session.list_tools()).tools)
    finally:
        await srv.close()
