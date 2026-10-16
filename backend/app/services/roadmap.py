"""Roadmap persistence + glue between DB rows and the pure scheduler."""

import bisect

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Goal, RoadmapItem, RoadmapPhase, User
from app.services import commitment, scheduler
from app.services.llm.outputs import RoadmapDraft

OPEN_STATUSES = ("todo", "in_progress")


async def active_goals(session: AsyncSession, user_id: uuid.UUID) -> list[Goal]:
    rows = await session.scalars(
        select(Goal).where(Goal.user_id == user_id, Goal.status == "active").order_by(Goal.priority.desc(), Goal.id)
    )
    return list(rows)


def has_commitment(goal: Goal) -> bool:
    return bool(goal.hours_per_day and goal.days_per_week)


async def goal_hours_per_day(session: AsyncSession, user: User, goal: Goal) -> float:
    """Pace in hours per calendar day, used for dates and timeline tracking.

    Uses the agreed commitment (hours/day x days/week / 7). Goals without one share whatever daily time is left,
    split by priority.
    """
    if has_commitment(goal):
        return goal.hours_per_day * goal.days_per_week / 7
    goals = [g for g in await active_goals(session, user.id) if g.intake_status == "active" or g.id == goal.id]
    committed = sum(g.hours_per_day * g.days_per_week / 7 for g in goals if has_commitment(g))
    priorities = [g.priority for g in goals if not has_commitment(g) and g.id != goal.id] + [goal.priority]
    budget = max(user.daily_available_hours - committed, 0.25)
    return scheduler.goal_hours_per_day(budget, goal.priority, priorities)


async def goal_target_minutes(session: AsyncSession, user: User, goal: Goal, day: date) -> int:
    """How many minutes the user planned to spend on this goal on `day` (0 on a routine rest day)."""
    if goal.routine:
        return commitment.routine_minutes_on(goal.routine, day)
    if has_commitment(goal):
        return round(goal.hours_per_day * 60)
    return round(await goal_hours_per_day(session, user, goal) * 60)


async def load_goal(session: AsyncSession, goal_id: int, user_id: uuid.UUID) -> Goal | None:
    return await session.scalar(
        select(Goal)
        .where(Goal.id == goal_id, Goal.user_id == user_id)
        .options(selectinload(Goal.phases).selectinload(RoadmapPhase.items))
    )


def ordered_items(goal: Goal) -> list[RoadmapItem]:
    return [item for phase in goal.phases for item in phase.items]


def remaining_hours(item: RoadmapItem) -> float:
    return max(item.est_hours - item.hours_logged, 0.5)


def capacity_for(goal: Goal, hours_per_day: float) -> scheduler.CapacityFn:
    """The goal's agreed weekly routine, or an even daily pace if it has none yet."""
    if goal.routine:
        return commitment.routine_capacity(goal.routine)
    return scheduler.even_pace(hours_per_day)


def compute_schedule(
    goal: Goal, start: date, capacity: scheduler.CapacityFn, skip_ids: set[int] | frozenset = frozenset(),
    daily: dict[date, int] | None = None,
) -> tuple[dict[int, scheduler.ScheduledSlot], date | None]:
    """Schedule all open items (minus skip_ids) from `start`. Returns {item_id: slot} and the finish date."""
    items = [
        scheduler.SchedItem(i.id, p_idx, i.type, remaining_hours(i))
        for p_idx, phase in enumerate(goal.phases)
        for i in phase.items
        if i.status in OPEN_STATUSES and i.id not in skip_ids
    ]
    if not items:
        return {}, None
    return scheduler.simulate(items, start, capacity, daily)


def finish_with_extra(goal: Goal, start: date, capacity: scheduler.CapacityFn, extra_hours: float,
                      extra_type: str = "topic") -> tuple[date | None, date | None]:
    """(finish now, finish if an item of `extra_hours` is inserted right after the current item). Saves nothing."""
    items = [
        scheduler.SchedItem(i.id, p_idx, i.type, remaining_hours(i))
        for p_idx, phase in enumerate(goal.phases)
        for i in phase.items
        if i.status in OPEN_STATUSES
    ]
    _, before = scheduler.simulate(items, start, capacity) if items else ({}, None)
    extra = scheduler.SchedItem(-1, items[0].phase if items else 0, extra_type, extra_hours)
    _, after = scheduler.simulate(items[:1] + [extra] + items[1:], start, capacity)
    return before, after


