"""Time spent on goals as it happens: blocks marked done, the focus timer, interviews and manual entries.

Each log credits its roadmap item straight away. Claude's nightly review can cover the same work, so anything counting
hours takes the larger of the two for a day rather than adding them.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Activity, ActivityLink, DailyEntry, PlanItem, RoadmapItem, TimeLog, User


async def _credit(session: AsyncSession, item_id: int | None, minutes: int) -> None:
    item = await session.get(RoadmapItem, item_id) if item_id is not None else None
    if item is None:
        return
    item.hours_logged = max(item.hours_logged + minutes / 60, 0)
    if item.status == "todo" and minutes > 0:
        item.status = "in_progress"


async def add(session: AsyncSession, user: User, day: date, goal_id: int, minutes: int, item_id: int | None = None,
              note: str = "", source: str = "manual", plan_item_id: int | None = None) -> TimeLog:
    log = TimeLog(user_id=user.id, day=day, goal_id=goal_id, roadmap_item_id=item_id, plan_item_id=plan_item_id,
                  minutes=minutes, note=note, source=source)
    session.add(log)
    await _credit(session, item_id, minutes)
    await session.flush()
    return log


async def remove(session: AsyncSession, log: TimeLog) -> None:
    await _credit(session, log.roadmap_item_id, -log.minutes)
    await session.delete(log)
    await session.flush()


async def for_day(session: AsyncSession, user_id, day: date) -> list[TimeLog]:
    return list(await session.scalars(
        select(TimeLog).where(TimeLog.user_id == user_id, TimeLog.day == day).order_by(TimeLog.id)))


async def item_minutes(session: AsyncSession, user_id, day: date, item_id: int, skip_source: str | None = None) -> int:
    """Minutes already credited to this roadmap item on this day."""
    query = select(func.coalesce(func.sum(TimeLog.minutes), 0)).where(
        TimeLog.user_id == user_id, TimeLog.day == day, TimeLog.roadmap_item_id == item_id)
    if skip_source:
        query = query.where(TimeLog.source != skip_source)
    return await session.scalar(query)


async def sync_block(session: AsyncSession, user: User, block: PlanItem) -> None:
    """Keep a plan block's logged time in step with its status. Marking it done or partly done logs the time, and
    undoing that takes it back. Time already logged for the same step that day, such as an interview, isn't added."""
    existing = await session.scalar(select(TimeLog).where(TimeLog.plan_item_id == block.id))
    if existing is not None:
        await remove(session, existing)
    minutes = {"done": block.done_minutes or block.minutes, "partial": block.done_minutes or 0}.get(block.status, 0)
    if not minutes or block.goal_id is None:
        return
    if block.roadmap_item_id is not None:
        minutes -= await item_minutes(session, user.id, block.date_for, block.roadmap_item_id)
    if minutes > 0:
        await add(session, user, block.date_for, block.goal_id, minutes, block.roadmap_item_id, block.title, "block",
                  block.id)


async def logged_minutes(session: AsyncSession, user_id, start: date, end: date) -> dict[tuple[date, int], int]:
    """{(day, goal_id): minutes} logged in the app or by interviews."""
    rows = await session.execute(
        select(TimeLog.day, TimeLog.goal_id, func.sum(TimeLog.minutes))
        .where(TimeLog.user_id == user_id, TimeLog.day.between(start, end)).group_by(TimeLog.day, TimeLog.goal_id))
    return {(d, gid): int(m or 0) for d, gid, m in rows}


async def worked_minutes(session: AsyncSession, user_id, start: date, end: date) -> dict[tuple[date, int], float]:
    """{(day, goal_id): minutes} from every source, counting each day's overlap between reviews and logs once."""
    reviewed = await session.execute(
        select(DailyEntry.date, ActivityLink.goal_id, func.sum(Activity.minutes * ActivityLink.relevance))
        .select_from(ActivityLink).join(Activity, Activity.id == ActivityLink.activity_id)
        .join(DailyEntry, DailyEntry.id == Activity.entry_id)
        .where(DailyEntry.user_id == user_id, DailyEntry.date.between(start, end))
        .group_by(DailyEntry.date, ActivityLink.goal_id))
    worked: dict[tuple[date, int], float] = {(d, gid): float(m or 0) for d, gid, m in reviewed}
    for key, minutes in (await logged_minutes(session, user_id, start, end)).items():
        worked[key] = max(worked.get(key, 0.0), float(minutes))
    return worked
