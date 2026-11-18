# zoho-skills

Zoho Projects automation for AI coding agents: **org rule packs** (title, description and comment standards, time
logging, scoring) plus a **gated MCP proxy** in front of Zoho, installed into Claude Code, Cursor, Antigravity / Gemini
CLI and Codex with one guided command. Creole Studios' rules are bundled (public) as the first pack.

[![npm](https://img.shields.io/npm/v/zoho-skills?logo=npm)](https://www.npmjs.com/package/zoho-skills)
[![CI](https://github.com/cr-arunkumar/creole-zoho-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/cr-arunkumar/creole-zoho-skills/actions/workflows/ci.yml)

## Links
| | |
|---|---|
| npm package | <https://www.npmjs.com/package/zoho-skills> — `npx zoho-skills@latest` |
| Source / issues / releases | <https://github.com/cr-arunkumar/creole-zoho-skills> · [issues](https://github.com/cr-arunkumar/creole-zoho-skills/issues) · [releases](https://github.com/cr-arunkumar/creole-zoho-skills/releases) |
| One-line installer | <https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh> |
| Zoho MCP console (create your MCP URL) | India <https://mcp.zoho.in/> · US <https://mcp.zoho.com/> · EU <https://mcp.zoho.eu/> · AU <https://mcp.zoho.com.au/> · JP <https://mcp.zoho.jp/> |

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
The MCP URL alone is not a credential: Zoho's endpoint answers `401` + an OAuth challenge. Onboarding (and `connect`)
asks **which Zoho services** and **what access level** to grant, then runs the sign-in; `zoho-skills login` repeats it
any time. What happens:

1. You pick services (the list comes from your MCP server, so e.g. Mail appears only if you added it in the Zoho MCP
   console) and a level: **read only**, **read + work items** (default: create/update tasks, time logs, bugs; no
   deletes) or **everything**, or custom. The Zoho MCP console's own tool selection still caps what can ever run.
2. The CLI opens Zoho's consent page in your browser and **waits** (up to 5 minutes, Ctrl+C cancels).
3. After you approve, Zoho redirects the browser to a one-shot listener on `127.0.0.1` in this terminal session. The
   page says "Signed in. You can close this tab", and the CLI **continues on its own**: "Approved in Zoho — collecting
   your access token…" → token exchange → a read-only `tools/list` check → "signed in".
4. **No localhost access** (SSH session, container, remote desktop)? While the CLI waits you can instead paste the
   final page's full address (`http://127.0.0.1:PORT/callback?code=…&state=…`) into the terminal and press Enter.
   `--no-browser` prints the consent URL instead of opening it.
5. **State it updates:** `~/.zoho-skills/oauth.json` (tokens, owner-only, bound to your MCP URL) and a
   `signin` entry in `~/.zoho-skills/config.json` (time + permissions granted, no secrets). Harness configs don't change:
   the running `zoho-skills mcp` proxy reads the token and refreshes it itself. `zoho-skills doctor` shows the status;
   `zoho-skills logout` removes the tokens and the URL. Restart your harness once after the first sign-in.

If Zoho tools are missing, `zs_status` / `zoho-skills doctor` say `sign-in required` and the fix.

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

Env: `ZOHO_SKILLS_REF` (installer: git ref), `ZOHO_SKILLS_READONLY=1` (block all writes), `ZOHO_SKILLS_URL` (overrides the
stored URL), `ZOHO_SKILLS_HOME` (config/token directory, default `~/.zoho-skills`), `ZOHO_SKILLS_ORG` (default org pack).

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

## Install paths (and which ones need no approval)
Every release tag builds a wheel in CI and attaches it to the [GitHub release](https://github.com/cr-arunkumar/creole-zoho-skills/releases),
fully automatic. These paths use it, so they work the moment CI finishes and never wait for npm:
```bash
curl -fsSL https://raw.githubusercontent.com/cr-arunkumar/creole-zoho-skills/main/install.sh | sh     # latest release
zoho-skills update            # moves to the latest GitHub release;  zoho-skills update --check  only reports
npx github:cr-arunkumar/creole-zoho-skills#v0.2.6            # pinned tag straight from GitHub
```
The npm package (`npx zoho-skills@latest`) is a mirror: npm may hold each release for a maintainer's approval (below).

## Release (maintainers)
`scripts/release.sh X.Y.Z` bumps the three version files, runs the tests, commits, tags and pushes. The tag starts the
`publish` workflow: tests, build the wheel, **GitHub release with the wheel** (+ install smoke test), npm publish with
provenance, then a wait-and-smoke-test of `npx zoho-skills@X.Y.Z`. Nothing in that path needs you. Only the npm mirror
can wait for npm's approval gate (see below); installs from GitHub never do.

### Making npm releases fully automatic (no approval click)
npm's staged publishing holds `npm publish` from a token until a maintainer approves it with 2FA. A trusted publisher
(GitHub Actions identity, no token stored anywhere) can be allowed to publish directly. One-time setup, by the package
owner (needs your npm 2FA; npm >= 11.15, so use `npx`):
```bash
npx --yes npm@latest login
npx --yes npm@latest trust github zoho-skills --repo cr-arunkumar/creole-zoho-skills --file publish.yml --allow-publish
gh variable set NPM_TRUSTED_PUBLISHING --body true -R cr-arunkumar/creole-zoho-skills
```
After that the `publish` workflow uses OIDC instead of `NPM_TOKEN`, and tag → installable needs no manual step
(plus npm's few minutes of registry lag). To go back to the token path, delete the variable.

## Develop
```bash
uv venv && uv pip install -e . pytest fastapi httpx
python3 -m pytest -q tests
python3 scripts/build_adapters.py      # regenerate .claude/.agent/.cursor copies (CI runs --check)
```
`skills/` (core) and `packs/*/skills/` are the source of truth. The estimated lint score is a heuristic from the
Creole guide's reference examples, not the real evaluation engine. Optional local API: `api/` (FastAPI + SQLite).
Version lives in `package.json`, `pyproject.toml` and `.claude-plugin/plugin.json` (tests and the release guard keep them equal).
