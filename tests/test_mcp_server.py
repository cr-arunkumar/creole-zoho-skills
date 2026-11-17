import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]
FAKE = REPO / "tests" / "fake_upstream.py"


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 60))


def server_params(tmp_path, readonly=False):
    env = {**os.environ, "HOME": str(tmp_path), "ZOHO_SKILLS_HOME": str(tmp_path / "zs"),
           "CALLS_FILE": str(tmp_path / "calls.jsonl"), "PYTHONPATH": str(REPO / "src"),
           "ZOHO_SKILLS_UPSTREAM_CMD": json.dumps([sys.executable, str(FAKE)]),
           "ZOHO_SKILLS_READONLY": "1" if readonly else "0"}
    env.pop("ZOHO_SKILLS_URL", None)
    return StdioServerParameters(command=sys.executable, args=["-m", "zoho_skills", "mcp"], env=env)


def calls(tmp_path):
    f = tmp_path / "calls.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def text(res):
    return res.content[0].text


def test_tools_listing_native_plus_gated_upstream(tmp_path):
    async def go():
        async with stdio_client(server_params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name: t for t in (await s.list_tools()).tools}
                assert {"zs_org_rules", "zs_lint_task", "get_portals", "create_a_task"} <= set(tools)
                assert "confirm_token" in tools["create_a_task"].inputSchema["properties"]
                assert "confirm_token" not in tools["get_portals"].inputSchema.get("properties", {})
                assert {p.name for p in (await s.list_prompts()).prompts} == {"create_task", "finish_task", "audit_task"}
                assert (await s.list_resources()).resources
    run(go())


def test_read_passes_through_and_write_is_gated(tmp_path):
    async def go():
        async with stdio_client(server_params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                assert "Creole Studios" in text(await s.call_tool("get_portals", {}))
                args = {"name": "Implement RLS policies on Zoho schema [4.0 hrs]", "description": "short"}

                prev = json.loads(text(await s.call_tool("create_a_task", args, )))
                assert "PREVIEW_ONLY" in prev and prev["org_pack"] is None or prev["org_pack"]
                token = prev["confirm_token"]
                assert [c["tool"] for c in calls(tmp_path)] == ["get_portals"]  # preview forwarded nothing

                bad = await s.call_tool("create_a_task", {**args, "description": "changed", "confirm_token": token})
                assert bad.isError and "does not match" in text(bad)

                ok = await s.call_tool("create_a_task", {**args, "confirm_token": token})
                assert not ok.isError and "created 42" in text(ok)
                done = [c for c in calls(tmp_path) if c["tool"] == "create_a_task"]
                assert len(done) == 1 and "confirm_token" not in done[0]["args"]

                replay = await s.call_tool("create_a_task", {**args, "confirm_token": token})
                assert replay.isError and "already used" in text(replay)
                assert len([c for c in calls(tmp_path) if c["tool"] == "create_a_task"]) == 1
    run(go())


def test_native_tools_use_org_pack(tmp_path):
    async def go():
        async with stdio_client(server_params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                rules = json.loads(text(await s.call_tool("zs_org_rules", {"org_name": "Creole Studios"})))
                assert rules["final_status"] == "In QA Review"
                lint = json.loads(text(await s.call_tool("zs_lint_task", {"org": "Creole Studios", "title": "Fix",
                                                                           "description": "x", "status": "In Progress"})))
                assert lint["errors"]
                t = json.loads(text(await s.call_tool("zs_build_title", {"description": "Add retry to sync job. More",
                                                                          "planned_minutes": 90})))
                assert t["title"] == "Add retry to sync job [1.5 hrs]"
                draft = json.loads(text(await s.call_tool("zs_draft_task", {
                    "tool": "create_a_task", "org": "Creole Studios",
                    "arguments": {"name": "Fix", "description": "x"}})))
                assert draft["lint"]["errors"] and draft["confirm_token"]
    run(go())


def test_readonly_hides_and_blocks_writes(tmp_path):
    async def go():
        async with stdio_client(server_params(tmp_path, readonly=True)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert "get_portals" in names and "create_a_task" not in names
                res = await s.call_tool("create_a_task", {"name": "x"})
                assert res.isError and "read-only" in text(res)
                assert calls(tmp_path) == [] or all(c["tool"] != "create_a_task" for c in calls(tmp_path))
    run(go())


def test_add_comment_is_gated_and_maps_to_upstream_schema(tmp_path):
    async def go():
        async with stdio_client(server_params(tmp_path)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                st = json.loads(text(await s.call_tool("zs_status", {})))
                assert st["zoho_connected"] and st["comment_tools"] == ["create_task_comment"]
                args = {"task_id": "T1", "comment": "Implemented retry in `sync.py` and verified with 12 tests.",
                        "org": "Creole Studios"}
                prev = json.loads(text(await s.call_tool("zs_add_comment", args)))
                assert prev["will_call"] == {"tool": "create_task_comment",
                                             "arguments": {"task_id": "T1", "content": args["comment"]}}
                assert prev["confirm_token"] and prev["lint"] is not None
                assert [c["tool"] for c in calls(tmp_path)] == []  # preview forwarded nothing

                bad = await s.call_tool("zs_add_comment", {**args, "comment": "edited", "confirm_token": prev["confirm_token"]})
                assert bad.isError and "does not match" in text(bad)
                ok = await s.call_tool("zs_add_comment", {**args, "confirm_token": prev["confirm_token"]})
                assert not ok.isError and "commented" in text(ok)
                done = calls(tmp_path)
                assert len(done) == 1 and done[0]["args"]["content"] == args["comment"]
                again = await s.call_tool("zs_add_comment", {**args, "confirm_token": prev["confirm_token"]})
                assert again.isError and len(calls(tmp_path)) == 1
    run(go())


def test_add_comment_blocked_in_readonly_and_without_upstream(tmp_path):
    async def go():
        async with stdio_client(server_params(tmp_path, readonly=True)) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("zs_add_comment", {"task_id": "T1", "comment": "x"})
                assert res.isError and "read-only" in text(res)
        p = server_params(tmp_path)
        p.env.pop("ZOHO_SKILLS_UPSTREAM_CMD")
        async with stdio_client(p) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                st = json.loads(text(await s.call_tool("zs_status", {})))
                assert not st["zoho_connected"] and "zoho-skills connect" in st["fix"]
                res = await s.call_tool("zs_add_comment", {"task_id": "T1", "comment": "x"})
                assert res.isError and "Nothing was written" in text(res)
    run(go())
