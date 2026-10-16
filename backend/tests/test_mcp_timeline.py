"""Behind/ahead with diagnosis + forecast over MCP, on a goal that has two weeks of history."""

import json
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


async def test_diagnosis_forecast_and_alerts():
    db = Path(tempfile.mkdtemp()) / "timeline.db"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "OWNER_EMAIL": "owner@example.com"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        today = date.fromisoformat((await call(session, "get_overview"))["today"])
        start = today - timedelta(days=14)
        gid = (await call(session, "create_goal", title="AI engineer"))["goal_id"]
        await call(session, "confirm_goal_definition", goal_id=gid, statement="AI engineer", success_criteria=["x"])
        rm = await call(session, "set_roadmap", goal_id=gid, roadmap_draft={"summary": "", "phases": [
            {"title": "P", "items": [{"title": "RAG", "est_hours": 10}, {"title": "Evals", "est_hours": 20}]}]})
        rag = rm["phases"][0]["items"][0]["id"]
        # 1h every day, target in ~5 weeks: the plan just fits
        await call(session, "confirm_commitment", goal_id=gid, target_date=str(start + timedelta(days=32)),
                   routine=[{"days": ALL_DAYS, "start": "07:00", "end": "08:00", "activity": "Study"}])

        # Pretend the goal and its plan (1h/day) were agreed two weeks ago; the user then managed 4 of the 14 days
        baseline = {"start": str(start), "done_at_start": 0,
                    "points": [[str(start + timedelta(days=n)), float(n + 1)] for n in range(30)]}
        con = sqlite3.connect(db)
        con.execute("update goals set created_at = ?, baseline = ?", (f"{start} 00:00:00", json.dumps(baseline)))
        con.commit()
        con.close()

        for n in (13, 9, 5, 1):  # 4 logged days, 1h each
            d = today - timedelta(days=n)
            res = await call(session, "save_day_review", day=str(d), review={"activities": [
                {"description": "RAG", "minutes": 60, "kind": "learn", "links": [{"goal_id": gid, "roadmap_item_id": rag}]}],
                "item_progress": [{"roadmap_item_id": rag, "hours": 1}]})
        alerts = res["timeline_alerts"]
        assert alerts and "behind plan" in alerts[0]["message"] and "routine not followed" in alerts[0]["message"]

        tl = (await call(session, "get_timeline"))["goals"][0]
        dx = tl["diagnosis"]
        assert tl["state"] == "behind" and tl["behind_days"] >= 9
        assert dx["likely_cause"] == "routine_not_followed"
        assert dx["missed_working_days_last_14_days"] >= 9
        assert dx["planned_hours_per_week"] == 7 and dx["actual_hours_per_week"] == 2
        assert dx["forecast_misses_target"] and dx["forecast_finish_at_actual_pace"] > dx["target_date"]

        # Items running over their estimate change the diagnosis
        await call(session, "update_roadmap_item", item_id=rag, est_hours=3)
        dx = (await call(session, "get_timeline"))["goals"][0]["diagnosis"]
        assert dx["likely_cause"] == "estimates_too_low" and dx["items_over_estimate"][0]["id"] == rag
