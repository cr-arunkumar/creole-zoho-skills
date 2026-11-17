"""Last-context / draft history. Reuses the core skill's SQLite helper (standard library) so the CLI, the skill
scripts and the MCP server share one schema. Default DB: <config dir>/state.db."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from . import adapters, config

_mod = None


def _core():
    global _mod
    if _mod is None:
        path = adapters.DATA / "skills" / "zoho-projects-core" / "scripts" / "store.py"
        spec = importlib.util.spec_from_file_location("zoho_core_store", path)
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
    return _mod


def connect():
    os.environ.setdefault("ZOHO_SKILL_DB", str(config.config_dir() / "state.db"))
    Path(os.environ["ZOHO_SKILL_DB"]).parent.mkdir(parents=True, exist_ok=True)
    return _core().connect()


def last_context(org=None):
    con = connect()
    try:
        return _core().last_context(con, org)
    finally:
        con.close()


def save_context(task: dict) -> int:
    con = connect()
    try:
        return _core().save_draft(con, task)
    finally:
        con.close()
