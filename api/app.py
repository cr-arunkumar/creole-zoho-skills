"""Optional local helper API (FastAPI + file-based SQLite). Never calls Zoho.

Run:  pip install -r api/requirements.txt && uvicorn api.app:app --port 8787
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

from fastapi import FastAPI
from pydantic import BaseModel, Field

_SKILLS = pathlib.Path(__file__).resolve().parents[1] / "skills"
_DIRS = {"lint_task": _SKILLS / "creole-studios-zoho" / "scripts", "store": _SKILLS / "zoho-projects-core" / "scripts"}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _DIRS[name] / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lint_task = _load("lint_task")
store = _load("store")

app = FastAPI(title="creole-zoho-skills helper", version="0.1.0")


class TaskIn(BaseModel):
    title: str = ""
    description: str = ""
    comment: str = ""
    planned_minutes: int | None = None
    logged_minutes: int | None = None
    status: str = ""
    final: bool = True


class DraftIn(TaskIn):
    zoho_task_id: str | None = None
    org: str | None = None
    project: str | None = None
    task_list: str | None = None
    parent: str | None = None
    owner: str | None = None
    est_score: float | None = Field(default=None, ge=0, le=10)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/lint")
def lint(task: TaskIn) -> dict:
    r = lint_task.lint(task.model_dump())
    return {"score": r.score, "errors": r.errors, "warnings": r.warnings, "notes": r.notes}


@app.get("/context/last")
def last_context(org: str | None = None) -> dict | None:
    return store.last_context(store.connect(), org)


@app.post("/drafts")
def save_draft(d: DraftIn) -> dict:
    data = {k: v for k, v in d.model_dump().items() if v is not None and k != "final"}
    return {"id": store.save_draft(store.connect(), data)}


@app.get("/drafts")
def drafts(limit: int = 10) -> list[dict]:
    return store.history(store.connect(), limit)
