# Connecting the Zoho Projects MCP server

The skill needs a Zoho Projects MCP server that exposes `get_portals`, `get_projects_list`,
`get_tasks_by_project`, `get_task_details`, `create_a_task`, `update_a_task`
(plus field-option, comment and timelog tools when your server version provides them).

No secrets live in this repo. Authenticate through your harness's MCP / OAuth flow.

| Harness | Where to add the MCP server |
|---------|-----------------------------|
| Claude Code | `claude mcp add --transport http zoho-projects <your Zoho MCP URL>` then `/mcp` to authenticate |
| Claude.ai / Desktop | Settings → Connectors → add the Zoho Projects connector |
| Cursor | `~/.cursor/mcp.json` → `{"mcpServers": {"zoho-projects": {"url": "<your Zoho MCP URL>"}}}` |
| Antigravity / Gemini CLI | `~/.gemini/settings.json` → `mcpServers.zoho-projects.httpUrl = "<your Zoho MCP URL>"` |
| Codex / others | `~/.codex/config.toml` `[mcp_servers.zoho-projects]` with the server URL |

Get the MCP URL from your Zoho Projects admin (Zoho MCP / Developer console). Zoho's India data centre is
used by this portal (`projects.zoho.in`), so use the matching `.in` endpoints.

## Verify read access (safe)
Ask your agent: "list my Zoho portals, then the latest 5 tasks in Research & Training 2025". It should call
`get_portals` and `get_tasks_by_project` only.

## Optional: local helper API (FastAPI + SQLite)
`pip install -r api/requirements.txt && uvicorn api.app:app --port 8787` serves `/lint`, `/context/last`, `/drafts`
for harnesses that can call HTTP but not run scripts. It stores drafts in a local SQLite file
(`$ZOHO_SKILL_DB`, default `~/.creole-zoho-skills/state.db`) and never calls Zoho.
