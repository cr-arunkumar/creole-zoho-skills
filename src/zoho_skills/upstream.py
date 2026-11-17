"""Client for the upstream Zoho Projects MCP server (streamable HTTP, SSE, or a stdio command for tests)."""
from __future__ import annotations

import contextlib
import os
from typing import Optional

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


class UpstreamError(Exception):
    pass


async def _open(stack: contextlib.AsyncExitStack, url: Optional[str], command: Optional[list]) -> ClientSession:
    if command:
        r, w = await stack.enter_async_context(stdio_client(StdioServerParameters(command=command[0], args=command[1:], env=dict(os.environ))))
    elif url and url.rstrip("/").endswith("/sse"):
        from mcp.client.sse import sse_client
        r, w = await stack.enter_async_context(sse_client(url))
    elif url:
        from mcp.client.streamable_http import streamablehttp_client
        r, w, _ = await stack.enter_async_context(streamablehttp_client(url))
    else:
        raise UpstreamError("no Zoho MCP URL configured (run: zoho-skills onboard)")
    session = await stack.enter_async_context(ClientSession(r, w))
    await session.initialize()
    return session


@contextlib.asynccontextmanager
async def connect(url: Optional[str] = None, command: Optional[list] = None):
    """Yield an initialised ClientSession; everything is closed on exit (same task that entered)."""
    async with contextlib.AsyncExitStack() as stack:
        yield await _open(stack, url, command)


async def list_tools_once(url: Optional[str] = None, command: Optional[list] = None) -> list:
    """Read-only reachability/inventory check used by onboarding and `doctor`."""
    async with connect(url, command) as s:
        res: types.ListToolsResult = await s.list_tools()
        return res.tools
