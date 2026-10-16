"""Drive the MCP server over real stdio, the way Claude Desktop does, against a throwaway SQLite file."""

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

BACKEND = Path(__file__).resolve().parents[1]

ROADMAP = {
    "summary": "Backend dev to AI engineer",
    "phases": [
        {"title": "Foundations", "items": [
            {"type": "topic", "title": "RAG fundamentals", "est_hours": 6},
            {"type": "skill", "title": "LLM evals", "est_hours": 4},
        ]},
        {"title": "Proof of work", "items": [{"type": "task", "title": "Build a RAG app", "est_hours": 12}]},
    ],
}


async def call(session: ClientSession, tool: str, **args):
    result = await session.call_tool(tool, args)
    text = result.content[0].text
    assert not result.is_error, f"{tool} failed: {text}"
    return json.loads(text)


async def test_mcp_end_to_end():
    db = Path(tempfile.mkdtemp()) / "mcp.db"
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "OWNER_EMAIL": "owner@example.com",
        "GEMINI_API_KEY": "",
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
        assert {"get_overview", "set_roadmap", "save_day_review", "preview_replan"} <= tools
        prompts = {p.name for p in (await session.list_prompts()).prompts}
        assert {"log_my_day", "new_goal", "weekly_review", "whats_new"} <= prompts

        overview = await call(session, "get_overview")
        assert overview["goals"] == [] and overview["today_logged"] is False
        today = date.fromisoformat(overview["today"])

        goal = await call(session, "create_goal", title="Become an AI engineer", category="career", priority=4)
        gid = goal["goal_id"]
        assert goal["intake"]["checkpoints"] == {"goal_definition": False, "roadmap": False,
                                                 "timeline_and_daily_commitment": False}
        facts = await call(session, "save_goal_facts", goal_id=gid, facts={"experience": "5y backend"})
        assert facts["facts"]["experience"] == "5y backend"

        # Checkpoint 1: exact goal
        d = await call(session, "confirm_goal_definition", goal_id=gid,
                       statement="AI Engineer offer at an AI-first company by June 2027",
                       success_criteria=["Offer letter", "Shipped RAG project"])
        assert d["intake"]["checkpoints"]["goal_definition"] and not d["intake"]["complete"]

        # Checkpoint 2: roadmap (goal not active yet)
        rm = await call(session, "set_roadmap", goal_id=gid, roadmap_draft=ROADMAP)
        assert rm["goal"]["intake_status"] == "commitment_pending" and rm["total_hours"] == 22
        rag_id = rm["phases"][0]["items"][0]["id"]
        status = await call(session, "get_intake_status", goal_id=gid)
        assert "propose_commitment" in status["next_step"]

        # Checkpoint 3: timeline + daily commitment
        target = today + timedelta(days=30)
        prop = await call(session, "propose_commitment", goal_id=gid, target_date=str(target), hours_per_day=1.5,
                          days_per_week=6)
        assert prop["remaining_roadmap_hours"] == 22 and prop["at_your_pace"]["meets_target"]
        assert prop["capacity"]["fits"] and len(prop["options"]) == 8
        weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][today.weekday()]
        tomorrow_wd = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][(today.weekday() + 1) % 7]
        rest = next(w for w in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] if w not in (weekday, tomorrow_wd))
        days = [w for w in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] if w != rest]
        conf = await call(session, "confirm_commitment", goal_id=gid, target_date=str(target), routine=[{"days": days, "start": "07:00", "end": "08:30",
                                                     "activity": "Study roadmap topic"}])
        assert conf["goal"]["intake_status"] == "active" and conf["goal"]["intake"]["complete"]
        assert conf["warnings"] == [] and conf["goal"]["commitment"]["weekly_hours"] == 9
        assert conf["goal"]["commitment"]["hours_per_day"] == 1.5 and conf["goal"]["commitment"]["days_per_week"] == 6
        assert conf["phases"][0]["items"][0]["planned_start"] == str(today)

        ctx = await call(session, "get_day_context")
        assert ctx["goals"][0]["focus_items"][0]["id"] == rag_id
        assert ctx["goals"][0]["planned_minutes_today"] == 90 and ctx["goals"][0]["routine_tomorrow"][0]["start"] == "07:00"

        saved = await call(session, "save_day_review", review={
            "activities": [
                {"description": "Read RAG paper", "minutes": 90, "kind": "learn",
                 "links": [{"goal_id": gid, "roadmap_item_id": rag_id, "relevance": 1, "reason": "Core topic"}]},
                {"description": "Office", "minutes": 480, "kind": "job"},
                {"description": "Scrolling", "minutes": 45, "kind": "waste"},
            ],
            "goal_impacts": [{"goal_id": gid, "impact": 6, "note": "Solid RAG reading"}],
            "item_progress": [{"roadmap_item_id": rag_id, "hours": 1.5}],
            "went_well": ["Focused reading"], "went_badly": ["45 min scrolling"],
            "tomorrow": [{"time_block": "07:00-08:30", "title": "Build toy retriever", "minutes": 90,
                          "roadmap_item_id": rag_id}],
            "tip": "Phone out of the bedroom",
        }, schedule=[{"start": "07:00", "end": "08:30", "activity": "Read RAG paper"}], notes="Good day", energy=4)
        assert saved["score"] > 0 and saved["per_goal"][str(gid)]["llm"] == 6
        assert saved["off_goal_minutes"] == 45  # job is neutral, scrolling is waste
        assert saved["tomorrow_plan"][0]["title"] == "Build toy retriever"

        assert saved["score_explanation"].endswith(f"= {saved['score']}")

        overview = await call(session, "get_overview")
        assert overview["today_logged"] and overview["streak_days"] == 1 and overview["unlogged_days"] == []

        # Next day: half of the planned block done -> partial credit in the plan part of the score
        tomorrow = str(today + timedelta(days=1))
        plan = (await call(session, "get_day_context", day=tomorrow))["plan_for_this_day"]
        nxt = await call(session, "save_day_review", day=tomorrow, review={
            "activities": [{"description": "Retriever", "minutes": 45, "kind": "build",
                            "links": [{"goal_id": gid, "roadmap_item_id": rag_id}]}]},
            plan_status=[{"plan_item_id": plan[0]["plan_item_id"], "status": "partial", "done_minutes": 45}])
        assert nxt["breakdown"]["plan_adherence"] == 0.5

        # A day off is recorded but not scored
        off = await call(session, "save_day_review", day=str(today - timedelta(days=1)), day_off=True,
                         review={"activities": []}, notes="Sick")
        assert off["rest_day"] and off["score"] is None

        preview = await call(session, "preview_replan", goal_id=gid, strategy="reduce_scope",
                             reason="Protect the deadline", skip_item_ids=[rm["phases"][0]["items"][1]["id"]])
        assert any(c["action"] == "skip" for c in preview["changes"])
        assert (await call(session, "resolve_replan", proposal_id=preview["proposal_id"], accept=True))["status"] \
            == "accepted"

        added = await call(session, "add_roadmap_item", goal_id=gid, title="Late chunking", est_hours=2,
                           source="trend", resources=[{"title": "post", "url": "https://example.com"}])
        assert added["item"]["source"] == "trend" and added["item"]["planned_start"] is not None

        timeline_view = await call(session, "get_timeline")
        assert timeline_view["goals"][0]["goal_id"] == gid

        candidates = await call(session, "get_trend_candidates", goal_id=gid)
        assert "rag" in [t.lower() for t in candidates["search_terms_used"]] and candidates["feeds_stale"]

        stats = await call(session, "get_weekly_stats")
        same_week = (today + timedelta(days=1)).weekday() != 0  # tomorrow is still this week
        assert stats["days_logged"] == (2 if same_week else 1)  # the day off doesn't count
        assert (await call(session, "save_weekly_review", summary="Good start", wins=["RAG"], gaps=[],
                           recommendations=["Ship the retriever"]))["saved"]

        history = {d["date"]: d for d in (await call(session, "get_history", days=7))["days"]}
        assert history[str(today)]["minutes_per_goal"]["Become an AI engineer"] == 90
        assert history[str(today - timedelta(days=1))]["rest_day"] and history[str(today - timedelta(days=1))]["score"] is None
