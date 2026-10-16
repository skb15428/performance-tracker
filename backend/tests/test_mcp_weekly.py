"""Weekly review over MCP on two weeks of history: comparison, commitment %, patterns, focus loop, due nudge."""

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.test_mcp_server import call

BACKEND = Path(__file__).resolve().parents[1]
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def test_weekly_review_loop():
    db = Path(tempfile.mkdtemp()) / "weekly.db"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "OWNER_EMAIL": "owner@example.com"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        today = date.fromisoformat((await call(session, "get_overview"))["today"])
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        first_day = last_monday - timedelta(days=7)

        gid = (await call(session, "create_goal", title="AI engineer"))["goal_id"]
        await call(session, "confirm_goal_definition", goal_id=gid, statement="AI engineer", success_criteria=["x"])
        rm = await call(session, "set_roadmap", goal_id=gid, roadmap_draft={"summary": "", "phases": [
            {"title": "P", "items": [{"title": "RAG", "est_hours": 200}]}]})
        item = rm["phases"][0]["items"][0]["id"]
        await call(session, "confirm_commitment", goal_id=gid, target_date=str(today + timedelta(days=200)), routine=[
            {"days": ALL_DAYS, "start": "07:00", "end": "08:00", "activity": "Study", "focus": "learn"},
            {"days": ALL_DAYS, "start": "19:00", "end": "20:00", "activity": "Build", "focus": "any"}])
        con = sqlite3.connect(db)
        con.execute("update goals set created_at = ?", (f"{first_day - timedelta(days=1)} 00:00:00",))
        con.commit()
        con.close()

        # Two weeks: mornings always done, evenings always skipped; better week last week; energy varies
        day = first_day - timedelta(days=1)
        plan_blocks = [{"time_block": "07:00-08:00", "title": "Study RAG", "minutes": 60, "roadmap_item_id": item},
                       {"time_block": "19:00-20:00", "title": "Build", "minutes": 60, "roadmap_item_id": item}]
        await call(session, "save_day_review", day=str(day), review={"activities": [], "tomorrow": plan_blocks})
        while day < today - timedelta(days=1):
            day += timedelta(days=1)
            plan = (await call(session, "get_day_context", day=str(day)))["plan_for_this_day"]
            status = [{"plan_item_id": p["plan_item_id"], "status": "done" if p["time_block"].startswith("07") else "skipped"}
                      for p in plan]
            minutes = 60 if day < last_monday else 60 + 30  # a bit more last week
            await call(session, "save_day_review", day=str(day), plan_status=status, energy=2 if day.weekday() == 0 else 4,
                       review={"activities": [{"description": "RAG", "minutes": minutes, "kind": "learn",
                                               "links": [{"goal_id": gid, "roadmap_item_id": item}]}],
                               "goal_impacts": [{"goal_id": gid, "impact": 5}], "tomorrow": plan_blocks})

        overview = await call(session, "get_overview")
        assert overview["weekly_review_due_for_week"] == str(last_monday) and overview["weekly_focus"] == []

        stats = await call(session, "get_weekly_stats", week_start=str(last_monday))
        g = stats["goals"][0]
        assert g["committed_hours"] == 14 and g["hours"] == 10.5 and g["pct_of_commitment"] == 0.75
        assert stats["previous_week"]["week_start"] == str(first_day) and len(stats["last_4_weeks"]) == 4
        assert stats["previous_week"]["goal_hours"] < stats["last_4_weeks"][-1]["goal_hours"]
        pat = stats["patterns_last_4_weeks"]
        assert pat["plan_done_by_time_of_day"] == {"morning": 1.0, "evening": 0.0}
        assert set(pat["avg_score_by_energy"]) == {"low (1-2)", "high (4-5)"}
        assert stats["last_week_focus"] == []

        saved = await call(session, "save_weekly_review", week_start=str(last_monday), summary="Mornings work",
                           wins=["Every morning block done"], gaps=["No evening block done"],
                           recommendations=["Move build block to Saturday morning"],
                           focus=["Build block before work, not after", "Phone away by 22:00"])
        assert len(saved["focus"]) == 2
        assert (await call(session, "get_overview"))["weekly_focus"] == ["Build block before work, not after",
                                                                       "Phone away by 22:00"]
        assert (await call(session, "get_overview"))["weekly_review_due_for_week"] is None
        assert (await call(session, "get_day_context"))["weekly_focus"][1] == "Phone away by 22:00"

        # Next weekly review follows up on those focus points
        this_week = await call(session, "get_weekly_stats", week_start=str(this_monday))
        assert [f["text"] for f in this_week["last_week_focus"]][0].startswith("Build block")
        await call(session, "save_weekly_review", week_start=str(this_monday), summary="s", wins=[], gaps=[],
                   recommendations=[], last_week_focus_kept=[True, False])
        followed = (await call(session, "get_weekly_stats", week_start=str(this_monday)))["last_week_focus"]
        assert [f["kept"] for f in followed] == [True, False]

        dash = await call(session, "get_dashboard", weeks=4)
        assert len(dash["weeks"]) == 4 and dash["goals"][0]["title"] == "AI engineer"
        last = next(w for w in dash["goals"][0]["weekly_hours"] if w["week"] == str(last_monday))
        assert last == {"week": str(last_monday), "planned_hours": 14.0, "actual_hours": 10.5}
        assert dash["weekly_focus"] and any(d["score"] is not None for d in dash["daily_scores"])
