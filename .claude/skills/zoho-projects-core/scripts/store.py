#!/usr/bin/env python3
"""Tiny file-based SQLite store (standard library only) for local drafts and "last create" context.

Never talks to Zoho. Default DB: $ZOHO_SKILL_DB or ~/.creole-zoho-skills/state.db

  python3 store.py save-draft --json < task.json     # remember a drafted/created task
  python3 store.py last [--org "Creole Studios"]     # last saved context (org, project, list, parent, owner)
  python3 store.py history --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  zoho_task_id TEXT,
  org TEXT, project TEXT, task_list TEXT, parent TEXT, owner TEXT,
  title TEXT, description TEXT, comment TEXT,
  planned_minutes INTEGER, logged_minutes INTEGER,
  status TEXT, est_score REAL
);
CREATE INDEX IF NOT EXISTS idx_drafts_created ON drafts(created_at DESC, id DESC);
"""
FIELDS = ["zoho_task_id", "org", "project", "task_list", "parent", "owner", "title", "description",
          "comment", "planned_minutes", "logged_minutes", "status", "est_score"]


def db_path() -> Path:
    p = Path(os.environ.get("ZOHO_SKILL_DB") or Path.home() / ".creole-zoho-skills" / "state.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or db_path()))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def save_draft(con: sqlite3.Connection, task: dict) -> int:
    cols = [f for f in FIELDS if f in task]
    cur = con.execute(
        f"INSERT INTO drafts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        [task[c] for c in cols],
    )
    con.commit()
    return int(cur.lastrowid)


def last_context(con: sqlite3.Connection, org: str | None = None) -> dict | None:
    sql = ("SELECT org, project, task_list, parent, owner, planned_minutes, zoho_task_id FROM drafts "
           "WHERE project IS NOT NULL")
    args: tuple = ()
    if org:
        sql, args = sql + " AND org = ?", (org,)
    row = con.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
    return dict(row) if row else None


def history(con: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = con.execute("SELECT * FROM drafts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save-draft"); s.add_argument("--json", action="store_true", required=True)
    l = sub.add_parser("last"); l.add_argument("--org")
    h = sub.add_parser("history"); h.add_argument("--limit", type=int, default=10)
    a = ap.parse_args(argv)
    con = connect()
    if a.cmd == "save-draft":
        print(json.dumps({"id": save_draft(con, json.load(sys.stdin))}))
    elif a.cmd == "last":
        print(json.dumps(last_context(con, a.org), indent=2))
    else:
        print(json.dumps(history(con, a.limit), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
