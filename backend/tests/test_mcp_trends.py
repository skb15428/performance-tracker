"""What's new over MCP: search terms + watch topics, ranking, arXiv cap, memory, impact preview, sources."""

import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.test_mcp_server import call

BACKEND = Path(__file__).resolve().parents[1]
ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def add_items(db: Path, source_ids: dict[str, int], rows: list[tuple[str, str, str, int]]) -> None:
    con = sqlite3.connect(db)
    for source, title, url, days_old in rows:
        ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S.%f")
        con.execute("insert into trend_items (source_id, title, url, summary, published_at) values (?, ?, ?, '', ?)",
                    (source_ids[source], title, url, ts))
    con.commit()
    con.close()


async def test_whats_new_flow():
    db = Path(tempfile.mkdtemp()) / "trends.db"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
           "OWNER_EMAIL": "owner@example.com"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND), env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        today = date.fromisoformat((await call(session, "get_overview"))["today"])
        gid = (await call(session, "create_goal", title="AI engineer"))["goal_id"]
        await call(session, "confirm_goal_definition", goal_id=gid, statement="AI engineer", success_criteria=["x"])
        rm = await call(session, "set_roadmap", goal_id=gid, roadmap_draft={"summary": "", "phases": [
            {"title": "P", "items": [{"title": "Retrieval fundamentals", "est_hours": 8},
                                     {"title": "Evals", "est_hours": 6}]}]})
        first = rm["phases"][0]["items"][0]["id"]
        await call(session, "confirm_commitment", goal_id=gid, target_date=str(today + timedelta(days=90)),
                   routine=[{"days": ALL_DAYS, "start": "07:00", "end": "08:00", "activity": "Study"}])
        assert (await call(session, "get_overview"))["goals"][0]["trends_check_due"]

        terms = await call(session, "set_search_terms", goal_id=gid,
                           watch_topics=[{"topic": "AI engineer hiring", "terms": ["AI engineer", "hiring"]}],
                           item_terms=[{"roadmap_item_id": first, "terms": ["RAG", "retrieval-augmented", "reranker"]}])
        assert [i["title"] for i in terms["items_without_terms"]] == ["Evals"]

        sources = {s["name"]: s["id"] for s in (await call(session, "manage_sources", action="list"))["sources"]}
        add_items(db, sources, [
            *[("arXiv cs.CL (NLP/LLMs)", f"Retrieval-augmented generation study #{n}", f"https://arxiv.org/abs/{n}", 1)
              for n in range(12)],
            ("Simon Willison", "A neat reranker trick for RAG", "https://simonwillison.net/rag", 2),
            ("Hacker News best", "Who is hiring: AI engineer roles", "https://news.ycombinator.com/hiring", 1),
            ("Hacker News best", "A new JavaScript bundler", "https://news.ycombinator.com/js", 1),
            ("Simon Willison", "Old RAG post", "https://simonwillison.net/old", 30),
        ])

        cand = await call(session, "get_trend_candidates", goal_id=gid)
        urls = [c["url"] for c in cand["candidates"]]
        assert urls[0] == "https://simonwillison.net/rag"  # curated source + two title hits beats arXiv volume
        assert sum("arxiv.org" in u for u in urls) == 8  # capped
        hn = next(c for c in cand["candidates"] if c["url"].endswith("/hiring"))
        assert {m["for"] for m in hn["matched"]} == {"watch: AI engineer hiring"}
        assert "https://news.ycombinator.com/js" not in urls and "https://simonwillison.net/old" not in urls
        assert not (await call(session, "get_overview"))["goals"][0]["trends_check_due"]

        rec = await call(session, "record_trend_suggestions", goal_id=gid, suggestions=[
            {"title": "Reranking for RAG", "why_relevant": "Biggest quality win for your retriever",
             "url": "https://simonwillison.net/rag", "est_hours": 3},
            {"title": "AI engineer job market", "why_relevant": "What companies ask for",
             "url": "https://news.ycombinator.com/hiring", "est_hours": 1, "type": "task"}])
        first_sg, second_sg = rec["suggestions"]
        assert first_sg["finish_if_added"] > first_sg["finish_now"]  # 3 more hours at 1h/day

        again = await call(session, "get_trend_candidates", goal_id=gid)
        assert "https://simonwillison.net/rag" not in [c["url"] for c in again["candidates"]]  # never twice
        assert {p["title"] for p in again["previously_suggested"]} == {"Reranking for RAG", "AI engineer job market"}

        added = await call(session, "resolve_trend_suggestion", suggestion_id=first_sg["suggestion_id"], action="add")
        assert added["item"]["source"] == "trend" and added["item"]["planned_start"] == str(today + timedelta(days=8))
        assert (await call(session, "resolve_trend_suggestion", suggestion_id=second_sg["suggestion_id"],
                           action="dismiss"))["status"] == "dismissed"

        before = len((await call(session, "get_roadmap", goal_id=gid))["phases"][0]["items"])
        preview = await call(session, "add_roadmap_item", goal_id=gid, title="LangGraph", est_hours=5, preview=True)
        assert preview["finish_if_added"] > preview["finish_now"]
        assert len((await call(session, "get_roadmap", goal_id=gid))["phases"][0]["items"]) == before  # not added

        srcs = await call(session, "manage_sources", action="add",
                          source={"name": "Latent Space", "url": "https://www.latent.space/feed"})
        mine = next(s for s in srcs["sources"] if s["name"] == "Latent Space")
        assert not mine["built_in"]
        arxiv_id = sources["arXiv cs.AI"]
        assert not next(s for s in (await call(session, "manage_sources", action="disable", source_id=arxiv_id))["sources"]
                        if s["id"] == arxiv_id)["enabled"]
        res = await session.call_tool("manage_sources", {"action": "remove", "source_id": arxiv_id})
        assert res.is_error and "can't be removed" in res.content[0].text
        await call(session, "manage_sources", action="remove", source_id=mine["id"])
