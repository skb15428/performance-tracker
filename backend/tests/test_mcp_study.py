"""The full study flow through the real MCP server, the way Claude drives it."""

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.test_mcp_server import call

BACKEND = Path(__file__).resolve().parents[1]
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
GRAPHS = {"title": "Graphs", "est_minutes": 60, "concepts": [{"name": "BFS"}, {"name": "DFS"},
                                                               {"name": "A*", "core": False}]}
HEAPS = {"title": "Heaps", "est_minutes": 40, "concepts": [{"name": "Heapify"}]}


def marks(*rows):
    return [{"question": f"Explain {c}", "concept": c, "score": s, "is_follow_up": i > 0} for i, (c, s) in enumerate(rows)]


async def test_study_flow():
    db = Path(tempfile.mkdtemp()) / "study.db"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "OWNER_EMAIL": "owner@example.com"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        today = date.fromisoformat((await call(session, "get_overview"))["today"])
        tomorrow = str(today + timedelta(days=1))
        gid = (await call(session, "create_goal", title="AI engineer"))["goal_id"]
        await call(session, "confirm_goal_definition", goal_id=gid, statement="AI", success_criteria=["x"])
        rm = await call(session, "set_roadmap", goal_id=gid, roadmap_draft={"summary": "", "phases": [
            {"title": "P", "items": [{"type": "topic", "title": "DSA", "est_hours": 10},
                                     {"type": "task", "title": "Ship app", "est_hours": 5}]}]})
        dsa, ship = rm["phases"][0]["items"]
        assert dsa["proof"] == "interview" and ship["proof"] == "deliverable"
        await call(session, "confirm_commitment", goal_id=gid, target_date=str(today + timedelta(days=90)),
                   routine=[{"days": ALL_DAYS, "start": "09:00", "end": "11:00", "activity": "Study"}])

        ctx = await call(session, "get_study_context")
        assert ctx["items_needing_topics"][0]["item_id"] == dsa["id"] and ctx["available_minutes"] == 120

        split = await call(session, "set_item_topics", item_id=dsa["id"], topics=[GRAPHS, HEAPS])
        graphs, heaps = [t["topic_id"] for t in split["topics"]]
        ctx = await call(session, "get_study_context")
        assert [t["title"] for t in ctx["topics"]] == ["Graphs", "Heaps"] and not ctx["items_needing_topics"]

        # Notes are saved per topic, and a later version replaces the first
        assert (await call(session, "get_topic_notes", topic_id=graphs))["content"] is None
        first = await call(session, "save_topic_notes", topic_id=graphs, content="# BFS")
        again = await call(session, "save_topic_notes", topic_id=graphs, content="# BFS and DFS")
        assert first["note_id"] == again["note_id"] and first["title"] == "Graphs"
        assert (await call(session, "get_topic_notes", topic_id=graphs))["content"] == "# BFS and DFS"
        empty = await session.call_tool("save_topic_notes", {"topic_id": graphs, "content": "  "})
        assert empty.is_error and "empty" in empty.content[0].text

        # Hours alone can't finish a knowledge item
        refused = await session.call_tool("update_roadmap_item", {"item_id": dsa["id"], "status": "done"})
        assert refused.is_error and "unpassed topics" in refused.content[0].text
        await call(session, "save_day_review", review={
            "activities": [{"description": "DSA", "minutes": 120, "kind": "learn", "links": [{"goal_id": gid}]}],
            "item_progress": [{"roadmap_item_id": dsa["id"], "hours": 2, "completed": True}]})
        assert (await call(session, "get_roadmap", goal_id=gid))["phases"][0]["items"][0]["status"] != "done"

        # Failed interview: 62%, tomorrow carries the weak subtopic only
        failed = await call(session, "save_interview", topic_id=graphs, minutes=60,
                            questions=marks(("BFS", 4.5), ("DFS", 1.5, )))
        assert not failed["passed"] and failed["percent_learned"] == 60 and failed["weak_subtopics"] == ["DFS"]
        assert failed["continues_on"] == tomorrow
        next_day = await call(session, "get_study_context", day=tomorrow)
        first = next_day["topics"][0]
        assert first["title"] == "Graphs" and first["mode"] == "carryover" and first["weak_concepts"] == ["DFS"]
        assert first["minutes"] == 20  # a third of the topic

        # Passing sets a re-test; the item finishes when all topics pass
        passed = await call(session, "save_interview", topic_id=graphs, day=tomorrow,
                            questions=marks(("BFS", 5), ("DFS", 4.5)))
        assert passed["passed"] and passed["next_review_on"] == str(today + timedelta(days=4))
        assert not passed["roadmap_item_finished"]
        heap = await call(session, "save_interview", topic_id=heaps, day=tomorrow,
                          questions=marks(("Heapify", 5), ("Heapify", 5)))
        assert heap["roadmap_item_finished"]
        mastery = await call(session, "get_mastery", goal_id=gid)
        assert mastery["items"][0]["passed"] == 2 and mastery["items"][0]["total"] == 2

        # A failed re-test re-opens the topic and the item
        review_day = str(today + timedelta(days=4))
        due = await call(session, "get_study_context", day=review_day)
        assert due["topics"][0]["mode"] == "retest"
        lost = await call(session, "save_interview", topic_id=graphs, kind="retest", day=review_day,
                          questions=marks(("DFS", 2)))
        assert not lost["passed"] and lost["next_review_on"] is None
        assert (await call(session, "get_roadmap", goal_id=gid))["phases"][0]["items"][0]["status"] == "in_progress"

        # Off-plan learning counts, and the day is judged on value
        extra = await call(session, "add_study_topic", goal_id=gid, title="Vector databases", est_minutes=30,
                           concepts=[{"name": "HNSW"}])
        assert extra["source"] == "offplan"
        assert "Vector databases" in [t["title"] for t in (await call(session, "get_study_context"))["topics"]]
        day = await call(session, "save_day_review", day=str(today), review={
            "activities": [{"description": "Vector DBs", "minutes": 120, "kind": "learn", "links": [{"goal_id": gid}]}],
            "goal_impacts": [{"goal_id": gid, "impact": 7}], "time_value": 9,
            "time_value_reason": "Valuable off-plan topic"})
        assert "work quality 7.6/10" in day["this_week"]["explanation"]  # 70% rating 7, 30% time value 9
        assert day["time_value_reason"] == "Valuable off-plan topic"

        # A physical goal: measured by numbers, with no interview
        fit = (await call(session, "create_goal", title="Get fit", category="health",
                          target_date=str(today + timedelta(days=60))))["goal_id"]
        metric = await call(session, "add_metric", goal_id=fit, name="Body weight", unit="kg", start_value=82,
                            target_value=76)
        logged = await call(session, "log_metric", metric_id=metric["metric_id"], value=81)
        assert logged["latest_value"] == 81 and logged["progress_pct"] == 16.7
        overview = await call(session, "get_overview")
        assert overview["goals"][1]["metrics"][0]["name"] == "Body weight"
        assert overview["goals"][0]["roadmap_check_due"]
        await call(session, "mark_roadmap_checked", goal_id=gid, summary="Added vector DBs")
        assert not (await call(session, "get_overview"))["goals"][0]["roadmap_check_due"]

        stats = await call(session, "get_weekly_stats", week_start=str(today + timedelta(days=1)))
        assert stats["study"]["topics_passed"] >= 1

        # The job search, from Claude
        job = await call(session, "save_application", company="Anthropic", role="AI Engineer")
        await call(session, "save_application", company="Anthropic", application_id=job["id"], stage="final")
        pipeline = await call(session, "get_applications")
        assert pipeline["by_stage"] == {"final": 1} and pipeline["final_rounds_reached"] == 1
        sent = await call(session, "add_metric", goal_id=gid, name="Applications", start_value=0, target_value=30,
                          source="applications")
        assert sent["latest_value"] == 1
        linked = await call(session, "update_roadmap_item", item_id=ship["id"], link_url="https://github.com/me/app",
                            link_title="Repo")
        assert linked["item"]["id"] == ship["id"]


