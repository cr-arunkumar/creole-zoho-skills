# Zoho Task Evaluation — scoring rubric (from the Creole Studios guide)

Every task is scored 0.0–10.0 from Zoho data: description, comments, timelogs, status, planned vs logged time.
The engine checks that comments genuinely substantiate the work described. It also adapts to experience level and
subscribed AI tools (Cursor, Copilot, Claude Pro): expect tighter time expectations when AI tools are available.

## Daily habits (what to do)
1. **Clear descriptions** before starting: what is built, requirements, what "done" looks like. No empty or one-line ("update code") descriptions.
2. **Meaningful technical comments** on update/close: files/modules changed, APIs/schemas touched, packages upgraded, errors resolved, how it was tested. Not "Done"/"Fixed"; not a pasted checklist with "- Done / - Pending".
3. **Stay on planned time; escalate early.** Finish close to estimate. Finished early → write unit tests and check edge cases. Running long → comment the roadblock immediately.
4. **Always move to "In QA Review"** after coding and self-testing, with self-testing notes. Leaving it In Progress/Backlog signals skipped verification.
5. **Meetings:** log under a dedicated meeting task; if inside a technical task, mention the meeting in the description and explain what was discussed in comments.

## Score bands and the 10 reference examples
| # | Score | Situation | Why |
|---|-------|-----------|-----|
| 1 | 9.8 | Planned 4h, logged 4h, In QA Review; ~50-word description (PostgreSQL RLS setup, role policies, migration scripts); comment cites `20261030_zoho_rls.sql`, helper functions, 8 passing pgTAP tests | Zero deductions; concrete code + automated testing; QA gate passed |
| 2 | 8.5 | Planned 4h, logged 6h, senior dev with Cursor | −1.5 time inflation (>35% over for senior with AI tools) |
| 3 | 7.2 | Detailed 45-word multi-requirement description, comment is one line (10 words) | Scope-substantiation gap → 7.0–7.5 |
| 4 | 6.2 | Good work, left In Progress | −1.0 flat status-gate deduction |
| 5 | 5.2 | Comment copies checklist "1. Setup DB - Done…" | Capped at 5.2: mirrors checklist, no substance |
| 6 | 5.0 | ≥3h ticket closed with core deliverables "pending" and no documented external blocker | Capped at 5.0 (partial delivery) |
| 7 | 5.0 | Planned 2h, logged 3h30 (85 min past the +5 min grace) | −2.0 immediate cut + scaled penalty; time score 3.0 |
| 8 | 4.0 | Comment is "Done"/"Fixed" (1–3 words) | No audit trail |
| 9 | 3.5 | 5-word description, 5-word comment, 1h15 of 4h, left In Progress | −4.5 short description (≤6 words, no acceptance criteria), −2.0 insufficient explanation, −1.0 status |
| 10 | 0.0 | 0h logged, or blank description / no comments | Flat zero |

## Checklist to hit 9.0–10.0
- [ ] Description ≥ 40 words with scope, technical specifics and acceptance criteria
- [ ] Comment 25–60 words naming concrete artifacts (file/migration/endpoint/package) + test evidence (counts, commands)
- [ ] Logged hours > 0 and within planned time + 5 minutes
- [ ] No deliverable "pending" unless an external blocker is named
- [ ] Status = **In QA Review** with self-testing notes
- [ ] Meetings logged under a meeting task (or explained)
