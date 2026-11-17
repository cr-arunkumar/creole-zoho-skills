"""Client for the upstream Zoho Projects MCP server (streamable HTTP, SSE, or a stdio command for tests)."""
from __future__ import annotations

import contextlib
import os
from typing import Optional

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

try:  # builtin on Python 3.11+; anyio uses the `exceptiongroup` backport on 3.10
    BaseExceptionGroup
except NameError:  # pragma: no cover
    from exceptiongroup import BaseExceptionGroup


class UpstreamError(Exception):
    pass


def _leaves(e: BaseException):
    if isinstance(e, BaseExceptionGroup):  # anyio task groups wrap the real error
        for x in e.exceptions:
            yield from _leaves(x)
    else:
        yield e


def is_auth_error(e: BaseException) -> bool:
    from . import auth
    for leaf in _leaves(e):
        if isinstance(leaf, auth.AuthRequired):
            return True
        status = getattr(getattr(leaf, "response", None), "status_code", None)
        if status in (401, 403):
            return True
    return False


def describe_error(e: BaseException) -> str:
    """One readable, secret-free sentence for whatever went wrong talking to Zoho (unwraps ExceptionGroups)."""
    from . import auth
    leaves = list(_leaves(e))
    for leaf in leaves:
        if isinstance(leaf, auth.AuthRequired):
            return str(leaf)
    for leaf in leaves:
        status = getattr(getattr(leaf, "response", None), "status_code", None)
        if status in (401, 403):
            return f"Zoho rejected the connection (HTTP {status}): sign-in required — {auth.RELOGIN}"
        if status == 404:
            return "Zoho endpoint not found (HTTP 404): check the MCP URL and data-centre region"
        if status:
            return f"Zoho MCP server error (HTTP {status})"
    leaf = leaves[0]
    name = type(leaf).__name__
    if "Connect" in name or "Timeout" in name:
        return f"cannot reach the Zoho MCP host ({name}): check your network and the MCP URL"
    return f"{name}: {leaf}"[:300]


async def _open(stack: contextlib.AsyncExitStack, url: Optional[str], command: Optional[list],
                auth=None) -> ClientSession:
    if command:
        r, w = await stack.enter_async_context(stdio_client(StdioServerParameters(command=command[0], args=command[1:], env=dict(os.environ))))
    elif url and url.rstrip("/").endswith("/sse"):
        from mcp.client.sse import sse_client
        r, w = await stack.enter_async_context(sse_client(url, auth=auth))
    elif url:
        from mcp.client.streamable_http import streamablehttp_client
        r, w, _ = await stack.enter_async_context(streamablehttp_client(url, auth=auth))
    else:
        raise UpstreamError("no Zoho MCP URL configured (run: zoho-skills onboard)")
    session = await stack.enter_async_context(ClientSession(r, w))
    await session.initialize()
    return session


@contextlib.asynccontextmanager
async def connect(url: Optional[str] = None, command: Optional[list] = None, auth=None):
    """Yield an initialised ClientSession; everything is closed on exit (same task that entered).
    `auth` defaults to the stored Zoho OAuth session, if the user has signed in."""
    if auth is None and url and not command:
        from . import auth as auth_mod
        auth = auth_mod.runtime_provider(url)
    async with contextlib.AsyncExitStack() as stack:
        yield await _open(stack, url, command, auth)


async def list_tools_once(url: Optional[str] = None, command: Optional[list] = None) -> list:
    """Read-only reachability/inventory check used by onboarding and `doctor`."""
    async with connect(url, command) as s:
        res: types.ListToolsResult = await s.list_tools()
        return res.tools
