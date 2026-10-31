"""Work the app does by itself. It runs inside the web process, so reminders and checks don't depend on an outside cron
job; the keep-alive ping is what stays awake to run them."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import AppEvent, Goal, User
from app.services import events, push, timeline, weekly
from app.services.analysis import load_goals_with_items
from app.services.email import send_email
from app.services.trends.feeds import ingest_all

log = logging.getLogger(__name__)
TICK_SECONDS = 10 * 60
STARTUP_DELAY_SECONDS = 60  # let the app finish starting and answer its first requests


async def active_users(session: AsyncSession) -> list[User]:
    return list(await session.scalars(
        select(User).where(User.is_active.is_(True), User.id.in_(select(Goal.user_id).where(Goal.status == "active")))
    ))


async def check_timelines(session: AsyncSession) -> int:
    """Propose a replan for goals that have fallen behind. It works even if the user stopped logging."""
    proposals = 0
    for user in await active_users(session):
        today = push.local_now(user.timezone).date()
        for goal in await load_goals_with_items(session, user):
            if goal.intake_status != "active" or await timeline.pending_replan(session, goal.id):
                continue
            status = await timeline.goal_status(session, user, goal, today)
            if status.state == "behind" and await timeline.build_replan(session, user, goal, status, today):
                proposals += 1
        await session.commit()  # commit per user so one failure doesn't lose everything
    return proposals


async def freeze_weeks(session: AsyncSession) -> None:
    for user in await active_users(session):
        today = push.local_now(user.timezone).date()
        for goal in await load_goals_with_items(session, user):
            if goal.intake_status == "active":
                await weekly.freeze_past_weeks(session, user, goal, today)
    await session.commit()


async def mail_error_summary(session: AsyncSession) -> None:
    """If anything failed in the last day, say so by email, so a silent failure doesn't stay silent."""
    errors = await events.count_since(session, "error", 1)
    if not errors or not get_settings().resend_api_key:
        return
    for user in await active_users(session):
        await send_email(user.email, "GoalCoach had errors today", (
            f"<p>{errors} error{'s' if errors > 1 else ''} in the last 24 hours. See Settings for the latest.</p>"))


async def daily(session: AsyncSession) -> None:
    for job in (ingest_all, check_timelines, freeze_weeks, mail_error_summary):
        try:
            await job(session)
            await session.commit()
        except Exception as e:  # one failing job shouldn't stop the others
            await session.rollback()
            log.exception("Daily job %s failed", job.__name__)
            await events.record("error", {"where": job.__name__, "error": events.describe(e)})
    await events.prune(session)
    await session.commit()


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    async with SessionLocal() as session:
        await push.run_reminders(session, now)
        await session.commit()
        ran = await events.last(session, "daily")
        started = ran.created_at if ran else None
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if started is None or now - started >= timedelta(days=1):
            await daily(session)
            session.add(AppEvent(kind="daily"))
        await events.prune_kind(session, "heartbeat", keep=20)
        session.add(AppEvent(kind="heartbeat", data={"at": now.isoformat()}))
        await session.commit()


async def run_forever() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("Background tick failed")
            await events.record("error", {"where": "tick", "error": events.describe(e)})
        await asyncio.sleep(TICK_SECONDS)
