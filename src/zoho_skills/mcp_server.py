"""`zoho-skills mcp`: one stdio MCP server that (1) serves org rules/tools and (2) proxies the Zoho Projects MCP,
refusing writes until the exact previewed call is confirmed with a token. Never prints to stdout (that's the protocol)."""
from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from pydantic import AnyUrl

from . import config, gate as gate_mod, packs, store, upstream

NATIVE = "zs_"
INSTRUCTIONS = (
    "Zoho Projects helper. Org rules: call zs_org_rules first. Writes to Zoho (create_/update_ tools) are gated: "
    "a call without confirm_token returns a PREVIEW and a token; show the preview to the user, and only after their "
    "explicit approval repeat the identical call with confirm_token. Never claim something was written unless the "
    "tool result says so. If Zoho tools (get_/create_/update_ …) are missing from the tool list, call zs_status: the "
    "Zoho connection is down. To post a task comment use zs_add_comment (gated like any write)."
)


def _schema(props: dict, required: Optional[list] = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


S = {"type": "string"}
N = {"type": "number"}
TASK_PROPS = {"title": S, "description": S, "comment": S, "planned_minutes": N, "logged_minutes": N, "status": S,
              "final": {"type": "boolean"}, "org": S}
NATIVE_TOOLS = [
    types.Tool(name="zs_org_rules", description="Return the org's Zoho rules (title/description/comment standards, "
               "status, scoring). Pass org_name from get_portals if known.",
               inputSchema=_schema({"org_name": S}), annotations=types.ToolAnnotations(readOnlyHint=True)),
    types.Tool(name="zs_lint_task", description="Offline lint + estimated score for a drafted task using the org "
               "pack. Never calls Zoho.", inputSchema=_schema(TASK_PROPS), annotations=types.ToolAnnotations(readOnlyHint=True)),
    types.Tool(name="zs_build_title", description="Build a title '<Verb> <object> [X.X hrs]' from a description "
               "(fallback when the title is empty).", inputSchema=_schema({"description": S, "planned_minutes": N},
               ["description"]), annotations=types.ToolAnnotations(readOnlyHint=True)),
    types.Tool(name="zs_draft_task", description="Preview a Zoho write without executing it: returns the payload, org "
               "lint and a confirm_token to pass to the real tool after the user approves.",
               inputSchema=_schema({"tool": S, "arguments": {"type": "object"}, "org": S}, ["tool", "arguments"]),
               annotations=types.ToolAnnotations(readOnlyHint=True)),
    types.Tool(name="zs_status", description="Connection status: is the Zoho MCP connected, read-only mode, and which "
               "gated write/comment tools the upstream offers. Call when Zoho tools are missing.",
               inputSchema=_schema({}), annotations=types.ToolAnnotations(readOnlyHint=True)),
    types.Tool(name="zs_add_comment", description="Add a comment to a Zoho task. Gated: the first call returns a "
               "PREVIEW (resolved Zoho call + org lint of the comment) and a confirm_token; repeat the identical call "
               "with confirm_token after the user approves. Needs the Zoho connection (see zs_status).",
               inputSchema=_schema({"task_id": S, "comment": S, "project_id": S, "org": S,
                                    "tool": {"type": "string", "description": "Zoho tool to use if auto-detection "
                                             "is ambiguous (see zs_status comment_tools)"},
                                    "extra": {"type": "object", "description": "Extra arguments passed to the Zoho tool"},
                                    gate_mod.TOKEN_FIELD: {"type": "string"}}, ["task_id", "comment"])),
    types.Tool(name="zs_last_context", description="Last saved Zoho context (org, project, list, parent, owner) to "
               "reuse as defaults.", inputSchema=_schema({"org": S}), annotations=types.ToolAnnotations(readOnlyHint=True)),
    types.Tool(name="zs_save_context", description="Remember the context of a task you just created/updated.",
               inputSchema=_schema({**TASK_PROPS, "project": S, "task_list": S, "parent": S, "owner": S,
                                    "zoho_task_id": S})),
]
PROMPTS = {
    "create_task": ("Draft and (after confirmation) create a Zoho task in the org's format.",
                    "Use zs_org_rules, zs_last_context, then draft the task with zs_build_title/zs_lint_task. Show the "
                    "preview from the gated create tool and wait for my explicit approval before confirming."),
    "finish_task": ("Log a final comment/time and move the task to the org's final status.",
                    "Read the task, draft a substantive technical comment, lint it with zs_lint_task, then update "
                    "status/time through the gated update tool, showing the preview first."),
    "audit_task": ("Audit an existing task against the org rules without changing it.",
                   "Fetch the task (read-only), run zs_lint_task on its fields and report errors, warnings and the "
                   "estimated score. Do not write anything."),
}


COMMENT_ALIASES = {"comment": ("comment", "comments", "content", "comment_content", "text", "body", "message"),
                   "task_id": ("task_id", "taskId", "task"), "project_id": ("project_id", "projectId", "project")}
COMMENT_CREATE = ("create_", "add_", "post_")


def comment_tools(tools: list) -> list:
    """Upstream tools that create a comment (not read/update/delete ones)."""
    return [t for t in tools if "comment" in t.name.lower() and t.name.lower().startswith(COMMENT_CREATE)]


def resolve_comment_call(tools: list, a: dict) -> tuple:
    """Map zs_add_comment arguments onto the upstream comment tool's own schema. Raises ValueError with a reason."""
    by_name = {t.name: t for t in tools}
    if a.get("tool"):
        tool = by_name.get(a["tool"])
        if tool is None or not gate_mod.is_write_tool(tool.name):
            raise ValueError(f"unknown Zoho tool {a['tool']!r} (see zs_status for comment_tools)")
    else:
        found = comment_tools(tools)
        task_scoped = [t for t in found if "task" in t.name.lower()]
        found = task_scoped or found
        if len(found) != 1:
            names = [t.name for t in found]
            raise ValueError("no Zoho comment-creating tool found; pass tool=<name> (see zs_status)" if not found else
                             f"several comment tools match {names}; pass tool=<name>")
        tool = found[0]
    props = (tool.inputSchema or {}).get("properties", {})
    args: dict = {}
    for ours, aliases in COMMENT_ALIASES.items():
        val = a.get(ours)
        if val in (None, ""):
            continue
        key = next((k for k in aliases if k in props), None)
        if key is None:
            if ours == "project_id":
                continue  # optional: some tools infer the project from the task
            raise ValueError(f"{tool.name} has no parameter for {ours}; its parameters are {sorted(props)}")
        args[key] = val
    args.update(a.get("extra") or {})
    missing = [k for k in (tool.inputSchema or {}).get("required", []) if k not in args]
    if missing:
        raise ValueError(f"{tool.name} also requires {missing}; pass them in extra (e.g. project_id)")
    return tool.name, args


def comment_lint(pack: Optional[packs.Pack], comment: str) -> Optional[dict]:
    if not pack:
        return None
    res = packs.lint(pack, _task_from_args({"comment": comment}))
    return {k: [m for m in res[k] if "comment" in m.lower()] for k in ("errors", "warnings", "notes")}


@dataclass
class Ctx:
    session: Any = None
    error: Optional[str] = None


def _text(obj: Any) -> list:
    s = obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str)
    return [types.TextContent(type="text", text=config.redact(s))]


