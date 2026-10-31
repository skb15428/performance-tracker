"""A small record of what the app did by itself, shown in Settings so silent failures can't stay hidden."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.models import AppEvent

log = logging.getLogger(__name__)
KEEP_DAYS = 30


def describe(error: Exception) -> str:
    """Enough to know what failed. Only the first line: database errors list the values involved on later lines."""
    message = str(error).split("\n", 1)[0][:120]
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


async def record(kind: str, data: dict | None = None) -> None:
    """Saved in its own session, so it still lands when the request that failed rolled back. Never raises."""
    try:
        async with SessionLocal() as session:
            session.add(AppEvent(kind=kind, data=data or {}))
            await session.commit()
    except Exception:
        log.exception("Could not record %s event", kind)


async def last(session: AsyncSession, kind: str) -> AppEvent | None:
    return await session.scalar(select(AppEvent).where(AppEvent.kind == kind).order_by(AppEvent.id.desc()).limit(1))


async def count_since(session: AsyncSession, kind: str, days: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return await session.scalar(
        select(func.count()).select_from(AppEvent).where(AppEvent.kind == kind, AppEvent.created_at >= since))


async def prune(session: AsyncSession) -> None:
    await session.execute(delete(AppEvent).where(
        AppEvent.created_at < datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)))


async def prune_kind(session: AsyncSession, kind: str, keep: int) -> None:
    """Heartbeats arrive every few minutes; only the latest matter."""
    ids = list(await session.scalars(select(AppEvent.id).where(AppEvent.kind == kind)
                                     .order_by(AppEvent.id.desc()).offset(keep)))
    if ids:
        await session.execute(delete(AppEvent).where(AppEvent.id.in_(ids)))
