"""Write gate: forwarded create/update tools run only with a confirm token that binds the exact (tool, args) that
were previewed. Tokens are HMAC-signed with a per-process key, single-use and short-lived. The gate guarantees that
what executes equals what was previewed; it cannot itself prove a human read the preview (see README)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Callable

READ_PREFIXES = ("get_", "list_", "search_", "find_", "read_", "fetch_", "describe_", "count_", "view_")
TOKEN_FIELD = "confirm_token"


def is_write_tool(name: str) -> bool:
    """Safe default: anything that is not clearly a read is treated as a write."""
    return not name.lower().startswith(READ_PREFIXES)


def canonical(tool: str, args: dict) -> str:
    clean = {k: v for k, v in (args or {}).items() if k != TOKEN_FIELD}
    return tool + "|" + json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)


class Gate:
    def __init__(self, ttl: int = 300, now: Callable[[], float] = time.time) -> None:
        self._key = os.urandom(32)
        self._ttl, self._now = ttl, now
        self._used: set = set()

    def _sig(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, tool: str, args: dict) -> str:
        exp = int(self._now()) + self._ttl
        nonce = secrets.token_hex(8)
        body = f"{exp}.{nonce}"
        return f"{body}.{self._sig(body + '|' + canonical(tool, args))}"

    def verify(self, tool: str, args: dict, token: str) -> tuple:
        """Return (ok, reason). A valid token is consumed."""
        try:
            exp_s, nonce, sig = token.split(".")
            exp = int(exp_s)
        except (ValueError, AttributeError):
            return False, "malformed confirm_token"
        if token in self._used:
            return False, "confirm_token already used"
        if self._now() > exp:
            return False, "confirm_token expired; request a new preview"
        if not hmac.compare_digest(sig, self._sig(f"{exp_s}.{nonce}|{canonical(tool, args)}")):
            return False, "confirm_token does not match these arguments (they changed after the preview)"
        self._used.add(token)
        return True, "ok"
