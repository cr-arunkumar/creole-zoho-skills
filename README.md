# zoho-skills

Zoho Projects automation for AI coding agents: **org rule packs** (title, description and comment standards, time
logging, scoring) plus a **gated MCP proxy** in front of Zoho, installed into Claude Code, Cursor, Antigravity / Gemini
CLI and Codex with one guided command. Creole Studios' rules are bundled (public) as the first pack.

## Install
```bash
npx zoho-skills@latest
# or, without Node:
curl -fsSL https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh | sh
```
Both use [uv](https://docs.astral.sh/uv/) to manage Python (the installer offers to fetch it; the npm shim asks first).
Pin a release for production: `ZOHO_SKILLS_REF=v0.2.0 sh install.sh`. The old `creole-zoho` command still works as an alias.

## What the wizard does
1. **Harnesses**: Claude Code, Cursor, Antigravity / Gemini, Codex (detected ones pre-ticked).
2. **Scope**: global (`$HOME`) or one project folder.
3. **Org packs**: which rule packs to enable (core skill is always included).
4. **Region**: Zoho data centre, India (`mcp.zoho.in`) by default; then paste your MCP URL from the Zoho MCP console
   (hidden input, never echoed).
5. **ONE MCP entry per harness**, launching `zoho-skills mcp`. Existing harness config is merged and backed up.
6. **Doctor**: verifies everything and reports what to fix.

## Architecture
```
 Claude Code ─┐
 Cursor ──────┤  one entry each:      ┌──────────────────────────────┐        ┌──────────────┐
 Gemini/AG ───┼─ `zoho-skills mcp` ──▶│ zoho-skills MCP (stdio)      │──HTTPS▶│ Zoho Projects │
 Codex ───────┘                       │  zs_* tools: org rules, lint │        │ MCP server    │
                                      │  write gate (preview→token)  │        └──────────────┘
                                      └──────────────┬───────────────┘
                                   ~/.zoho-skills/config.json (0600: MCP URL)
```
Org rules, lint and Zoho tools all arrive through that single entry (`zs_*` tools plus the proxied Zoho tools).
Native tools: `zs_org_rules`, `zs_lint_task`, `zs_build_title`, `zs_draft_task`, `zs_last_context`,
`zs_save_context`, `zs_status` (is Zoho connected? which gated tools exist) and `zs_add_comment` (gated task comment,
linted against the org's comment rules). **Only the `zs_*` tools appear when the Zoho connection is down** — call
`zs_status`, then `zoho-skills doctor` / `zoho-skills connect`.

## The write gate (what it does and does not do)
Zoho tools that create or update data are not forwarded straight through. The agent first requests a preview; the
server returns a **token bound to that exact call** (tool + arguments). The write only executes with that token:
**single-use, expires after 5 minutes**, rejected if any argument changed. `ZOHO_SKILLS_READONLY=1` blocks all writes.

Be clear about the limit: the gate **cannot prove a human read the preview**. A model can still obtain and use a
token in one turn. The safety model is layered: the gate (no unreviewed, altered or replayed writes), your harness's
own tool-approval prompt (keep it on for the write tools), and the skill instructions telling the model to show the
preview and wait for your confirmation. Treat the gate as a guard rail, not an authorisation system.

## Signing in to Zoho
The MCP URL alone is not a credential: Zoho's endpoint answers `401` + an OAuth challenge. After `connect`, run
`zoho-skills login` once; it opens your browser, you approve the listed permissions, and the proxy stores and refreshes
the tokens. You choose what zoho-skills may touch: the services your MCP server offers (the list comes from the server,
so e.g. Mail appears only if you added it in the Zoho MCP console) and an access level — **read only**,
**read + work items** (default: create/update tasks, time logs, bugs; no deletes) or **everything**. The Zoho MCP
console's own tool selection still caps what can ever run. If Zoho tools are missing, `zs_status` / `zoho-skills doctor` say `sign-in required` and the fix.

## Where secrets live
In `~/.zoho-skills/` (mode 0600): `config.json` (the Zoho MCP URL, which may embed a key) and `oauth.json` (OAuth tokens, bound to that URL). Harness configs contain
just the `zoho-skills mcp` launch command. Output masks the URL. Zoho auth/OAuth is handled by Zoho; nothing in this repo.

## Commands
| Command | Purpose |
|---------|---------|
| `zoho-skills` / `onboard` | Guided wizard (default) |
| `install` | Skills only, no MCP; non-interactive: `--yes --harness claude,cursor --global\|--project DIR [--dry-run]` |
| `connect` | Only (re)set the Zoho MCP URL (stored in `~/.zoho-skills`); `--region in\|com\|eu\|com.au\|jp`, `--no-verify` |
| `login` | Sign in to Zoho (OAuth, once). Interactive: pick services (Projects, WorkDrive, …) and an access level (read / read + work items / everything / custom). Flags: `--services zohoprojects,workdrive`, `--level read\|standard\|full`, `--scopes a,b`, `--no-browser`, `-y` |
| `logout` | Forget the stored Zoho URL and sign-in tokens (harness entries and skills stay) |
| `disconnect` | Remove the `zoho-skills` MCP entry from harnesses, keep skills; `--logout` also forgets the URL |
| `mcp` | Run the stdio MCP server (what harnesses launch) |
| `org add\|list\|update\|remove` | Manage org packs |
| `doctor` | Check harnesses, skills, MCP entry, config permissions |
| `lint` | Offline task lint + estimated score from the org's rules |
| `update` | Upgrade the tool, refresh org packs and re-copy installed skills (`--skills-only` skips the upgrade) |
| `uninstall` | Remove entries and installed skills (`--purge` also deletes `~/.zoho-skills`) |

Env: `ZOHO_SKILLS_REF`, `ZOHO_SKILLS_READONLY`, `ZOHO_SKILLS_URL` (overrides the stored URL), `ZOHO_SKILLS_HOME`.

## Add an org pack
```bash
zoho-skills org add <dir | git-url | owner/repo>
```
A pack is a folder with `pack.json` and `skills/<name>/SKILL.md` (see `packs/creole-studios/pack.json`):
`slug`, `display_name`, `version`, `org_names` (matched against the portal's `org_name`), `skills`, `lint`
(optional script), `final_status`, `resources` (files served by `zs_org_rules`). Start from `templates/org-skill/`
and `skills/zoho-projects-core/references/org-skill-spec.md`.
**Trust:** a pack's lint script runs locally with your permissions. Add packs only from sources you trust.

## Uninstall
`zoho-skills uninstall [--purge]`, then `uv tool uninstall zoho-skills`. Delete `~/.zoho-skills` to remove config and state.

## Develop
```bash
uv venv && uv pip install -e . pytest fastapi httpx
python3 -m pytest -q tests
python3 scripts/build_adapters.py      # regenerate .claude/.agent/.cursor copies (CI runs --check)
```
`skills/` (core) and `packs/*/skills/` are the source of truth. The estimated lint score is a heuristic from the
Creole guide's reference examples, not the real evaluation engine. Optional local API: `api/` (FastAPI + SQLite).
Version lives in `package.json`, `pyproject.toml` and `.claude-plugin/plugin.json` (tests and the release guard keep them equal).
