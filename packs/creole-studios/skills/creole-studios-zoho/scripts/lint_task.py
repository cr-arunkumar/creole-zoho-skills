#!/usr/bin/env python3
"""Offline linter + heuristic score estimator for Creole Studios Zoho tasks.

Standard library only. Never talks to Zoho. The score is a *heuristic* derived from the
10 examples in the Zoho Task Evaluation guide, not the real evaluation engine.

Usage:
  echo '{"title": "...", "description": "...", "comment": "...",
         "planned_minutes": 240, "logged_minutes": 235,
         "status": "In QA Review"}' | python3 lint_task.py --json
  python3 lint_task.py --title "Fix login [2.0 hrs]" --description "..." --comment "..." \
      --planned 120 --logged 118 --status "In QA Review"
Exit code: 0 = no errors, 1 = errors found, 2 = bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field

QA_STATUS = "in qa review"
GRACE_MIN = 5
TITLE_MAX = 200
TITLE_TAG = re.compile(r"\s\[\d+(?:\.\d)? hrs\]$")
GENERIC_TITLES = {"task", "update", "work", "misc", "fix", "changes", "development"}
STRONG_VERBS = {
    "implement", "fix", "upgrade", "review", "migrate", "build", "create", "add", "refactor",
    "design", "integrate", "configure", "write", "optimize", "debug", "test", "document",
    "deploy", "research", "analyze", "update", "remove", "setup", "set", "improve", "meeting",
}
BLOCKER_WORDS = re.compile(r"\b(blocked|blocker|waiting on|waiting for|credential|access|dependency|"
                           r"unavailable|permission|not provided)\b", re.I)
PENDING_WORDS = re.compile(r"\b(pending|todo|to-do|tomorrow|not done|remaining|yet to)\b", re.I)
CHECKLIST_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*.+?[-–:]\s*(done|pending|completed|ok|yes)\.?\s*$", re.I)
TECH_SIGNAL = re.compile(r"(`[^`]+`|\b[\w./-]+\.[a-z]{1,5}\b|\b\d+\s*(tests?|cases?|endpoints?|files?|migrations?)\b|"
                         r"\b(tested|verified|passed|passing|migration|schema|endpoint|api|function|"
                         r"module|class|query|index|policy|package|upgraded|resolved)\b)", re.I)


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float = 10.0
    notes: list[str] = field(default_factory=list)

    def cap(self, value: float, why: str) -> None:
        if self.score > value:
            self.notes.append(f"cap {value}: {why}")
            self.score = value

    def deduct(self, amount: float, why: str) -> None:
        self.notes.append(f"-{amount}: {why}")
        self.score = max(0.0, self.score - amount)


def words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def is_checklist_copy(comment: str) -> bool:
    lines = [ln for ln in (comment or "").splitlines() if ln.strip()]
    if not lines:
        return False
    hits = sum(1 for ln in lines if CHECKLIST_LINE.match(ln))
    if hits >= 2 and hits / len(lines) >= 0.6:
        return True
    # inline form: "1. Setup DB - Done, 2. Update API - Done, 3. Testing - Done"
    return len(re.findall(r"\d+[.)]\s*[^,.;]+?\s[-–]\s*(?:done|pending|completed)", comment or "", re.I)) >= 2


def lint(task: dict) -> Result:
    r = Result()
    title = (task.get("title") or "").strip()
    desc = (task.get("description") or "").strip()
    comment = (task.get("comment") or "").strip()
    planned = task.get("planned_minutes")
    logged = task.get("logged_minutes")
    status = (task.get("status") or "").strip().lower()
    final = bool(task.get("final", True))

    # --- title ---
    if not title:
        r.errors.append("title is empty: derive '<Verb> <object> <system> [X.X hrs]' from the description")
    else:
        if len(title) > TITLE_MAX:
            r.errors.append(f"title is {len(title)} chars (max {TITLE_MAX})")
        if title.lower().rstrip(".") in GENERIC_TITLES or words(title) < 2:
            r.errors.append("title is too generic; use '<Verb> <object> <system>'")
        elif title.split()[0].lower() not in STRONG_VERBS:
            r.warnings.append("title should start with a verb (Implement, Fix, Upgrade, Review…)")
        if not TITLE_TAG.search(title):
            r.warnings.append("title should end with the planned hours tag like ' [4.0 hrs]'")
        elif planned:
            tag_h = float(TITLE_TAG.search(title).group(0).strip(" []hrs"))
            if abs(tag_h * 60 - planned) > 1:
                r.warnings.append(f"title hours {tag_h} != planned {planned / 60:.1f}h")

    # --- hard zero gates ---
    if not desc:
        r.errors.append("description is blank (score 0.0)")
        r.score = 0.0
        r.notes.append("0.0: blank description")
    if logged is not None and logged <= 0:
        r.errors.append("no time logged (score 0.0)")
        r.score = 0.0
        r.notes.append("0.0: 0 hours logged")

    # --- description ---
    dw = words(desc)
    if desc and dw <= 6:
        r.errors.append(f"description has {dw} words; needs > 6 and acceptance criteria")
        r.deduct(4.5, "super short description")
    elif desc and dw < 40:
        r.warnings.append(f"description has {dw} words; aim for 40–60 with scope, specifics, 'done' criteria")

    # --- comment ---
    cw = words(comment)
    if final:
        if not comment:
            r.errors.append("no progress comment")
            r.score = 0.0 if not desc else min(r.score, 0.0)
            r.notes.append("0.0: no comment")
        elif cw <= 3:
            r.errors.append(f"comment has {cw} words ('Done'/'Fixed' gives no audit trail)")
            r.cap(4.0, "single-word/superficial comment")
        elif is_checklist_copy(comment):
            r.errors.append("comment copies the checklist with Done/Pending; explain the technical work")
            r.cap(5.2, "checklist copy-paste comment")
        else:
            if cw < 15:
                r.warnings.append(f"comment has {cw} words; name files/APIs/schemas and how it was tested")
                r.cap(7.5, "concise comment on a multi-requirement ticket")
            elif cw < 25:
                r.warnings.append(f"comment has {cw} words; aim for 25–60")
            if not TECH_SIGNAL.search(comment):
                r.warnings.append("comment lacks concrete technical specifics (file, endpoint, package, test count)")
            if "test" not in comment.lower() and "verif" not in comment.lower():
                r.warnings.append("comment should say how the work was tested/verified")
        if planned and planned >= 180 and PENDING_WORDS.search(comment) and not BLOCKER_WORDS.search(comment):
            r.errors.append("deliverables left pending on a >=3h task without a documented external blocker")
            r.cap(5.0, "partial delivery without documented blocker")

    # --- time ---
    if planned and logged and logged > 0:
        over = logged - planned
        if over > GRACE_MIN:
            beyond = over - GRACE_MIN
            r.errors.append(f"logged {logged}m vs planned {planned}m: {over}m over (+{GRACE_MIN}m grace)")
            r.deduct(min(5.0, 2.0 + 0.04 * beyond), "overran planned time")
            if not BLOCKER_WORDS.search(comment):
                r.warnings.append("add a comment explaining the roadblock behind the overrun")
        if logged < 0.5 * planned and planned >= 120:
            r.warnings.append(f"logged {logged}m is <50% of planned {planned}m; use spare time for unit tests/edge cases")
            r.deduct(1.0, "rushed execution") if cw < 25 else None

    # --- status gate ---
    if final and status != QA_STATUS:
        r.errors.append(f"status is '{task.get('status')}'; move to 'In QA Review' with self-testing notes")
        r.deduct(1.0, "status gate")
    if final and comment and "test" not in comment.lower() and status == QA_STATUS:
        r.warnings.append("add self-testing notes to the QA Review comment")

    r.score = round(max(0.0, min(10.0, r.score)), 1)
    # A clean pass still only reaches 10 with test evidence; mirror the 9.8 reference example.
    if r.score == 10.0 and not (final and re.search(r"\b\d+\s*(tests?|cases?)\b|passing|passed", comment, re.I)):
        r.score = 9.8
        r.notes.append("9.8: add concrete test evidence (counts/commands) to reach 10.0")
    return r


def render(r: Result) -> str:
    out = [f"Estimated score (heuristic): {r.score:.1f} / 10"]
    out += [f"ERROR  {m}" for m in r.errors] + [f"WARN   {m}" for m in r.warnings]
    out += [f"note   {m}" for m in r.notes]
    if not r.errors and not r.warnings:
        out.append("OK: no issues found")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="read task JSON from stdin")
    ap.add_argument("--title"); ap.add_argument("--description"); ap.add_argument("--comment")
    ap.add_argument("--planned", type=int, help="planned minutes")
    ap.add_argument("--logged", type=int, help="logged minutes")
    ap.add_argument("--status")
    ap.add_argument("--draft", action="store_true", help="skip comment/status gates (pre-start check)")
    a = ap.parse_args(argv)
    if a.json:
        try:
            task = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"bad JSON: {e}", file=sys.stderr)
            return 2
    else:
        task = {"title": a.title, "description": a.description, "comment": a.comment,
                "planned_minutes": a.planned, "logged_minutes": a.logged, "status": a.status}
    if a.draft:
        task["final"] = False
    r = lint(task)
    print(render(r))
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
