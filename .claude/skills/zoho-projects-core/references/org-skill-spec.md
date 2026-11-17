# Writing an org skill

One org = one skill folder `skills/<org-slug>-zoho/`. The core skill finds it by matching the Zoho portal's
`org_name` against the skill's `description`, so name the organisation explicitly there.

## Required files
```
skills/<org-slug>-zoho/
  SKILL.md                    # frontmatter (name, description naming the org) + workflow; says "requires zoho-projects-core"
  references/conventions.md   # hierarchy, title/description/comment standards, statuses, time rules, billing
  references/examples.md      # before/after titles, descriptions, comments
```
## Optional
- `references/scoring-rubric.md` — if the org evaluates tasks (document the deductions and caps)
- `scripts/lint_<org>.py` — stdlib-only linter; print errors/warnings and exit non-zero on errors
- `tests/test_<org>.py` — encode the org's own examples as tests

## Contract
- Org rules **override** core defaults; they never weaken core safety rules (dry-run, read-first, read-only).
- No hardcoded numeric Zoho ids as truth: record them as "observed — verify before use" and resolve at runtime.
- No secrets. No org data from other orgs.

## Checklist
- [ ] `description` names the org and the triggers (Zoho, task, comment, status…)
- [ ] Title, description, comment standards each have a good and bad example
- [ ] Status workflow and the final status developers must reach are stated
- [ ] Time rules (estimates, grace buffer, logging) stated
- [ ] Linter (if any) has tests; `scripts/build-adapters.sh` run so Cursor/Antigravity copies are regenerated
