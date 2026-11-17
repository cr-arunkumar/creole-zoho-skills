---
name: creole-studios-zoho
description: Creole Studios (portal creolestudiosdotcom1) rules for Zoho Projects — task title format, 40–60 word descriptions, substantive technical comments, time logging and moving tasks to "In QA Review" so the daily Zoho Task Evaluation scores 9.0–10.0. Use when the Zoho portal org is Creole Studios, or the user mentions Creole Studios Zoho tasks, daily evaluation, task score, logging hours, or "move to QA".
---

# Creole Studios — Zoho Projects rules

Requires `zoho-projects-core` (read-first, ID resolution, dry-run, read-only mode). These rules override its defaults.
Goal: every task, description, comment and status change scores 9.0–10.0 on the Creole Studios Zoho Task Evaluation
(10.0 is the ceiling; the aim is to remove every deduction in `references/scoring-rubric.md`).

## Standards at a glance
| Area | Rule |
|------|------|
| Title | `<Verb> <object> <system> [X.X hrs]`, ≤ 200 chars. Empty title → derive from the description |
| Description | 40–60 words: scope, requirements, files/APIs/schemas, "done" criteria. Never blank, never ≤ 6 words |
| Progress comment | 25–60 words: files/modules changed, APIs/schemas/packages, errors resolved, how tested (counts/commands). Never "Done"/"Fixed", never a copied checklist |
| Time | Finish within planned + 5 min. Early → add unit tests/edge cases. Running long → comment the roadblock immediately. Log actual hours (0h = score 0.0) |
| Status | Backlog → In Progress → **In QA Review** (with self-testing notes). Never leave finished work In Progress; never mark Completed |
| Partial delivery | On ≥ 3h tasks don't leave deliverables "pending" unless an external blocker is named (cap 5.0) |
| Meetings | Dedicated meeting task; if logged in a technical task, mention it in the description and explain it in comments |

## Workflow
**Create** — collect what/who/hours/billable; default project, list and parent to the last created task (core step 2);
build title + description; run `python3 scripts/lint_task.py --draft --json`; fix every ERROR/WARN; dry-run; create in
the person's weekly bucket (`W47 …` → `Name: N hours`) with status Backlog (or In Progress if already started).

**Update / finish** — read the task; draft the technical comment; lint with the final fields
(`python3 scripts/lint_task.py --json`); dry-run; post the comment and hours (or output them ready-to-paste if the
server has no comment/timelog tool); set status **In QA Review**.

**Audit** — for "how will this score?" run the linter on the task's fields; report the estimated score (a
heuristic from the guide's 10 examples, not the real engine), each deduction, and the rewrite that removes it.

## References
- `references/conventions.md` — hierarchy, title format, statuses, ids
- `references/scoring-rubric.md` — the guide's 10 scored examples, deductions and checklist
- `references/examples.md` — before/after titles, descriptions, comments
- `scripts/lint_task.py` — offline checker + estimated score