def _task_from_args(args: dict, tool: str = "") -> dict:
    g = lambda *ks: next((args[k] for k in ks if args.get(k) not in (None, "")), None)  # noqa: E731
    final = args.get("final")
    if final is None:
        final = tool.startswith("update") and g("status", "custom_status") is not None
    return {"title": g("title", "name") or "", "description": g("description") or "", "comment": g("comment") or "",
            "planned_minutes": g("planned_minutes"), "logged_minutes": g("logged_minutes"),
            "status": g("status", "custom_status") or "", "final": bool(final)}


def build_title(description: str, planned_minutes: Optional[float] = None) -> str:
    first = " ".join((description or "").replace("\n", " ").split(". ")[0].split()[:10]).rstrip(".:;,")
    first = first[:1].upper() + first[1:] if first else "Update task"
    tag = f" [{planned_minutes / 60:.1f} hrs]" if planned_minutes else ""
    return first + tag


def _pack_for(org: Optional[str], default_org: Optional[str]) -> Optional[packs.Pack]:
    return packs.match(org or default_org)


def make_server(*, url: Optional[str] = None, command: Optional[list] = None, readonly: Optional[bool] = None,
                default_org: Optional[str] = None, gate: Optional[gate_mod.Gate] = None) -> Server:
    gate = gate or gate_mod.Gate()
    ro = config.readonly() if readonly is None else readonly

    @contextlib.asynccontextmanager
    async def lifespan(_server):
        ctx = Ctx()
        if url or command:
            try:
                async with upstream.connect(url, command) as session:
                    ctx.session = session
                    yield ctx
                    return
            except Exception as e:  # keep serving native tools; report on forwarded calls
                ctx.error = config.redact(f"upstream unavailable: {upstream.describe_error(e)}")
                print(ctx.error, file=sys.stderr)
        else:
            ctx.error = "no Zoho MCP URL configured (run: zoho-skills onboard)"
        yield ctx

    server: Server = Server("zoho-skills", instructions=INSTRUCTIONS, lifespan=lifespan)

    def ctx() -> Ctx:
        return server.request_context.lifespan_context

    def preview(tool: str, args: dict, org: Optional[str]) -> dict:
        clean = {k: v for k, v in args.items() if k != gate_mod.TOKEN_FIELD}
        pack = _pack_for(org, default_org)
        out: dict = {"PREVIEW_ONLY": "nothing was written to Zoho", "tool": tool, "arguments": clean}
        if pack and "task" in tool:
            out["org_pack"] = pack.display_name
            out["lint"] = packs.lint(pack, _task_from_args(clean, tool))
            if pack.final_status:
                out["org_final_status"] = pack.final_status
        else:
            out["org_pack"] = pack.display_name if pack else None
        out["confirm_token"] = gate.issue(tool, clean)
        out["next"] = ("Show this preview to the user. Only after their explicit approval, repeat the SAME call with "
                       "confirm_token set. Token is single-use and expires in 5 minutes.")
        return out

    async def upstream_tools() -> list:
        c = ctx()
        if not c.session:
            return []
        tools = (await c.session.list_tools()).tools
        out = []
        for t in tools:
            if gate_mod.is_write_tool(t.name):
                if ro:
                    continue
                schema = json.loads(json.dumps(t.inputSchema or {"type": "object"}))
                schema.setdefault("properties", {})[gate_mod.TOKEN_FIELD] = {
                    "type": "string", "description": "Required to execute: token from the preview of this exact call."}
                # outputSchema dropped: a preview/blocked reply is not the tool's normal output shape
                t = t.model_copy(update={"inputSchema": schema, "outputSchema": None,
                                         "description": (t.description or "") + " [gated: preview first]"})
            out.append(t)
        return out

    @server.list_tools()
    async def _list_tools() -> list:
        return NATIVE_TOOLS + await upstream_tools()

    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict) -> Any:
        args = dict(arguments or {})
        if name == "zs_status":
            return _text(await status())
        if name == "zs_add_comment":
            return await add_comment(args)
        if name.startswith(NATIVE):
            return _text(native(name, args))
        c = ctx()
        if not c.session:
            return types.CallToolResult(content=_text(c.error or "upstream unavailable"), isError=True)
        if gate_mod.is_write_tool(name):
            if ro:
                return types.CallToolResult(content=_text("read-only mode: writes are disabled "
                                                           "(ZOHO_SKILLS_READONLY / config)"), isError=True)
            token = args.get(gate_mod.TOKEN_FIELD)
            if not token:
                return _text(preview(name, args, args.get("org")))
            ok, why = gate.verify(name, args, token)
            if not ok:
                return types.CallToolResult(content=_text(f"BLOCKED: {why}. Nothing was written."), isError=True)
            args.pop(gate_mod.TOKEN_FIELD, None)
        res = await c.session.call_tool(name, args)
        return types.CallToolResult(content=res.content, isError=bool(res.isError),
                                    structuredContent=getattr(res, "structuredContent", None))

    async def status() -> dict:
        c = ctx()
        out: dict = {"zoho_connected": bool(c.session), "url_configured": bool(url or command), "readonly": ro}
        if not c.session:
            out["problem"] = c.error or "upstream unavailable"
            out["fix"] = ("run `zoho-skills doctor`, then `zoho-skills connect` if the URL is missing/expired, "
                          "and restart the harness; only zs_* tools work until Zoho is connected")
            return out
        tools = (await c.session.list_tools()).tools
        out["write_tools_gated"] = [] if ro else sorted(t.name for t in tools if gate_mod.is_write_tool(t.name))
        out["comment_tools"] = [t.name for t in comment_tools(tools)]
        return out

    async def add_comment(a: dict) -> Any:
        def fail(msg: str) -> types.CallToolResult:
            return types.CallToolResult(content=_text(msg), isError=True)

        c = ctx()
        if ro:
            return fail("read-only mode: writes are disabled (ZOHO_SKILLS_READONLY / config)")
        if not c.session:
            return fail(f"{c.error or 'upstream unavailable'}. Nothing was written. Run zs_status for the fix.")
        comment = str(a.get("comment") or "").strip()
        if not comment or not a.get("task_id"):
            return fail("task_id and a non-empty comment are required")
        try:
            tool, fwd = resolve_comment_call((await c.session.list_tools()).tools, a)
        except ValueError as e:
            return fail(f"{e}. Nothing was written.")
        token = a.get(gate_mod.TOKEN_FIELD)
        if not token:
            clean = {k: v for k, v in a.items() if k != gate_mod.TOKEN_FIELD}
            pack = _pack_for(a.get("org"), default_org)
            return _text({"PREVIEW_ONLY": "nothing was written to Zoho", "tool": "zs_add_comment",
                          "will_call": {"tool": tool, "arguments": fwd},
                          "org_pack": pack.display_name if pack else None, "lint": comment_lint(pack, comment),
                          "confirm_token": gate.issue("zs_add_comment", clean),
                          "next": "Show the comment and lint to the user. Only after their explicit approval, repeat "
                                  "the SAME call with confirm_token set. Single-use, expires in 5 minutes."})
        ok, why = gate.verify("zs_add_comment", a, token)
        if not ok:
            return fail(f"BLOCKED: {why}. Nothing was written.")
        res = await c.session.call_tool(tool, fwd)
        return types.CallToolResult(content=res.content, isError=bool(res.isError))

    def native(name: str, a: dict) -> Any:
        if name == "zs_org_rules":
            p = _pack_for(a.get("org_name"), default_org)
            if not p:
                return {"installed_packs": [x.display_name for x in packs.discover()],
                        "message": "No rule pack matched; apply the core skill rules only (preview before write)."}
            return {"pack": p.display_name, "final_status": p.final_status, "rules": packs.rules_text(p)}
        if name == "zs_lint_task":
            p = _pack_for(a.get("org"), default_org)
            return packs.lint(p, _task_from_args(a)) if p else {"error": "no org pack matched; pass org"}
        if name == "zs_build_title":
            return {"title": build_title(a.get("description", ""), a.get("planned_minutes"))}
        if name == "zs_draft_task":
            if not gate_mod.is_write_tool(a["tool"]):
                return {"error": f"{a['tool']} is a read tool; call it directly"}
            return preview(a["tool"], a.get("arguments") or {}, a.get("org"))
        if name == "zs_last_context":
            return store.last_context(a.get("org")) or {"message": "no saved context yet"}
        if name == "zs_save_context":
            return {"saved_id": store.save_context({k: v for k, v in a.items() if k != "final"})}
        raise ValueError(f"unknown tool {name}")

    @server.list_prompts()
    async def _prompts() -> list:
        return [types.Prompt(name=k, description=v[0]) for k, v in PROMPTS.items()]

    @server.get_prompt()
    async def _prompt(name: str, arguments: Optional[dict] = None) -> types.GetPromptResult:
        desc, body = PROMPTS[name]
        return types.GetPromptResult(description=desc, messages=[
            types.PromptMessage(role="user", content=types.TextContent(type="text", text=body))])

    @server.list_resources()
    async def _resources() -> list:
        out = []
        for p in packs.discover():
            for rel in packs.read_resource_files(p):
                out.append(types.Resource(uri=AnyUrl(f"zs://{p.slug}/{rel}"), name=f"{p.display_name}: {rel}",
                                          mimeType="text/markdown"))
        return out

    @server.read_resource()
    async def _read(uri: AnyUrl) -> list:
        slug, _, rel = str(uri).removeprefix("zs://").partition("/")
        for p in packs.discover():
            if p.slug == slug and rel in (docs := packs.read_resource_files(p)):
                return [ReadResourceContents(content=docs[rel], mime_type="text/markdown")]
        raise ValueError(f"unknown resource {uri}")

    return server


async def serve() -> None:
    cmd = os.environ.get("ZOHO_SKILLS_UPSTREAM_CMD")  # test hook: stdio upstream as a JSON list
    cfg = config.load()
    server = make_server(url=config.get_url(), command=json.loads(cmd) if cmd else None,
                         default_org=os.environ.get("ZOHO_SKILLS_ORG") or cfg.get("default_org"))
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


def main() -> int:
    anyio.run(serve)
    return 0
