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

## Install (one line)
```bash
curl -fsSL https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh | sh
```
Starts an interactive onboarding (needs Python 3.9+, no other dependencies):

1. **Skills** — pick which skills to install (`zoho-projects-core` is always included).
2. **Harnesses** — Claude Code, Cursor, Antigravity / Gemini CLI, Codex / Copilot (AGENTS.md); detected ones are pre-ticked.
3. **Scope** — global (`$HOME`) or a project folder.
4. **Zoho MCP** — paste your Zoho Projects MCP URL; it is registered with every chosen harness
   (`claude mcp add`, `~/.cursor/mcp.json`, `~/.gemini/settings.json`, `~/.codex/config.toml`). Existing config is
   preserved and backed up to `*.bak`. The URL may contain a key, so it is written only to your harness config and is
   masked in output. Authenticate in the harness afterwards (Claude Code: `/mcp`).
5. **Review → confirm → install.**

The installer leaves a `creole-zoho` command in `~/.local/bin`:
```bash
creole-zoho                 # onboarding again
creole-zoho list            # skills and harnesses
creole-zoho doctor          # harnesses found, skills installed, MCP registered
creole-zoho update          # fetch the latest version
```
Non-interactive (CI, dotfiles):
```bash
creole-zoho install --yes --harness claude,cursor --project ~/code/app --mcp-url "$ZOHO_MCP_URL" [--skills a,b] [--no-mcp] [--dry-run]
# or straight from curl:
curl -fsSL https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh | sh -s -- install --yes --harness all --global --no-mcp
```
Env: `CZ_REF` (branch/tag), `CZ_HOME`, `CZ_BIN`, `ZOHO_MCP_URL`. The older flag-only `scripts/install.py` still works.
Or just open this repo in a harness: root `AGENTS.md` / `GEMINI.md` point at `skills/`, and generated copies are
committed in `.claude/skills`, `.agent/skills`, `.cursor/rules`. MCP details: `skills/zoho-projects-core/references/mcp-setup.md`.

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
