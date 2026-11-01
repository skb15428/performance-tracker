"""Which study topics a day should cover. Unfinished topics roll forward by themselves."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, RoadmapItem, StudyTopic, User
from app.services import roadmap

RETEST_MINUTES = 10
RETEST_SHARE = 0.3  # re-tests can't take more than this share of the day
UPCOMING_DAYS = 7  # working days shown ahead
UPCOMING_LOOKAHEAD = 30  # calendar days searched for them


@dataclass
class DayTopic:
    topic: StudyTopic
    mode: str  # retest/carryover/new
    minutes: int


@dataclass
class UpcomingDay:
    day: date
    minutes: int
    topics: list[tuple[Goal, DayTopic]]


def topic_minutes(topic: StudyTopic) -> int:
    """Time left on a topic: a topic with weak subtopics only needs those."""
    total = len(topic.concepts or []) or 1
    weak = len(topic.weak_concepts or [])
    if topic.status == "learning" and weak:
        return max(round(topic.est_minutes * weak / total), 15)
    if topic.status == "new" and topic.understood:
        return max(round(topic.est_minutes * (total - len(topic.understood)) / total), 15)
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


def background_due(goal: Goal) -> RoadmapItem | None:
    """The next roadmap step, if it's a study step nobody has checked the user's background for."""
    for item in roadmap.ordered_items(goal):
        if item.status in roadmap.OPEN_STATUSES:
            return item if item.proof == "interview" and item.background is None else None
    return None


async def topic_path(session: AsyncSession, goal: Goal, topic: StudyTopic) -> dict:
    """Where a topic sits in its roadmap step: what came before it, and what it leads to."""
    rows = [t for t in await goal_topics(session, goal) if t.roadmap_item_id == topic.roadmap_item_id]
    at = next(n for n, t in enumerate(rows) if t.id == topic.id)
    return {"position": at + 1, "of": len(rows),
            "before": [{"title": t.title, "status": t.status, "subtopics": [c["name"] for c in t.concepts]}
                       for t in rows[:at]],
            "after": [t.title for t in rows[at + 1:]]}


def reachable(goal: Goal, rows: list[StudyTopic]) -> list[StudyTopic]:
    """The topics that can come up now. A new topic waits for the roadmap to reach its step, so a project or an
    unprepared step ahead of it isn't skipped; topics already started, chosen or off-plan are always in."""
    prepared = {t.roadmap_item_id for t in rows}
    reached: set[int] = set()
    for item in roadmap.ordered_items(goal):
        if item.status in roadmap.OPEN_STATUSES:
            if item.proof != "interview" or item.id not in prepared:
                break
            reached.add(item.id)
    return [t for t in rows if t.status != "new" or t.planned_for or t.roadmap_item_id is None
            or t.roadmap_item_id in reached]


async def day_topics(session: AsyncSession, user: User, goals: list[Goal], day: date) -> list[tuple[Goal, DayTopic]]:
    out = []
    for g in goals:
        minutes = await roadmap.goal_target_minutes(session, user, g, day)
        rows = await goal_topics(session, g)
        if minutes > 0 or any(t.planned_for == day for t in rows):
            out += [(g, dt) for dt in choose(reachable(g, rows), day, minutes)]
    return out


async def is_rest_day(session: AsyncSession, user: User, goals: list[Goal], day: date) -> bool:
    """No goal has time planned. A session the user adds for themselves doesn't change that."""
    return bool(goals) and not any([await roadmap.goal_target_minutes(session, user, g, day) for g in goals])


async def upcoming_days(session: AsyncSession, user: User, goals: list[Goal], today: date,
                        count: int = UPCOMING_DAYS) -> list[UpcomingDay]:
    """A forecast of the next working days, each taking the next topics as if the days before it went to plan.
    A topic that overruns its day eats into the next one, which keeps these dates in step with the roadmap's."""
    pools = {g.id: reachable(g, await goal_topics(session, g)) for g in goals}
    taken = {p.topic.id for _, p in await day_topics(session, user, goals, today)}
    overrun = dict.fromkeys(pools, 0)
    days: list[UpcomingDay] = []
    for offset in range(1, UPCOMING_LOOKAHEAD + 1):
        d = today + timedelta(days=offset)
        picked: list[tuple[Goal, DayTopic]] = []
        total = 0
        for g in goals:
            minutes = await roadmap.goal_target_minutes(session, user, g, d)
            total += minutes
            left = minutes - overrun[g.id]
            if left <= 0:  # a rest day, or the whole day goes on finishing the last topic
                overrun[g.id] -= minutes
                continue
            chosen = choose([t for t in pools[g.id] if t.id not in taken], d, left)
            overrun[g.id] = max(sum(p.minutes for p in chosen) - left, 0)
            taken |= {p.topic.id for p in chosen}
            picked += [(g, p) for p in chosen]
        if picked:
            days.append(UpcomingDay(d, total, picked))
        if len(days) == count:
            break
    return days


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
