"""End-to-end API flow with a fake LLM: intake -> roadmap -> nightly log -> replan -> trends -> weekly."""

from datetime import date, datetime, timedelta, timezone

from app.core.db import SessionLocal
from app.models import TrendItem, TrendSource
from app.services.llm import set_llm_override
from tests.conftest import register

ROADMAP = {
    "summary": "From backend dev to AI engineer",
    "suggested_target_date": None,
    "phases": [
        {"title": "LLM foundations", "items": [
            {"type": "topic", "title": "Transformers & LLM basics", "est_hours": 6},
            {"type": "topic", "title": "RAG fundamentals", "est_hours": 8,
             "resources": [{"title": "RAG paper", "url": "https://arxiv.org/abs/2005.11401"}]},
        ]},
        {"title": "Proof of work", "items": [
            {"type": "task", "title": "Build a RAG project", "est_hours": 20},
            {"type": "milestone", "title": "Publish project on GitHub", "est_hours": 2},
        ]},
    ],
}


async def test_full_flow(client, fake_llm):
    h = await register(client, "a@example.com")
    today = date.today()

    # --- intake interview ---
    fake_llm.queue("IntakeTurn", {"action": "ask", "message": "Great goal!",
                                  "questions": ["What's your current experience?", "Hours per day?"]})
    r = await client.post("/goals", headers=h, json={"title": "Become an AI engineer", "category": "career",
                                                     "priority": 4})
    assert r.status_code == 201, r.text
    goal_id = r.json()["goal"]["id"]
    assert "Hours per day?" in r.json()["messages"][-1]["content"]

    fake_llm.queue("IntakeTurn", {"action": "propose", "message": "Here's your plan",
                                  "facts": [{"key": "experience", "value": "5y backend"}], "roadmap": ROADMAP})
    r = await client.post(f"/goals/{goal_id}/chat", headers=h, json={"message": "5 years backend, 2h/day"})
    goal = r.json()["goal"]
    assert goal["intake_status"] == "roadmap_proposed"
    assert goal["context"]["experience"] == "5y backend"
    assert "Hours per day?" in fake_llm.prompts[-1][1] or "5 years backend" in fake_llm.prompts[-1][1]

    r = await client.post(f"/goals/{goal_id}/roadmap/approve", headers=h,
                          json={"roadmap": goal["proposed_roadmap"], "target_date": str(today + timedelta(days=90))})
    assert r.status_code == 200, r.text
    rm = r.json()
    assert rm["goal"]["intake_status"] == "active" and rm["feasibility"]["feasible"]
    items = [i for p in rm["phases"] for i in p["items"]]
    assert items[0]["planned_start"] == str(today)
    rag_id, basics_id = items[1]["id"], items[0]["id"]

    # --- nightly log ---
    r = await client.put(f"/entries/{today}", headers=h, json={
        "schedule": [{"start": "09:00", "end": "10:30", "activity": "Read about RAG"},
                     {"start": "10:30", "end": "12:00", "activity": "Twitter scrolling"}],
        "free_text": "Decent day", "energy": 3})
    assert r.status_code == 200
    fake_llm.queue("DayAnalysis", {
        "activities": [
            {"description": "Read about RAG", "minutes": 90, "kind": "learn",
             "links": [{"goal_id": goal_id, "roadmap_item_id": rag_id, "relevance": 1, "reason": "Core topic"},
                       {"goal_id": 9999, "relevance": 1}]},  # bogus id must be dropped
            {"description": "Twitter scrolling", "minutes": 90, "kind": "waste"},
        ],
        "goal_impacts": [{"goal_id": goal_id, "impact": 6}],
        "item_progress": [{"roadmap_item_id": rag_id, "hours": 1.5}],
        "went_well": ["Focused RAG reading"], "went_badly": ["90 min of scrolling"],
        "tomorrow": [{"time_block": "09:00-10:30", "title": "RAG: build a toy retriever", "minutes": 90,
                      "roadmap_item_id": rag_id}],
        "tip": "Block social media until noon",
    })
    r = await client.post(f"/entries/{today}/analyze", headers=h)
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["used_llm"] and len(draft["draft"]["activities"][0]["links"]) == 1
    assert "RAG fundamentals" in fake_llm.prompts[-1][1]

    r = await client.post(f"/entries/{today}/confirm", headers=h, json={"analysis": draft["draft"]})
    assert r.status_code == 200, r.text
    review = r.json()["review"]
    assert review["total_score"] > 0 and review["drift_minutes"] == 90
    assert review["per_goal"][str(goal_id)]["llm"] == 6

    # Confirming twice must not double-count hours.
    r = await client.post(f"/entries/{today}/confirm", headers=h, json={"analysis": draft["draft"]})
    rm = (await client.get(f"/goals/{goal_id}/roadmap", headers=h)).json()
    rag = next(i for p in rm["phases"] for i in p["items"] if i["id"] == rag_id)
    assert rag["hours_logged"] == 1.5 and rag["status"] == "in_progress"

    plan = (await client.get("/plan", headers=h, params={"day": str(today + timedelta(days=1))})).json()
    assert plan[0]["goal_id"] == goal_id and plan[0]["roadmap_item_id"] == rag_id

    # --- fall behind -> replan ---
    past = today - timedelta(days=12)
    for item_id in (basics_id, rag_id):  # both were due days ago, almost nothing done -> clearly behind
        await client.patch(f"/goals/roadmap/items/{item_id}", headers=h,
                           json={"planned_start": str(past), "planned_due": str(past + timedelta(days=3))})
    fake_llm.queue("ReplanDraft", {"strategy": "shift", "reason": "Slipped on basics"})
    r = await client.post("/jobs/check-timeline", headers={"X-Jobs-Secret": "test-secret"})
    assert r.json()["proposals"] == 1
    goal = (await client.get(f"/goals/{goal_id}", headers=h)).json()
    assert goal["timeline"]["state"] == "behind" and goal["pending_replan_id"]
    r = await client.post(f"/replans/{goal['pending_replan_id']}/accept", headers=h)
    assert r.json()["status"] == "accepted"
    rm = (await client.get(f"/goals/{goal_id}/roadmap", headers=h)).json()
    basics = next(i for p in rm["phases"] for i in p["items"] if i["id"] == basics_id)
    assert basics["planned_start"] >= str(today)
    assert (await client.post("/jobs/check-timeline")).status_code == 403

    # --- trends ---
    async with SessionLocal() as s:
        src = TrendSource(name="test", kind="rss", url="https://feed.test/rss")
        s.add(src)
        await s.flush()
        s.add(TrendItem(source_id=src.id, title="New RAG technique: late chunking", url="https://ex.com/late",
                        published_at=datetime.now(timezone.utc)))
        await s.commit()
    fake_llm.queue("TrendPicks", lambda prompt: {"suggestions": [
        {"title": "Late chunking for RAG", "why_relevant": "Improves retrieval quality", "est_hours": 3,
         "links": [{"title": "post", "url": "https://ex.com/late"}]}]} if "late chunking" in prompt else {})
    r = await client.post(f"/trends/scan/{goal_id}", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1
    r = await client.post(f"/trends/{r.json()[0]['id']}/add", headers=h)
    assert r.json()["status"] == "added_to_roadmap"
    rm = (await client.get(f"/goals/{goal_id}/roadmap", headers=h)).json()
    trend_item = next(i for p in rm["phases"] for i in p["items"] if i["source"] == "trend")
    assert trend_item["planned_start"] is not None

    # --- weekly review + dashboard ---
    fake_llm.queue("WeeklyText", {"summary": "Solid start.", "wins": ["RAG reading"], "gaps": ["Scrolling"],
                                  "recommendations": ["Ship the toy retriever"]})
    r = await client.post("/reviews/weekly", headers=h)
    assert r.status_code == 200 and r.json()["stats"]["days_logged"] == 1
    dash = (await client.get("/dashboard/summary", headers=h)).json()
    assert dash["streak"] == 1 and dash["latest"]["score"] == review["total_score"]
    assert dash["goals"][0]["burnup"][-1]["actual"] == 1.5

    # --- isolation ---
    h2 = await register(client, "b@example.com")
    assert (await client.get(f"/goals/{goal_id}", headers=h2)).status_code == 404
    assert (await client.get("/goals", headers=h2)).json() == []
    assert (await client.get(f"/entries/{today}", headers=h2)).json()["review"] is None


async def test_rule_fallback_without_llm(client):
    set_llm_override(None)  # no override and no server key -> rules only
    h = await register(client, "c@example.com")
    r = await client.post("/goals", headers=h, json={"title": "Start a business"})
    goal_id = r.json()["goal"]["id"]
    assert "isn't available" in r.json()["messages"][-1]["content"]

    rm = (await client.post(f"/goals/{goal_id}/roadmap/phases", headers=h, json={"title": "Validate"})).json()
    phase_id = rm["phases"][0]["id"]
    item = (await client.post(f"/goals/{goal_id}/roadmap/items", headers=h,
                              json={"phase_id": phase_id, "title": "10 customer interviews", "est_hours": 10})).json()
    await client.post(f"/goals/{goal_id}/roadmap/reschedule", headers=h)

    day = date.today()
    await client.put(f"/entries/{day}", headers=h, json={"schedule": [
        {"start": "18:00", "end": "20:00", "activity": "Customer calls", "kind": "network",
         "goal_id": goal_id, "roadmap_item_id": item["id"]}]})
    draft = (await client.post(f"/entries/{day}/analyze", headers=h)).json()
    assert draft["used_llm"] is False
    assert draft["draft"]["item_progress"] == [{"roadmap_item_id": item["id"], "hours": 2.0, "completed": False}]
    assert draft["draft"]["tomorrow"][0]["roadmap_item_id"] == item["id"]
    r = await client.post(f"/entries/{day}/confirm", headers=h, json={"analysis": draft["draft"], "used_llm": False})
    assert r.json()["review"]["total_score"] > 50


async def test_step_ticks_and_week_strip(client):
    from tests.conftest import register
    h = await register(client, "steps@example.com")
    r = await client.post("/goals", headers=h, json={"title": "Learn RAG"})
    goal_id = r.json()["goal"]["id"]
    phase = (await client.post(f"/goals/{goal_id}/roadmap/phases", headers=h, json={"title": "P"})).json()["phases"][0]
    await client.post(f"/goals/{goal_id}/roadmap/items", headers=h, json={"phase_id": phase["id"], "title": "RAG", "est_hours": 5})
    day = (await client.get("/dashboard/summary", headers=h)).json()["today"]
    item = (await client.post("/plan", headers=h, json={"date_for": day, "title": "Study", "minutes": 60})).json()
    # give it steps the way Claude does, then tick the second one from the web app
    from app.core.db import SessionLocal
    from app.models import PlanItem
    async with SessionLocal() as s:
        p = await s.get(PlanItem, item["id"])
        p.details = {"steps": [{"text": "Read", "minutes": 30}, {"text": "Code", "minutes": 30}], "done_when": "x"}
        await s.commit()
    out = (await client.patch(f"/plan/{item['id']}", headers=h, json={"done_steps": [1]})).json()
    assert [st.get("done") for st in out["details"]["steps"]] == [False, True] and out["details"]["done_when"] == "x"

    dash = (await client.get("/dashboard/summary", headers=h)).json()
    assert len(dash["week"]) == 7 and sum(d["is_today"] for d in dash["week"]) == 1
    today_cell = next(d for d in dash["week"] if d["is_today"])
    assert today_cell["state"] == "today" and today_cell["planned_minutes"] == 60
