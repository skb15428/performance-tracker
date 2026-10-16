"""Endpoints triggered by an external cron (GitHub Actions / cron-job.org). Protected by X-Jobs-Secret."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_jobs_secret
from app.core.db import get_session
from app.models import Goal, User, WeeklyReview
from app.services import push, timeline, weekly
from app.services.analysis import load_goals_with_items
from app.services.trends.feeds import ingest_all
from app.services.trends.scan import scan_goal

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_jobs_secret)])


async def active_users(session: AsyncSession) -> list[User]:
    return list(await session.scalars(
        select(User).where(User.is_active.is_(True), User.id.in_(select(Goal.user_id).where(Goal.status == "active")))
    ))


def user_today(user: User) -> date:
    return push.local_now(user.timezone).date()


@router.post("/send-reminders")
async def send_reminders(session: AsyncSession = Depends(get_session)):
    sent = await push.run_reminders(session)
    await session.commit()
    return {"sent": sent}


@router.post("/ingest-feeds")
async def ingest_feeds(session: AsyncSession = Depends(get_session)):
    added = await ingest_all(session)
    await session.commit()
    return {"added": added}


@router.post("/check-timeline")
async def check_timeline(session: AsyncSession = Depends(get_session)):
    proposals = 0
    for user in await active_users(session):
        today = user_today(user)
        for goal in await load_goals_with_items(session, user):
            if goal.intake_status != "active" or await timeline.pending_replan(session, goal.id):
                continue
            status = await timeline.goal_status(session, user, goal, today)
            if status.state == "behind" and await timeline.build_replan(session, user, goal, status, today):
                proposals += 1
        await session.commit()  # commit per user so one failure doesn't lose everything
    return {"proposals": proposals}


@router.post("/trend-scan")
async def trend_scan(session: AsyncSession = Depends(get_session)):
    created = 0
    for user in await active_users(session):
        for goal in await load_goals_with_items(session, user):
            if goal.intake_status == "active":
                created += len(await scan_goal(session, user, goal, user_today(user)))
        await session.commit()
    return {"created": created}


@router.post("/weekly-review")
async def weekly_review(session: AsyncSession = Depends(get_session)):
    """Generate last week's review for everyone who doesn't have one yet."""
    made = 0
    for user in await active_users(session):
        start = weekly.week_start_of(user_today(user) - timedelta(days=7))
        exists = await session.scalar(
            select(WeeklyReview.id).where(WeeklyReview.user_id == user.id, WeeklyReview.week_start == start)
        )
        if not exists:
            await weekly.generate(session, user, start)
            made += 1
            await session.commit()
    return {"generated": made, "at": datetime.now(timezone.utc).isoformat()}
