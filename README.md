# creole-zoho-skills

Zoho Projects automation for AI coding agents, built from **skills** — one skill per organisation on top of a generic core.
Point any supported harness at this repo (or install it) and the agent knows how to create tasks, write titles,
descriptions and progress comments, log time and move work to review **in your org's format**.

| Skill | Purpose |
|-------|---------|
| `zoho-projects-core` | Org-neutral workflow: resolve ids, "last create" defaults, dry-run before writes, read-only mode |
| `creole-studios-zoho` | Creole Studios rules from the Zoho Task Evaluation guide: title/description/comment standards, time, **In QA Review**, scoring rubric + linter |
| `templates/org-skill` | Starting point for another organisation (see `skills/zoho-projects-core/references/org-skill-spec.md`) |

Org rules live **only** in the org skill; the core never contains them.

## Install
Everything is Python 3.9+ standard library.

```bash
# Claude Code / Claude.ai  (or: /plugin marketplace add <this repo>)
python3 scripts/install.py --harness claude --global

# Cursor (writes .cursor/rules/*.mdc into a project)
python3 scripts/install.py --harness cursor --project ~/code/my-app

# Antigravity / Gemini CLI
python3 scripts/install.py --harness antigravity --global

# Codex, Copilot and other AGENTS.md-aware tools
python3 scripts/install.py --harness codex --project ~/code/my-app

# Everything, preview only
python3 scripts/install.py --harness all --project . --dry-run
```
Or just open this repo in the harness: root `AGENTS.md` / `GEMINI.md` point at `skills/`, and generated copies are
committed in `.claude/skills`, `.agent/skills`, `.cursor/rules`.

Then connect the Zoho Projects MCP server: `skills/zoho-projects-core/references/mcp-setup.md`.

## Safety model
- Reads first; ids are resolved at runtime, never hardcoded.
- **Every create/update is previewed and needs explicit confirmation**; read-only mode never writes.
- No secrets in the repo; auth goes through the harness's MCP/OAuth.
- The Python helpers never call Zoho. If the connected MCP server has no comment/time-log tool, the agent hands you
  ready-to-paste text instead of claiming it posted.

## Creole Studios scoring helper
```bash
echo '{"title":"Upgrade PHP on Site A [4.0 hrs]","description":"...","comment":"...","planned_minutes":240,"logged_minutes":240,"status":"In QA Review"}' \
  | python3 skills/creole-studios-zoho/scripts/lint_task.py --json
```
The estimated score is a heuristic derived from the guide's 10 reference examples — not the real evaluation engine.
10.0 is the maximum on the scale.

## Optional: local API + SQLite
`pip install -r api/requirements.txt && uvicorn api.app:app --port 8787` → `/lint`, `/drafts`, `/context/last`.
State is a local SQLite file (`$ZOHO_SKILL_DB`, default `~/.creole-zoho-skills/state.db`).

## Add your organisation
Copy `templates/org-skill` to `skills/<org>-zoho/`, fill in the conventions, add tests, run
`python3 scripts/build_adapters.py`, then `python3 -m pytest -q tests`.

## Develop
`skills/` is the source of truth. After editing: `python3 scripts/build_adapters.py` (CI runs `--check`).
