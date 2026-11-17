---
name: zoho-projects-core
description: Generic, org-agnostic workflow for automating Zoho Projects through its MCP server — resolving portal/project/list/parent/status IDs, drafting tasks, comments and status changes, dry-run before writes, and reusing the last-created context. Use whenever the user mentions Zoho Projects tasks, then load the matching org skill (for example creole-studios-zoho) for that organisation's rules.
---

# Zoho Projects Core

Org-neutral engine. **Organisation-specific rules (title format, description/comment standards, statuses, scoring)
live only in an org skill** such as `creole-studios-zoho`. This skill never contains them.

## Step 0 — find the org skill
1. Read `get_portals` and note `org_name` / `portal_name`.
2. Load the installed skill whose description names that organisation (e.g. portal org *Creole Studios* → `creole-studios-zoho`).
3. No matching org skill → work with the generic rules below, tell the user no org rules were applied, and point them to
   `references/org-skill-spec.md` to create one (template: `templates/org-skill/`).
Org skill rules always override the defaults here.

## Safety rules (always)
1. **Read first.** Resolve portal, project, task list, parent task, owner (`zpuid`) and status ids with read calls. Never hardcode ids; ids differ per portal.
2. **Dry-run before any write.** Show the exact payload (title, description, owner, hours, status, parent) and wait for an explicit "yes".
3. **Read-only mode.** If the user says read-only, never call a create/update tool.
4. **Never invent work.** Titles, descriptions and comments must reflect what the user actually did; ask when details are missing.
5. **No secrets in the repo.** Auth goes through the harness's MCP/OAuth flow.

## Generic workflow
1. **Resolve context**: `get_portals` → `get_projects_list` → `get_all_project_task_lists` → parent task via `get_tasks_by_project` (filter/sort as needed).
2. **"Last create" default**: when project/list/parent are unspecified, read the newest tasks (`sort_by=DESC(created_time)`), reuse that task's project, task list and parent, and confirm. Optionally persist it with `scripts/store.py`.
3. **Draft** title, description, owner, duration (`HH:MM`), billing type, status using the org skill's rules.
4. **Validate** with the org skill's linter if it ships one.
5. **Dry-run → confirm → write** with `create_a_task` / `update_a_task`. Status is sent as `status: {"id": "<id>"}` (names are rejected); resolve ids from the field-options lookup for module `tasks`, field `status`, filtered by project. Add owners on update with `owners: [{"add": [{"zpuid": "..."}]}]` — never send a plain owner array on update (it removes co-owners).
6. **Report** what changed with task ids/links; never claim a comment or timelog was posted if the connected server has no tool for it — output ready-to-paste text instead.

## Local state (optional)
`python3 scripts/store.py save-draft --json < task.json`, `last --org "<org>"`, `history`. File-based SQLite at
`$ZOHO_SKILL_DB` (default `~/.creole-zoho-skills/state.db`). Standard library only; never contacts Zoho.

## References
- `references/mcp-setup.md` — connect the Zoho Projects MCP in each harness
- `references/org-skill-spec.md` — how to write an org skill (contract, files, checklist)
