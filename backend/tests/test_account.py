"""Sign-in safety, the calendar feed, export and restore, job search, proof, readiness, and the app's own scheduler."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import AppEvent, Goal, RoadmapItem, StudyTopic, User
from app.routers import calendar
from app.services import background, backup, events, push
from tests.conftest import register
from tests.test_api_flow import setup_flexible_goal

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
PASSWORD = "pw-123456!"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


async def login(client, email: str, password: str):
    return await client.post("/auth/jwt/login", data={"username": email, "password": password})


async def test_repeated_wrong_passwords_lock_the_account(client):
    await register(client, "lock@example.com")
    for _ in range(5):
        assert (await login(client, "lock@example.com", "wrong-password")).status_code == 400
    assert (await login(client, "lock@example.com", PASSWORD)).status_code == 400  # even the right one, for now
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == "lock@example.com"))
        user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await s.commit()
    assert (await login(client, "lock@example.com", PASSWORD)).status_code == 200


async def test_a_good_login_clears_the_count(client):
    await register(client, "count@example.com")
    for _ in range(4):
        await login(client, "count@example.com", "wrong-password")
    assert (await login(client, "count@example.com", PASSWORD)).status_code == 200
    for _ in range(4):
        await login(client, "count@example.com", "wrong-password")
    assert (await login(client, "count@example.com", PASSWORD)).status_code == 200


async def test_changing_your_password(client):
    h = await register(client, "change@example.com")
    bad = await client.put("/me/password", headers=h, json={"current_password": "nope", "new_password": "long-enough-1"})
    assert bad.status_code == 400
    short = await client.put("/me/password", headers=h, json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 400
    ok = await client.put("/me/password", headers=h, json={"current_password": PASSWORD, "new_password": "long-enough-1"})
    assert ok.status_code == 200
    assert (await login(client, "change@example.com", "long-enough-1")).status_code == 200


async def test_forgot_password_sends_a_link(client, monkeypatch):
    from app.core import auth
    await register(client, "forgot@example.com")
    sent = []

    async def fake_email(to, subject, html):
        sent.append((to, html))
        return True

    monkeypatch.setattr(auth, "send_email", fake_email)
    assert (await client.post("/auth/forgot-password", json={"email": "forgot@example.com"})).status_code == 202
    assert sent[0][0] == "forgot@example.com" and "/reset-password?token=" in sent[0][1]
    token = sent[0][1].split("token=")[1].split('"')[0]
    r = await client.post("/auth/reset-password", json={"token": token, "password": "brand-new-pass"})
    assert r.status_code == 200
    assert (await login(client, "forgot@example.com", "brand-new-pass")).status_code == 200


async def test_calendar_feed_shows_the_plan_and_stays_private(client):
    today = utc_today()
    tomorrow = today + timedelta(days=1)
    h, goal_id, _ = await setup_flexible_goal(client, "cal@example.com", today, ALL_DAYS)
    assert (await client.get("/calendar/not-a-real-token-at-all-not-a-real-token.ics")).status_code == 404
    token = (await client.post("/me/calendar-token", headers=h)).json()["token"]
    await client.put(f"/entries/{tomorrow}/type", headers=h, json={"day_type": "rest"})
    await client.post("/plan", headers=h, json={"date_for": str(today), "title": "Deep, focused; work", "minutes": 60,
                                                "time_block": "09:00-10:00", "goal_id": goal_id})
    r = await client.get(f"/calendar/{token}.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.rstrip().endswith("END:VCALENDAR")
    assert r"Deep\, focused\; work" in text and "BEGIN:VALARM" in text and "Log your day" in text
    assert f"DTSTART;TZID=UTC:{today:%Y%m%d}T090000" in text
    assert f"DTSTART;TZID=UTC:{tomorrow:%Y%m%d}" not in text  # the rest day has nothing
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))

    # A new link replaces the old one
    assert (await client.post("/me/calendar-token", headers=h)).status_code == 200
    assert (await client.get(f"/calendar/{token}.ics")).status_code == 404


def test_long_calendar_lines_fold_without_breaking_letters():
    line = "SUMMARY:" + "नमस्ते" * 40
    folded = calendar.fold(line)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line


async def test_export_has_no_secrets_and_restores_into_an_empty_account(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "export@example.com", today, ALL_DAYS)
    await client.post("/time-logs", headers=h, json={"day": str(today), "goal_id": goal_id, "minutes": 30,
                                                     "roadmap_item_id": item_id})
    await client.post("/applications", headers=h, json={"company": "Anthropic", "stage": "applied"})
    data = (await client.get("/me/export", headers=h)).json()
    assert "hashed_password" not in data["user"] and data["tables"]["time_logs"][0]["minutes"] == 30
    assert data["tables"]["goals"][0]["id"] == goal_id
    status = (await client.get("/me/status", headers=h)).json()
    assert status["last_backup"] is not None

    h2 = await register(client, "restored@example.com")
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == "restored@example.com"))
        source = await s.scalar(select(User).where(User.email == "export@example.com"))
        # ids are kept in a real restore into a fresh database, so empty the source account first
        for row in list(await s.scalars(select(Goal).where(Goal.user_id == source.id))):
            await s.delete(row)
        await s.commit()
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == "restored@example.com"))
        data["tables"].pop("job_applications")
        counts = await backup.restore_user(s, user, data)
        await s.commit()
    assert counts["goals"] == 1 and counts["time_logs"] == 1
    goals = (await client.get("/goals", headers=h2)).json()
    assert [g["title"] for g in goals] == ["Learn RAG"]
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == "restored@example.com"))
        try:
            await backup.restore_user(s, user, data)
            raise AssertionError("restored over existing data")
        except ValueError:
            pass


async def test_job_search_and_targets_that_count_themselves(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "jobs@example.com", today, ALL_DAYS)
    other = await register(client, "jobs-b@example.com")
    for source, name, target in (("applications", "Applications", 30), ("final_rounds", "Final rounds", 3),
                                 ("proof_links", "Public proof", 3)):
        await client.post(f"/study/goals/{goal_id}/metrics", headers=h, json={
            "name": name, "target_value": target, "source": source})
    mocks = (await client.post(f"/study/goals/{goal_id}/metrics", headers=h, json={
        "name": "Mock interviews", "target_value": 10})).json()

    saved = (await client.post("/applications", headers=h, json={"company": "Saved Co"})).json()
    assert saved["stage"] == "saved" and saved["applied_on"] is None
    job = (await client.post("/applications", headers=h, json={"company": "Anthropic", "stage": "applied"})).json()
    assert job["applied_on"] == str(today)
    assert (await client.patch(f"/applications/{job['id']}", headers=other, json={"stage": "offer"})).status_code == 404
    await client.patch(f"/applications/{job['id']}", headers=h, json={"stage": "final"})
    rejected = (await client.patch(f"/applications/{job['id']}", headers=h, json={"stage": "rejected"})).json()
    assert rejected["reached_final"]  # it still counts as a final round

    bad = await client.post(f"/goals/roadmap/items/{item_id}/links", headers=h, json={"url": "javascript:alert(1)"})
    assert bad.status_code == 422
    bad = await client.post("/applications", headers=h, json={"company": "X", "url": "javascript:alert(1)"})
    assert bad.status_code == 422
    await client.post(f"/goals/roadmap/items/{item_id}/links", headers=h, json={"title": "Repo", "url": "https://x.dev/r"})
    assert (await client.post(f"/study/metrics/{mocks['id']}/log", headers=h, json={})).json()["latest_value"] == 1
    assert (await client.post(f"/study/metrics/{mocks['id']}/log", headers=h, json={})).json()["latest_value"] == 2

    card = {c["name"]: c for c in (await client.get("/dashboard/summary", headers=h)).json()["scorecard"]}
    assert card["Applications"]["latest_value"] == 1 and card["Final rounds"]["latest_value"] == 1
    assert card["Public proof"]["latest_value"] == 1 and card["Mock interviews"]["latest_value"] == 2
    automatic = card["Applications"]["id"]
    assert (await client.post(f"/study/metrics/{automatic}/log", headers=h, json={})).status_code == 400
    proof = (await client.get("/study/proof", headers=h)).json()["items"]
    assert proof[0]["links"][0]["title"] == "Repo"


async def test_readiness_shows_whats_proven_and_whats_weakest(client):
    today = utc_today()
    h, goal_id, item_id = await setup_flexible_goal(client, "ready@example.com", today, ALL_DAYS)
    async with SessionLocal() as s:
        (await s.get(RoadmapItem, item_id)).proof = "interview"
        s.add_all([
            StudyTopic(goal_id=goal_id, roadmap_item_id=item_id, order=0, title="A", status="passed", est_minutes=60,
                       next_review_on=today),
            StudyTopic(goal_id=goal_id, roadmap_item_id=item_id, order=1, title="B", status="learning", est_minutes=60,
                       weak_concepts=["Beam search", "Top-p"], concept_scores={"Beam search": 3, "Top-p": 1}),
        ])
        await s.commit()
    r = (await client.get("/study/readiness", headers=h)).json()
    assert r["passed"] == 1 and r["total"] == 2 and r["pct"] == 50 and r["retests_due"] == 1
    assert [w["concept"] for w in r["weakest"]] == ["Top-p", "Beam search"]


async def test_scheduler_runs_reminders_daily_jobs_and_reports_itself(client, monkeypatch):
    async def no_feeds(session):
        return 0

    monkeypatch.setattr(background, "ingest_all", no_feeds)
    h, _, _ = await setup_flexible_goal(client, "tick@example.com", utc_today(), ALL_DAYS)
    await background.tick()
    await background.tick()
    async with SessionLocal() as s:
        dailies = list(await s.scalars(select(AppEvent).where(AppEvent.kind == "daily")))
    assert len(dailies) == 1  # the day's work only runs once
    status = (await client.get("/me/status", headers=h)).json()
    assert status["scheduler_last_run"] is not None and status["email_enabled"] is False


async def test_a_failing_daily_job_is_recorded_and_doesnt_stop_the_rest(client, monkeypatch):
    ran = []

    async def broken(session):
        raise RuntimeError("feed exploded")

    async def fine(session):
        ran.append(True)

    monkeypatch.setattr(background, "ingest_all", broken)
    monkeypatch.setattr(background, "freeze_weeks", fine)
    h, _, _ = await setup_flexible_goal(client, "fail@example.com", utc_today(), ALL_DAYS)
    async with SessionLocal() as s:
        await background.daily(s)
    assert ran == [True]
    status = (await client.get("/me/status", headers=h)).json()
    assert status["errors_last_7_days"] >= 1 and "feed exploded" in status["last_error"]["error"]


def test_error_records_keep_out_the_data_involved():
    error = RuntimeError("UNIQUE constraint failed\n[parameters: ('me@example.com', 'my private note')]")
    assert events.describe(error) == "RuntimeError: UNIQUE constraint failed"


async def test_jobs_need_a_real_secret(client, monkeypatch):
    from app.core import auth
    assert (await client.post("/jobs/send-reminders")).status_code == 403
    assert (await client.post("/jobs/send-reminders", headers={"X-Jobs-Secret": "wrong"})).status_code == 403
    assert (await client.post("/jobs/export")).status_code in (404, 405)  # there's no bulk export to reach
    monkeypatch.setattr(auth.settings, "jobs_secret", "change-me-too")
    r = await client.post("/jobs/send-reminders", headers={"X-Jobs-Secret": "change-me-too"})
    assert r.status_code == 503  # the public default never unlocks anything


async def test_monday_reminds_about_the_weekly_review_and_silence_is_noticed(client, monkeypatch):
    sent = []
    h, goal_id, _ = await setup_flexible_goal(client, "nudge@example.com", date(2026, 10, 1), ALL_DAYS)
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == "nudge@example.com"))
        uid = user.id
        user.timezone, user.reminder_time, user.morning_push = "UTC", "21:00", False
        s.add(push.PushSubscription(user_id=uid, endpoint="https://push.example/nudge", p256dh="k", auth="a"))
        await s.commit()

    async def fake_send(session, user_id, payload):
        if user_id == uid:
            sent.append(payload)
        return 1

    monkeypatch.setattr(push, "send_to_user", fake_send)
    await client.post("/time-logs", headers=h, json={"day": "2026-10-29", "goal_id": goal_id, "minutes": 30})
    monday = datetime(2026, 11, 2, tzinfo=timezone.utc)
    async with SessionLocal() as s:
        await push.run_reminders(s, monday.replace(hour=9, minute=5))
        await push.run_reminders(s, monday.replace(hour=9, minute=15))
        await push.run_reminders(s, monday.replace(hour=21, minute=5))
        await s.commit()
    assert [p["title"] for p in sent] == ["Time for your weekly review", "How did today go?"]
    assert "Nothing logged for 4 days" in sent[1]["body"]


async def test_security_headers_are_set(client):
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


async def test_events_are_pruned(client):
    async with SessionLocal() as s:
        s.add(AppEvent(kind="old", created_at=datetime.now(timezone.utc) - timedelta(days=60)))
        await s.commit()
        await events.prune(s)
        await s.commit()
        assert await s.scalar(select(AppEvent).where(AppEvent.kind == "old")) is None
