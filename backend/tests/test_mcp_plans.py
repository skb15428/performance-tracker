"""Tomorrow's / today's plan over MCP: plan on demand, edit it, and routine clashes between goals."""

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.test_mcp_server import call

BACKEND = Path(__file__).resolve().parents[1]
WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def make_goal(session, title, routine, items):
    gid = (await call(session, "create_goal", title=title))["goal_id"]
    await call(session, "confirm_goal_definition", goal_id=gid, statement=title, success_criteria=["done"])
    await call(session, "set_roadmap", goal_id=gid, roadmap_draft={"summary": "", "phases": [{"title": "P1", "items": items}]})
    return gid, await call(session, "confirm_commitment", goal_id=gid, target_date="2027-12-31", routine=routine)


async def test_plan_day_edit_plan_and_clashes():
    db = Path(tempfile.mkdtemp()) / "plans.db"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "OWNER_EMAIL": "owner@example.com"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        today = date.fromisoformat((await call(session, "get_overview"))["today"])
        wd = WEEK[today.weekday()]
        gid, _ = await make_goal(session, "AI engineer", [
            {"days": [wd], "start": "07:00", "end": "08:30", "activity": "Study", "focus": "learn"},
            {"days": [wd], "start": "19:00", "end": "20:00", "activity": "Build", "focus": "build"}],
            [{"type": "topic", "title": "RAG", "est_hours": 10}, {"type": "task", "title": "RAG app", "est_hours": 10}])

        # No review last night -> the overview flags it, and plan_day builds today's plan from the routine
        assert (await call(session, "get_overview"))["today_plan_missing"]
        plan = await call(session, "plan_day")
        assert plan["created_now"] and [(p["time_block"], p["title"].split(": ")[-1]) for p in plan["plan"]] == [
            ("07:00-08:30", "RAG"), ("19:00-20:00", "RAG app")]  # learn block -> topic, build block -> task
        again = await call(session, "plan_day")
        assert not again["created_now"] and len(again["plan"]) == 2  # doesn't duplicate

        # Structured block: short title + why, timed steps, resources, done_when
        details = {"why": "Attention is the core of every LLM", "done_when": "Output matches PyTorch on 4 tokens",
                   "steps": [{"text": "Read The Illustrated Transformer", "minutes": 45},
                             {"text": "Implement attention + causal mask in NumPy", "minutes": 45}],
                   "resources": [{"title": "The Illustrated Transformer",
                                  "url": "https://jalammar.github.io/illustrated-transformer/"}]}
        structured = await call(session, "edit_plan", update=[
            {"plan_item_id": plan["plan"][0]["plan_item_id"], "title": "Attention from scratch", "details": details}])
        assert structured["plan"][0]["details"]["steps"][1]["minutes"] == 45
        assert structured["plan"][0]["details"]["resources"][0]["url"].startswith("https://jalammar")
        assert (await call(session, "get_overview"))["today_plan"][0]["details"]["done_when"].startswith("Output")

        # The day changes: rename to a concrete task, shorten the evening block, add a block, then drop one
        first, second = plan["plan"]
        edited = await call(session, "edit_plan", update=[
            {"plan_item_id": first["plan_item_id"], "title": "Hybrid retriever - done when top-5 works on 10 questions"},
            {"plan_item_id": second["plan_item_id"], "minutes": 30, "time_block": "19:30-20:00"}],
            add=[{"time_block": "21:00-21:30", "title": "Read LangGraph docs", "minutes": 30, "goal_id": gid}])
        assert edited["total_minutes"] == 90 + 30 + 30
        assert edited["plan"][0]["title"].startswith("Hybrid retriever")
        added = next(p for p in edited["plan"] if p["title"] == "Read LangGraph docs")
        assert len((await call(session, "edit_plan", remove=[added["plan_item_id"]]))["plan"]) == 2

        # A day with nothing in the routine is a rest day: no plan
        rest_day = next(today + timedelta(days=n) for n in range(1, 7))
        assert (await call(session, "plan_day", day=str(rest_day)))["rest_day"]

        # A second goal whose routine overlaps the first one gets a warning
        _, second_goal = await make_goal(session, "Micro-SaaS", [
            {"days": [wd, WEEK[(today.weekday() + 1) % 7]], "start": "08:00", "end": "09:00", "activity": "Build"}],
            [{"type": "task", "title": "Interviews", "est_hours": 5}])
        assert any("overlaps 'AI engineer' 07:00-08:30" in w for w in second_goal["warnings"])