async def test_rest_day_shows_whats_ahead_and_extra_work_is_a_bonus():
    db = Path(tempfile.mkdtemp()) / "rest.db"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "OWNER_EMAIL": "owner@example.com"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        today = date.fromisoformat((await call(session, "get_overview"))["today"])
        tomorrow = today + timedelta(days=1)
        gid = (await call(session, "create_goal", title="AI engineer"))["goal_id"]
        await call(session, "confirm_goal_definition", goal_id=gid, statement="AI", success_criteria=["x"])
        rm = await call(session, "set_roadmap", goal_id=gid, roadmap_draft={"summary": "", "phases": [
            {"title": "P", "items": [{"type": "topic", "title": "DSA", "est_hours": 10}]}]})
        dsa = rm["phases"][0]["items"][0]["id"]
        working = [d for d in ALL_DAYS if d != ALL_DAYS[today.weekday()]]  # today is the weekly rest day
        await call(session, "confirm_commitment", goal_id=gid, target_date=str(today + timedelta(days=90)),
                   routine=[{"days": working, "start": "09:00", "end": "10:00", "activity": "Study"}])
        split = await call(session, "set_item_topics", item_id=dsa, topics=[GRAPHS, HEAPS])
        graphs = split["topics"][0]["topic_id"]

        # Nothing is due, but what's ahead is visible day by day
        ctx = await call(session, "get_study_context")
        assert ctx["rest_day"] and not ctx["topics"] and ctx["available_minutes"] == 0
        ahead = [(d["date"], [t["title"] for t in d["topics"]]) for d in ctx["coming_up"]]
        assert ahead == [(str(tomorrow), ["Graphs"]), (str(tomorrow + timedelta(days=1)), ["Heaps"])]
        assert (await call(session, "plan_day"))["rest_day"]

        # Working anyway: an early pass moves the next topic up
        answers = marks(("BFS", 5), ("BFS", 5), ("DFS", 5), ("DFS", 4))
        out = await call(session, "save_interview", topic_id=graphs, minutes=45, questions=answers)
        assert out["passed"]

        # The same save again, as after a dropped connection, changes nothing
        again = await call(session, "save_interview", topic_id=graphs, minutes=45, questions=answers)
        assert again["already_saved"] and again["passed"]
        day_view = await call(session, "get_day_context")
        assert [(x["minutes"], x["source"]) for x in day_view["already_logged"]] == [(45, "interview")]
        ctx = await call(session, "get_study_context")
        assert ctx["coming_up"][0]["date"] == str(tomorrow)
        assert [t["title"] for t in ctx["coming_up"][0]["topics"]] == ["Heaps"]

        # The review credits the hours to the week, however the day is rated
        streak = (await call(session, "get_overview"))["streak_days"]
        day = await call(session, "save_day_review", review={
            "activities": [{"description": "Graphs", "minutes": 45, "kind": "learn", "links": [{"goal_id": gid}]},
                           {"description": "Heaps", "minutes": 15, "kind": "learn",
                            "links": [{"goal_id": gid, "roadmap_item_id": dsa}]}],
            "goal_impacts": [{"goal_id": gid, "impact": 8}], "time_value": 9,
            "item_progress": [{"roadmap_item_id": dsa, "hours": 1.0}]})  # all of it, the server subtracts the interview
        assert day["rest_day"] and "score" not in day and day["bonus_minutes"] == 60
        assert day["this_week"]["hours_done"] == 1.0  # a rest day's work still counts toward the week
        assert (await call(session, "get_overview"))["streak_days"] == streak
        logged = (await call(session, "get_roadmap", goal_id=gid))["phases"][0]["items"][0]["hours_logged"]
        assert logged == 1.0  # 45 minutes from the interview, 15 from the review

        # A session they add for themselves and then skip costs nothing
        added = await call(session, "edit_plan", add=[{"title": "Extra DSA", "minutes": 60, "goal_id": gid}])
        skipped = await call(session, "save_day_review", review={"activities": []}, plan_status=[
            {"plan_item_id": added["plan"][0]["plan_item_id"], "status": "skipped"}])
        assert skipped["rest_day"]

        # Turning a rest day into a work day gives it a usual day's time and a plan; undoing it clears the plan
        worked = await call(session, "set_day_type", day_type="work")
        assert worked["day_type"] == "work" and worked["plan"]
        assert (await call(session, "get_study_context"))["available_minutes"] == 60
        assert (await call(session, "set_day_type", day_type="normal"))["day_type"] == "normal"
        assert (await call(session, "get_study_context"))["rest_day"]

        # Taking a working day off: no topics that day, and the forecast moves past it
        off = await call(session, "set_day_type", day_type="rest", day=str(tomorrow))
        assert off["day_type"] == "rest"
        assert (await call(session, "get_study_context"))["coming_up"][0]["date"] == str(tomorrow + timedelta(days=1))

        # Moving a roadmap step re-dates what's left
        added = await call(session, "add_roadmap_item", goal_id=gid, title="Portfolio site", est_hours=4)
        moved = await call(session, "move_roadmap_item", item_id=added["item"]["id"],
                           phase_id=rm["phases"][0]["phase_id"])
        assert moved["phases"][0]["items"][0]["title"] == "Portfolio site"
