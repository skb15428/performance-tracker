"""Which study topics a day should cover. Unfinished topics roll forward by themselves."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, RoadmapItem, StudyTopic, User
from app.services import roadmap

RETEST_MINUTES = 10
RETEST_SHARE = 0.3  # re-tests can't take more than this share of the day


@dataclass
class DayTopic:
    topic: StudyTopic
    mode: str  # retest/carryover/new
    minutes: int


def topic_minutes(topic: StudyTopic) -> int:
    """Time left on a topic: a topic with weak subtopics only needs those."""
    total = len(topic.concepts or []) or 1
    weak = len(topic.weak_concepts or [])
    if topic.status == "learning" and weak:
        return max(round(topic.est_minutes * weak / total), 15)
    return topic.est_minutes


def choose(topics: list[StudyTopic], day: date, minutes: int) -> list[DayTopic]:
    """Due re-tests first (capped), then planned and carried-over topics, then new ones until the time is used.
    `topics` must be in roadmap order. The next topic is always offered, even if it overruns the day."""
    picked: list[DayTopic] = []
    left = minutes

    budget = max(round(minutes * RETEST_SHARE), RETEST_MINUTES)
    for t in sorted((t for t in topics if t.status == "passed" and t.next_review_on and t.next_review_on <= day),
                    key=lambda t: t.next_review_on):
        if budget < RETEST_MINUTES:
            break
        picked.append(DayTopic(t, "retest", RETEST_MINUTES))
        budget -= RETEST_MINUTES
        left -= RETEST_MINUTES

    for t in topics:
        if t.status == "learning" or (t.status == "new" and t.planned_for and t.planned_for <= day):
            need = topic_minutes(t)
            picked.append(DayTopic(t, "carryover" if t.status == "learning" else "new", need))
            left -= need

    for t in topics:
        if left <= 0 and any(p.mode != "retest" for p in picked):
            break
        if t.status == "new" and not any(p.topic.id == t.id for p in picked):
            need = topic_minutes(t)
            picked.append(DayTopic(t, "new", need))
            left -= need
    return picked


async def goal_topics(session: AsyncSession, goal: Goal) -> list[StudyTopic]:
    """All the goal's topics in roadmap order, with off-plan topics first since the user chose them."""
    position = {i.id: n for n, i in enumerate(roadmap.ordered_items(goal))}
    rows = list(await session.scalars(select(StudyTopic).where(StudyTopic.goal_id == goal.id).order_by(StudyTopic.order)))
    return sorted(rows, key=lambda t: (position.get(t.roadmap_item_id, -1), t.order, t.id))


async def day_topics(session: AsyncSession, user: User, goals: list[Goal], day: date) -> list[tuple[Goal, DayTopic]]:
    out = []
    for g in goals:
        minutes = await roadmap.goal_target_minutes(session, user, g, day)
        if minutes > 0 or any(t.planned_for == day for t in await goal_topics(session, g)):
            out += [(g, dt) for dt in choose(await goal_topics(session, g), day, minutes)]
    return out


async def item_topics(session: AsyncSession, item_id: int) -> list[StudyTopic]:
    return list(await session.scalars(
        select(StudyTopic).where(StudyTopic.roadmap_item_id == item_id).order_by(StudyTopic.order)))


async def unpassed_count(session: AsyncSession, item_id: int) -> int:
    return sum(1 for t in await item_topics(session, item_id) if t.status != "passed")


async def sync_item(session: AsyncSession, item: RoadmapItem, day: date) -> bool:
    """An interview-proven item is done exactly when all its topics have passed. Returns True if it just finished."""
    rows = await item_topics(session, item.id)
    if not rows:
        return False
    if all(t.status == "passed" for t in rows):
        finished = item.status != "done"
        item.status, item.completed_at = "done", item.completed_at or day
        return finished
    if item.status == "done":
        item.status, item.completed_at = "in_progress", None
    elif item.status == "todo":
        item.status = "in_progress"
    return False


async def topics_due_soon(session: AsyncSession, user: User) -> list[StudyTopic]:
    rows = await session.scalars(
        select(StudyTopic).join(Goal).where(Goal.user_id == user.id, or_(StudyTopic.status != "passed",
                                                                          StudyTopic.next_review_on.is_not(None))))
    return list(rows)
