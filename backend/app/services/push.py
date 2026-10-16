"""Web Push (PWA) notifications and the reminder schedule."""

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import DailyEntry, DailyReview, PlanItem, PushSubscription, User

log = logging.getLogger(__name__)
MORNING_TIME = "07:00"
WINDOW_MINUTES = 15  # matches the cron cadence


def local_now(tz: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    try:
        return now.astimezone(ZoneInfo(tz))
    except ZoneInfoNotFoundError:
        return now


def minutes_of(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_window(local: datetime, hhmm: str) -> bool:
    delta = local.hour * 60 + local.minute - minutes_of(hhmm)
    return 0 <= delta < WINDOW_MINUTES


async def send(session: AsyncSession, sub: PushSubscription, payload: dict) -> bool:
    settings = get_settings()
    if not settings.vapid_private_key:
        log.info("VAPID keys not configured; skipping push")
        return False
    try:
        await asyncio.to_thread(
            webpush,
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return True
    except WebPushException as e:
        if e.response is not None and e.response.status_code in (404, 410):
            await session.delete(sub)  # subscription expired
        else:
            log.warning("Push failed: %s", e)
        return False


async def send_to_user(session: AsyncSession, user_id, payload: dict) -> int:
    subs = list(await session.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)))
    return sum([await send(session, s, payload) for s in subs])


async def has_review(session: AsyncSession, user_id, day: date) -> bool:
    return bool(await session.scalar(
        select(DailyReview.id).join(DailyEntry).where(DailyEntry.user_id == user_id, DailyEntry.date == day)
    ))


CLAUDE_NEW_CHAT = "https://claude.ai/new"


def claude_link(message: str) -> str:
    """Opens a new Claude chat (the Claude app on a phone) with the message filled in."""
    return f"{CLAUDE_NEW_CHAT}?q={quote(message)}"


def plan_summary(plan: list[PlanItem]) -> str:
    first = plan[0]
    text = f"{first.time_block + ' ' if first.time_block else ''}{first.title}"
    return text + (f" (+{len(plan) - 1} more)" if len(plan) > 1 else "")


async def todays_plan(session: AsyncSession, user: User, today: date, create: bool) -> list[PlanItem]:
    """Today's plan; if there is none and `create`, build it from the routines (empty on a rest day)."""
    from app.services import analysis  # local import: analysis pulls in most of the app

    plan = await analysis.plan_for(session, user.id, today)
    if not plan and create:
        blocks = await analysis.rule_plan(session, user, today)
        if blocks:
            plan = await analysis.save_plan(session, user, today, blocks)
    return plan


async def is_rest_day(session: AsyncSession, user: User, today: date) -> bool:
    from app.services import analysis

    return not await analysis.plan_for(session, user.id, today) and not await analysis.rule_plan(session, user, today)


async def run_reminders(session: AsyncSession, now: datetime | None = None) -> int:
    sent = 0
    users = list(await session.scalars(
        select(User).where(User.id.in_(select(PushSubscription.user_id)), User.is_active.is_(True))
    ))
    for user in users:
        local = local_now(user.timezone, now)
        today = local.date()
        # Night reminder: once a day after reminder_time, unless already logged (a day off counts) or a rest day.
        if (local.hour * 60 + local.minute >= minutes_of(user.reminder_time)
                and user.last_reminded_on != today and not await has_review(session, user.id, today)):
            user.last_reminded_on = today
            if not await is_rest_day(session, user, today):
                sent += await send_to_user(session, user.id, {
                    "title": "How did today go?",
                    "body": "Tap to tell Claude about your day and get tomorrow's plan.",
                    "url": claude_link("Log my day"),
                })
        # Morning: today's plan, built from the routine if last night's review didn't make one.
        if user.morning_push and in_window(local, MORNING_TIME):
            plan = await todays_plan(session, user, today, create=True)
            if plan:
                sent += await send_to_user(session, user.id, {
                    "title": f"Today: {len(plan)} block{'s' if len(plan) > 1 else ''}",
                    "body": plan_summary(plan), "url": "/",
                })
    await session.flush()
    return sent
