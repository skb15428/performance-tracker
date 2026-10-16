"""Smart reminders: skip rest days and logged days, open Claude, build the morning plan from the routine."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Goal, PlanItem, PushSubscription, RoadmapItem, RoadmapPhase, User
from app.services import push
from tests.conftest import register

SAT = datetime(2026, 10, 17, tzinfo=timezone.utc)  # Saturday


async def setup_user(client, email: str):
    await register(client, email)
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == email))
        user.timezone, user.reminder_time, user.morning_push = "UTC", "21:00", True
        goal = Goal(user_id=user.id, title="AI", priority=3, intake_status="active", status="active",
                    hours_per_day=1.5, days_per_week=5,
                    routine=[{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:00", "end": "08:30",
                              "activity": "Study", "focus": "learn"}])
        goal.phases = [RoadmapPhase(title="P", order=0, items=[RoadmapItem(title="RAG", est_hours=10)])]
        s.add(goal)
        s.add(PushSubscription(user_id=user.id, endpoint=f"https://push.example/{email}", p256dh="k", auth="a"))
        await s.commit()
        return user.id


async def test_reminders(client, monkeypatch):
    sent: list[dict] = []

    async def fake_send(session, user_id, payload):
        sent.append(payload)
        return 1

    monkeypatch.setattr(push, "send_to_user", fake_send)
    uid = await setup_user(client, "reminders@example.com")

    async with SessionLocal() as s:
        # Saturday night: nothing in the routine, no plan -> rest day, no nudge
        await push.run_reminders(s, SAT.replace(hour=21, minute=5))
        assert sent == []
        # Monday 07:00: no plan yet -> built from the routine and pushed
        monday = SAT + timedelta(days=2)
        await push.run_reminders(s, monday.replace(hour=7, minute=3))
        assert sent[-1]["title"] == "Today: 1 block" and sent[-1]["body"] == "07:00-08:30 Study: RAG"
        plan = list(await s.scalars(select(PlanItem).where(PlanItem.user_id == uid)))
        assert len(plan) == 1
        # Monday night, not logged -> nudge that opens Claude, only once
        await push.run_reminders(s, monday.replace(hour=21, minute=1))
        await push.run_reminders(s, monday.replace(hour=21, minute=16))
        nightly = [p for p in sent if p["title"] == "How did today go?"]
        assert len(nightly) == 1 and nightly[0]["url"] == "https://claude.ai/new?q=Log%20my%20day"
