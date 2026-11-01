"""Logging time from the app, frozen weeks, per-goal rest, fitness sessions, and study staying on the roadmap's order."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Goal, RoadmapItem, RoadmapPhase, StudyTopic, User
from app.services import analysis, timelogs, weekly
from app.services.llm.outputs import ActivityDraft, DayAnalysis, GoalImpact, ItemProgress, LinkDraft
from tests.conftest import register
from tests.test_api_flow import setup_flexible_goal

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def last_monday() -> date:
    today = utc_today()
    return today - timedelta(days=today.weekday() + 7)


async def owner(s, email: str) -> User:
    return await s.scalar(select(User).where(User.email == email))


async def item_hours(item_id: int) -> float:
    async with SessionLocal() as s:
        return (await s.get(RoadmapItem, item_id)).hours_logged


async def test_mark_done_counts_hours_and_undo_takes_them_back(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "done@example.com", today, ALL_DAYS)
    block = (await client.post("/plan", headers=h, json={"date_for": str(today), "title": "Study", "minutes": 90,
                                                         "goal_id": goal_id, "roadmap_item_id": item_id})).json()
    await client.patch(f"/plan/{block['id']}", headers=h, json={"status": "done"})
    assert await item_hours(item_id) == 1.5
    logs = (await client.get(f"/time-logs?day={today}", headers=h)).json()
    assert [(x["minutes"], x["source"]) for x in logs] == [(90, "block")]
    assert (await client.get("/dashboard/summary", headers=h)).json()["this_week"]["hours_done"] == 1.5

    # The timer's real time beats the block's length, and undoing removes it all
    await client.patch(f"/plan/{block['id']}", headers=h, json={"status": "partial", "done_minutes": 40})
    assert round(await item_hours(item_id), 2) == 0.67
    await client.patch(f"/plan/{block['id']}", headers=h, json={"status": "open"})
    assert await item_hours(item_id) == 0
    assert (await client.get(f"/time-logs?day={today}", headers=h)).json() == []


async def test_logging_time_in_the_app_counts_without_a_review_and_claude_cant_double_it(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "quick@example.com", today, ALL_DAYS)
    log = (await client.post("/time-logs", headers=h, json={"day": str(today), "goal_id": goal_id, "minutes": 60,
                                                            "roadmap_item_id": item_id, "note": "Reading"})).json()
    assert await item_hours(item_id) == 1
    dash = (await client.get("/dashboard/summary", headers=h)).json()
    assert dash["this_week"]["hours_done"] == 1 and next(c for c in dash["week"] if c["is_today"])["state"] == "done"

    # Claude reports the whole 2 hours that night: the hour already logged isn't credited again
    review = {"activities": [{"description": "Study", "minutes": 120, "kind": "learn", "links": [{"goal_id": goal_id}]}],
              "item_progress": [{"roadmap_item_id": item_id, "hours": 2}]}
    r = await client.post(f"/entries/{today}/confirm", headers=h, json={"analysis": review, "used_llm": False})
    assert r.status_code == 200
    assert await item_hours(item_id) == 2
    assert (await client.get("/dashboard/summary", headers=h)).json()["this_week"]["hours_done"] == 2

    # Saving the review again changes nothing
    await client.post(f"/entries/{today}/confirm", headers=h, json={"analysis": review, "used_llm": False})
    assert await item_hours(item_id) == 2

    await client.delete(f"/time-logs/{log['id']}", headers=h)
    assert await item_hours(item_id) == 1


async def test_time_logs_are_private_and_checked(client):
    today = utc_today()
    h, goal_id, _ = await setup_flexible_goal(client, "logs-a@example.com", today, ALL_DAYS)
    other = await register(client, "logs-b@example.com")
    body = {"day": str(today), "goal_id": goal_id, "minutes": 30}
    assert (await client.post("/time-logs", headers=other, json=body)).status_code == 404
    log = (await client.post("/time-logs", headers=h, json=body)).json()
    assert (await client.delete(f"/time-logs/{log['id']}", headers=other)).status_code == 404


async def test_todays_plan_appears_by_itself_and_names_the_topic(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "auto@example.com", today, ALL_DAYS)
    async with SessionLocal() as s:
        (await s.get(RoadmapItem, item_id)).proof = "interview"
        s.add(StudyTopic(goal_id=goal_id, roadmap_item_id=item_id, order=0, title="Chunking", est_minutes=120,
                         concepts=[{"name": "Fixed size", "core": True}, {"name": "Semantic", "core": True}]))
        await s.commit()
    dash = (await client.get("/dashboard/summary", headers=h)).json()
    block = dash["today_plan"][0]
    assert block["title"] == "Chunking" and block["minutes"] == 120 and block["time_block"] == "09:00-11:00"
    assert block["details"]["topic_id"] and "Fixed size" in block["details"]["steps"][0]["text"]
    assert sum(step["minutes"] for step in block["details"]["steps"]) == 120

    # It isn't built twice, and a marked rest day doesn't get one
    assert len((await client.get("/dashboard/summary", headers=h)).json()["today_plan"]) == 1
    tomorrow = today + timedelta(days=1)
    await client.put(f"/entries/{tomorrow}/type", headers=h, json={"day_type": "rest"})
    async with SessionLocal() as s:
        user = await owner(s, "auto@example.com")
        assert await analysis.rule_plan(s, user, tomorrow) == []


async def test_past_scores_dont_change_when_the_routine_does(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "frozen@example.com", monday, ALL_DAYS[:6])
    from tests.test_api_flow import log_hours
    await log_hours(client, h, goal_id, monday, 720)
    async with SessionLocal() as s:
        user = await owner(s, "frozen@example.com")
        today = utc_today()
        before = await weekly.week_score(s, user, monday, today)
        assert before["hours_target"] == 12 and before["score"] == 100
        goal = await s.get(Goal, goal_id)
        goal.routine = [{"days": ALL_DAYS, "start": "08:00", "end": "12:00", "activity": "Study"}]
        await s.flush()
        after = await weekly.week_score(s, user, monday, today)
        assert after["hours_target"] == 12 and after["score"] == 100
        await s.commit()


async def week_of(client, email: str, h: dict, goal_id: int, monday: date, hours: list[float],
                  marks: dict[int, str] | None = None) -> dict:
    """Logs a Mon-Sun week of hours, marks days rest or work, and returns how it scored."""
    from tests.test_api_flow import log_hours
    for offset, kind in (marks or {}).items():
        r = await client.put(f"/entries/{monday + timedelta(days=offset)}/type", headers=h, json={"day_type": kind})
        assert r.status_code == 200
    for offset, worked in enumerate(hours):
        if worked:
            await log_hours(client, h, goal_id, monday + timedelta(days=offset), round(worked * 60))
    async with SessionLocal() as s:
        return await weekly.week_score(s, await owner(s, email), monday, utc_today())


async def test_rest_tuesday_work_sunday_and_uneven_hours_still_make_a_full_week(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "swap@example.com", monday, ALL_DAYS[:6])
    week = await week_of(client, "swap@example.com", h, goal_id, monday, [4, 0, 2, 2, 1, 2, 1], {1: "rest", 6: "work"})
    assert (week["hours_done"], week["hours_target"], week["hours_pct"], week["score"]) == (12, 12, 100, 100)
    assert week["average_hours"] == 2 and week["planned_hours_per_day"] == 2


async def test_uneven_hours_add_up_without_marking_anything(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "unmarked@example.com", monday, ALL_DAYS[:6])
    week = await week_of(client, "unmarked@example.com", h, goal_id, monday, [4, 0, 2, 2, 1, 2, 1])
    assert (week["hours_done"], week["hours_target"], week["score"]) == (12, 12, 100)


async def test_a_short_week_scores_against_the_planned_average(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "short@example.com", monday, ALL_DAYS[:6])
    week = await week_of(client, "short@example.com", h, goal_id, monday, [4, 0, 0, 1, 0, 0, 1])
    assert (week["hours_done"], week["hours_target"], week["score"]) == (6, 12, 50)
    assert week["average_hours"] == 1 and week["planned_hours_per_day"] == 2


async def test_a_rest_day_lowers_the_week_by_one_day(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "one-rest@example.com", monday, ALL_DAYS[:6])
    week = await week_of(client, "one-rest@example.com", h, goal_id, monday, [2, 0, 2, 2, 2, 2, 0], {1: "rest"})
    assert (week["hours_done"], week["hours_target"], week["score"]) == (10, 10, 100)
    assert week["average_hours"] == 2


async def test_a_goal_started_on_a_rest_day_can_still_work_that_day(client):
    sunday = last_monday() + timedelta(days=6)
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "sunday@example.com", sunday, ALL_DAYS[:6])
    week = await week_of(client, "sunday@example.com", h, goal_id, monday, [0, 0, 0, 0, 0, 0, 2], {6: "work"})
    assert (week["hours_done"], week["hours_target"], week["score"]) == (2, 2, 100)
    assert week["average_hours"] == 2


async def test_the_weekly_report_uses_the_same_hours_as_the_score(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "report@example.com", monday, ALL_DAYS[:6])
    week = await week_of(client, "report@example.com", h, goal_id, monday, [4, 2, 2, 2, 1, 0, 1], {6: "work"})
    assert week["hours_target"] == 12  # working Sunday as well doesn't raise the bar to 14
    await client.post("/time-logs", headers=h, json={"day": str(monday + timedelta(days=5)), "goal_id": goal_id,
                                                     "minutes": 30})
    async with SessionLocal() as s:
        stats = await weekly.week_stats(s, await owner(s, "report@example.com"), monday, utc_today())
    assert stats["goals"][0]["committed_hours"] == 12 and stats["days_logged"] == 7


async def test_a_gym_session_counts_in_full_and_days_off_can_be_per_goal(client):
    today = utc_today()
    monday = today - timedelta(days=today.weekday())
    h = await register(client, "gym@example.com")
    async with SessionLocal() as s:
        user = await owner(s, "gym@example.com")
        work = Goal(user_id=user.id, title="Career", priority=3, intake_status="active", hours_per_day=2, days_per_week=7,
                    created_at=datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc),
                    routine=[{"days": ALL_DAYS, "start": "09:00", "end": "11:00", "activity": "Study"}])
        gym = Goal(user_id=user.id, title="Fitness", priority=3, intake_status="active", hours_per_day=1, days_per_week=7,
                   created_at=datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc),
                   routine=[{"days": ALL_DAYS, "start": "18:00", "end": "19:00", "activity": "Gym"}])
        work.phases = [RoadmapPhase(title="P", order=0, items=[RoadmapItem(title="Study", est_hours=100)])]
        gym.phases = [RoadmapPhase(title="P", order=0, items=[RoadmapItem(title="Train", est_hours=100, proof="log")])]
        s.add_all([work, gym])
        await s.commit()
        work_id, gym_id = work.id, gym.id

    # Resting the gym leaves study alone
    r = await client.put(f"/entries/{today}/type", headers=h, json={"day_type": "rest", "goal_id": gym_id})
    assert r.json()["goal_day_types"] == {str(gym_id): "rest"}
    async with SessionLocal() as s:
        user = await owner(s, "gym@example.com")
        goals = await analysis.tracked_goals(s, user)
        targets = await analysis.daily_targets(s, user, goals, today)
        assert targets[gym_id] == 0 and targets[work_id] == 120
        assert {b.goal_id for b in await analysis.rule_plan(s, user, today)} == {work_id}

    # 45 minutes logged as "other" in a one-hour slot is still a session done
    await client.put(f"/entries/{today}/type", headers=h, json={"day_type": None, "goal_id": gym_id})
    entry = {"activities": [{"description": "Run", "minutes": 45, "kind": "other", "links": [{"goal_id": gym_id}]}]}
    await client.post(f"/entries/{monday}/confirm", headers=h, json={"analysis": entry, "used_llm": False})
    async with SessionLocal() as s:
        user = await owner(s, "gym@example.com")
        week = await weekly.week_score(s, user, monday, monday)
        row = next(g for g in week["goals"] if g["goal_id"] == gym_id)
        assert row["sessions_done"] == 1 and row["hours_done"] == 1


async def test_a_measurable_target_affects_the_week(client):
    monday = last_monday()
    h, goal_id, _ = await setup_flexible_goal(client, "target@example.com", monday, ALL_DAYS[:6])
    from tests.test_api_flow import log_hours
    await log_hours(client, h, goal_id, monday, 720)
    metric = (await client.post(f"/study/goals/{goal_id}/metrics", headers=h, json={
        "name": "Weight", "unit": "kg", "start_value": 82, "target_value": 76})).json()
    async with SessionLocal() as s:
        goal = await s.get(Goal, goal_id)
        goal.target_date = utc_today() + timedelta(days=30)
        goal.created_at = goal.created_at - timedelta(days=1)
        await s.commit()
    await client.post(f"/study/metrics/{metric['id']}/log", headers=h, json={"value": 83})  # going the wrong way
    async with SessionLocal() as s:
        user = await owner(s, "target@example.com")
        week = await weekly.week_score(s, user, monday, utc_today())
    assert week["quality"] is not None and week["score"] < 100


async def test_goal_progress_counts_proof_not_hours(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "proof-pct@example.com", today, ALL_DAYS)
    async with SessionLocal() as s:
        item = await s.get(RoadmapItem, item_id)
        item.proof, item.hours_logged = "interview", 40
        s.add_all([StudyTopic(goal_id=goal_id, roadmap_item_id=item_id, order=n, title=t, est_minutes=60, status=st)
                   for n, (t, st) in enumerate((("A", "passed"), ("B", "new"), ("C", "learning"), ("D", "new")))])
        await s.commit()
    goal = (await client.get(f"/goals/{goal_id}", headers=h)).json()
    assert goal["progress_pct"] == 25  # all 40 hours worked, one topic in four proven


async def test_study_waits_for_a_project_ahead_of_it(client):
    today = utc_today()
    h, goal_id, first = await setup_flexible_goal(client, "order@example.com", today, ALL_DAYS)
    async with SessionLocal() as s:
        phase_id = (await s.get(RoadmapItem, first)).phase_id
        start = await s.get(RoadmapItem, first)
        start.proof = "deliverable"
        later = RoadmapItem(phase_id=phase_id, order=1, title="Later study", proof="interview", est_hours=5)
        s.add(later)
        await s.flush()
        s.add(StudyTopic(goal_id=goal_id, roadmap_item_id=later.id, order=0, title="Too soon", est_minutes=60,
                         concepts=[{"name": "x", "core": True}]))
        await s.commit()
    assert (await client.get("/study/today", headers=h)).json()["topics"] == []
    assert (await client.get("/study/upcoming", headers=h)).json()["days"] == []
    await client.patch(f"/goals/roadmap/items/{first}", headers=h, json={"status": "done"})
    assert [t["title"] for t in (await client.get("/study/today", headers=h)).json()["topics"]] == ["Too soon"]


async def test_a_review_on_a_day_with_an_interview_only_adds_the_rest(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "merge@example.com", today, ALL_DAYS)
    async with SessionLocal() as s:
        user = await owner(s, "merge@example.com")
        await timelogs.add(s, user, today, goal_id, 45, item_id, source="interview")
        entry = await analysis.get_or_create_entry(s, user, today)
        await analysis.confirm(s, user, entry, DayAnalysis(
            activities=[ActivityDraft(description="Study", minutes=60, kind="learn",
                                      links=[LinkDraft(goal_id=goal_id, relevance=1.0, reason="x")])],
            goal_impacts=[GoalImpact(goal_id=goal_id, impact=7, note="")],
            item_progress=[ItemProgress(roadmap_item_id=item_id, hours=1)]), used_llm=True)
        await s.commit()
    assert await item_hours(item_id) == 1