def done_hours(goal: Goal) -> float:
    """Progress in hours: finished items count in full, others count logged hours up to their estimate."""
    return sum(i.est_hours if i.status == "done" else min(i.hours_logged, i.est_hours)
               for i in ordered_items(goal) if i.status != "skipped")


def make_baseline(start: date, daily: dict[date, int], done_at_start: float) -> dict:
    cum, points = 0.0, []
    for d in sorted(daily):
        cum += daily[d] / 60
        points.append([d.isoformat(), round(cum, 3)])
    return {"start": start.isoformat(), "done_at_start": round(done_at_start, 3), "points": points}


def baseline_planned(baseline: dict, day: date) -> float | None:
    """Hours the agreed plan expected to be done by the end of `day` (None if there's no baseline)."""
    if not baseline or "points" not in baseline:
        return None
    key = day.isoformat()
    idx = bisect.bisect_right([p[0] for p in baseline["points"]], key)
    return baseline["done_at_start"] + (baseline["points"][idx - 1][1] if idx else 0.0)


def baseline_length_days(baseline: dict) -> int | None:
    if not baseline or not baseline.get("points"):
        return None
    return (date.fromisoformat(baseline["points"][-1][0]) - date.fromisoformat(baseline["start"])).days + 1


def apply_schedule(goal: Goal, mapping: dict[int, scheduler.ScheduledSlot]) -> None:
    for phase in goal.phases:
        for item in phase.items:
            if item.id in mapping:
                item.planned_start = mapping[item.id].start
                item.planned_due = mapping[item.id].due
        dated = [i for i in phase.items if i.planned_start and i.planned_due]
        if dated:
            phase.start_date = min(i.planned_start for i in dated)
            phase.due_date = max(i.planned_due for i in dated)


async def materialize_roadmap(session: AsyncSession, goal: Goal, draft: RoadmapDraft) -> None:
    """Replace the goal's roadmap with the drafted phases/items."""
    for phase in list(goal.phases):
        await session.delete(phase)
    await session.flush()
    goal.phases.clear()
    for p_idx, p in enumerate(draft.phases):
        phase = RoadmapPhase(title=p.title, order=p_idx)
        phase.items = [
            RoadmapItem(
                order=i_idx,
                type=it.type,
                title=it.title,
                description=it.description,
                est_hours=it.est_hours,
                resources=[r.model_dump() for r in it.resources],
                source="ai",
            )
            for i_idx, it in enumerate(p.items)
        ]
        goal.phases.append(phase)
    await session.flush()


async def reschedule(session: AsyncSession, user: User, goal: Goal, start: date) -> scheduler.Feasibility:
    """Re-date open items from `start` and make this the agreed plan (baseline) that progress is measured against."""
    hpd = await goal_hours_per_day(session, user, goal)
    daily: dict[date, int] = {}
    mapping, finish = compute_schedule(goal, start, capacity_for(goal, hpd), daily=daily)
    apply_schedule(goal, mapping)
    goal.baseline = make_baseline(start, daily, done_hours(goal))
    total = sum(remaining_hours(i) for i in ordered_items(goal) if i.status in OPEN_STATUSES)
    return scheduler.feasibility(total, start, finish, goal.target_date)


async def approve_draft(
    session: AsyncSession, user: User, goal: Goal, draft: RoadmapDraft, target_date: date | None, today: date,
    activate: bool = True,
) -> scheduler.Feasibility:
    """Replace the roadmap with `draft`, keep progress on items that survive (matched by title), and schedule it."""
    kept = {i.title.strip().lower(): (i.hours_logged, i.status, i.completed_at)
            for i in ordered_items(goal) if i.hours_logged or i.status != "todo"}
    await materialize_roadmap(session, goal, draft)
    for item in ordered_items(goal):
        if (prev := kept.get(item.title.strip().lower())) is not None:
            item.hours_logged, item.status, item.completed_at = prev
    if target_date:
        goal.target_date = target_date
    if activate:
        goal.intake_status = "active"
    goal.proposed_roadmap = None
    return await reschedule(session, user, goal, today)


def insert_after_current(goal: Goal, item: RoadmapItem) -> None:
    """Insert `item` right after the first unfinished item so it gets scheduled soon."""
    for phase in goal.phases:
        for idx, existing in enumerate(phase.items):
            if existing.status in OPEN_STATUSES:
                phase.items.insert(idx + 1, item)
                for order, it in enumerate(phase.items):
                    it.order = order
                return
    if not goal.phases:
        goal.phases.append(RoadmapPhase(title="Extras", order=0, items=[]))
    phase = goal.phases[-1]
    item.order = len(phase.items)
    phase.items.append(item)
