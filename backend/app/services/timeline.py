"""Timeline tracking: compare planned progress vs logged progress, and build replan proposals."""

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Activity, ActivityLink, DailyEntry, DailyReview, Goal, PlanItem, ReplanProposal, User
from app.services import commitment, prompts, roadmap, scheduler, scoring
from app.services.llm import LLMError, get_llm
from app.services.llm.outputs import ReplanDraft


@dataclass
class ItemProgressView:
    est_hours: float
    hours_logged: float
    status: str
    planned_start: date | None
    planned_due: date | None


@dataclass
class TimelineStatus:
    planned_hours: float
    done_hours: float
    behind_hours: float
    behind_days: float
    behind_pct: float
    overdue_items: int
    hours_per_day: float
    state: str  # on_track / behind / ahead / not_started
    threshold_days: int = 3

    def as_dict(self) -> dict:
        return asdict(self)


def planned_fraction(start: date | None, due: date | None, today: date) -> float:
    """How much of an item should be done by the end of `today` if it is on schedule."""
    if not start or not due:
        return 0.0
    if today < start:
        return 0.0
    if today >= due:
        return 1.0
    return ((today - start).days + 1) / ((due - start).days + 1)


def threshold_days(plan_length_days: int | None) -> int:
    """How far off plan counts as behind/ahead: ~5% of the plan's length, between 2 and 7 days."""
    if not plan_length_days:
        return 3
    return min(max(round(plan_length_days * 0.05), 2), 7)


def compute_status(items: list[ItemProgressView], today: date, hours_per_day: float,
                   baseline: dict | None = None) -> TimelineStatus:
    yesterday = today - timedelta(days=1)  # work scheduled for today isn't owed until the day is over
    done = sum(it.est_hours if it.status == "done" else min(it.hours_logged, it.est_hours)
               for it in items if it.status != "skipped")
    overdue = sum(1 for it in items
                  if it.status not in ("done", "skipped") and it.planned_due and it.planned_due < today)
    planned = roadmap.baseline_planned(baseline or {}, yesterday)
    if planned is not None:
        length = roadmap.baseline_length_days(baseline)
    else:  # no agreed baseline (dates edited by hand): assume each item's hours are spread over its dates
        planned = sum(it.est_hours * planned_fraction(it.planned_start, it.planned_due, yesterday)
                      for it in items if it.status != "skipped")
        dated = [it for it in items if it.planned_start and it.planned_due]
        length = ((max(i.planned_due for i in dated) - min(i.planned_start for i in dated)).days + 1
                  if dated else None)
    behind = planned - done
    behind_days = behind / hours_per_day if hours_per_day else 0.0
    pct = behind / planned if planned else 0.0
    threshold = threshold_days(length)
    if planned == 0 and done == 0:
        state = "not_started"
    elif behind_days >= threshold:
        state = "behind"
    elif -behind_days >= threshold:
        state = "ahead"
    else:
        state = "on_track"
    return TimelineStatus(
        round(planned, 1), round(done, 1), round(behind, 1), round(behind_days, 1), round(pct, 2), overdue,
        round(hours_per_day, 2), state, threshold,
    )


async def goal_status(session: AsyncSession, user: User, goal: Goal, today: date) -> TimelineStatus:
    hpd = await roadmap.goal_hours_per_day(session, user, goal)
    views = [
        ItemProgressView(i.est_hours, i.hours_logged, i.status, i.planned_start, i.planned_due)
        for i in roadmap.ordered_items(goal)
    ]
    return compute_status(views, today, hpd, goal.baseline)


DIAGNOSIS_DAYS = 14
PACE_DAYS = 21
MIN_HISTORY_DAYS = 7


async def diagnose(session: AsyncSession, user: User, goal: Goal, today: date, status: TimelineStatus) -> dict:
    """Why a goal is off plan, and when it will really finish at the user's actual recent pace."""
    created = goal.created_at if goal.created_at.tzinfo else goal.created_at.replace(tzinfo=timezone.utc)
    started = max(created.date(), today - timedelta(days=PACE_DAYS))
    history_days = (today - started).days

    window_start = today - timedelta(days=DIAGNOSIS_DAYS)
    plans = list(await session.scalars(select(PlanItem).where(
        PlanItem.user_id == user.id, PlanItem.goal_id == goal.id, PlanItem.date_for >= window_start,
        PlanItem.date_for < today)))
    adherence = scoring.plan_adherence([scoring.PlanBlock(p.status, p.minutes, p.done_minutes) for p in plans])

    logged = set(await session.scalars(select(DailyEntry.date).join(DailyReview).where(
        DailyEntry.user_id == user.id, DailyEntry.date >= window_start, DailyEntry.date < today)))
    missed = [d for n in range(1, DIAGNOSIS_DAYS + 1)
              if (d := today - timedelta(days=n)) >= created.date() and d not in logged
              and (commitment.routine_minutes_on(goal.routine, d) > 0 if goal.routine else True)]

    overruns = [{"id": i.id, "title": i.title, "est_hours": i.est_hours, "hours_logged": round(i.hours_logged, 1)}
                for i in roadmap.ordered_items(goal)
                if i.status in roadmap.OPEN_STATUSES and i.hours_logged >= i.est_hours]

    minutes = await session.scalar(
        select(func.coalesce(func.sum(Activity.minutes * ActivityLink.relevance), 0))
        .select_from(ActivityLink)
        .join(Activity, Activity.id == ActivityLink.activity_id)
        .join(DailyEntry, DailyEntry.id == Activity.entry_id)
        .where(DailyEntry.user_id == user.id, ActivityLink.goal_id == goal.id,
               DailyEntry.date >= started, DailyEntry.date < today))
    actual_weekly = (float(minutes) / 60) / history_days * 7 if history_days else 0.0
    planned_weekly = status.hours_per_day * 7
    remaining = sum(roadmap.remaining_hours(i) for i in roadmap.ordered_items(goal)
                    if i.status in roadmap.OPEN_STATUSES)

    forecast = None
    if history_days >= MIN_HISTORY_DAYS and actual_weekly > 0:
        forecast = today + timedelta(days=math.ceil(remaining / (actual_weekly / 7)))
    misses_target = bool(forecast and goal.target_date and forecast > goal.target_date)

    if history_days < MIN_HISTORY_DAYS:
        cause, suggestion = "too_early", "Too little history yet; check again after a week of logging."
    elif overruns:
        cause = "estimates_too_low"
        suggestion = ("Items are taking longer than estimated: ask what's left on each, re-estimate them "
                      "(update_roadmap_item with reschedule=True) and check the target still holds.")
    elif (adherence is not None and adherence < 0.6) or len(missed) >= 3 or (
            planned_weekly and actual_weekly < 0.6 * planned_weekly):
        cause = "routine_not_followed"
        suggestion = ("They're doing much less than the agreed routine: talk about what gets in the way, then agree "
                      "a smaller, realistic routine (confirm_commitment) and/or cut scope (reduce_scope) rather than "
                      "just pushing dates.")
    elif status.state == "behind" or misses_target:
        cause = "plan_too_tight"
        suggestion = ("They follow the routine but the plan is too tight: shift dates if the target is flexible, "
                      "otherwise reduce scope or add time blocks.")
    elif status.state == "ahead":
        cause = "ahead"
        suggestion = "They're ahead: offer an earlier target date or a stretch item."
    else:
        cause, suggestion = "on_track", "No action needed."

    return {
        "likely_cause": cause,
        "suggestion": suggestion,
        "plan_done_last_14_days": round(adherence, 2) if adherence is not None else None,
        "missed_working_days_last_14_days": len(missed),
        "items_over_estimate": overruns,
        "actual_hours_per_week": round(actual_weekly, 1),
        "planned_hours_per_week": round(planned_weekly, 1),
        "remaining_hours": round(remaining, 1),
        "forecast_finish_at_actual_pace": forecast.isoformat() if forecast else None,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "forecast_misses_target": misses_target,
    }


def alert(goal: Goal, status: TimelineStatus, diagnosis: dict) -> str | None:
    """One line worth telling the user after their review, or None."""
    if status.state == "behind":
        return (f"'{goal.title}' is {status.behind_days} days behind plan "
                f"(likely cause: {diagnosis['likely_cause'].replace('_', ' ')}).")
    if diagnosis["forecast_misses_target"]:
        return (f"'{goal.title}': at your actual pace ({diagnosis['actual_hours_per_week']}h/week) you'd finish "
                f"{diagnosis['forecast_finish_at_actual_pace']}, after the {diagnosis['target_date']} target.")
    if status.state == "ahead":
        return f"'{goal.title}' is {abs(status.behind_days)} days ahead of plan."
    return None


async def build_replan(
    session: AsyncSession, user: User, goal: Goal, status: TimelineStatus, today: date
) -> ReplanProposal | None:
    """Ask the LLM for a strategy (rule fallback: shift), then compute concrete dates with the scheduler."""
    open_items = [i for i in roadmap.ordered_items(goal) if i.status in roadmap.OPEN_STATUSES]
    if not open_items:
        return None

    reason = (
        f"You're about {status.behind_days} days behind; dates were moved to keep the plan realistic."
        if status.behind_days > 0
        else "Dates recalculated from today based on the work that's left."
    )
    draft = ReplanDraft(strategy="shift", reason=reason)
    llm = get_llm(user)
    if llm is not None:
        lines = [f"{i.id} | {i.title} | {i.est_hours}h | {i.hours_logged}h logged" for i in open_items]
        try:
            draft = await llm.complete_json(
                prompts.REPLAN_SYSTEM,
                prompts.replan_prompt(goal, status.as_dict(), lines, goal.context or {}),
                ReplanDraft,
            )
        except LLMError:
            pass

    return make_proposal(session, user, goal, status, draft, today)


def make_proposal(
    session: AsyncSession, user: User, goal: Goal, status: TimelineStatus, draft: ReplanDraft, today: date
) -> ReplanProposal | None:
    """Turn a chosen strategy into concrete new dates (pending until the user accepts)."""
    open_items = [i for i in roadmap.ordered_items(goal) if i.status in roadmap.OPEN_STATUSES]
    if not open_items:
        return None
    valid_ids = {i.id for i in open_items}
    skip_ids = {i for i in draft.skip_item_ids if i in valid_ids} if draft.strategy == "reduce_scope" else set()
    hpd = status.hours_per_day
    new_daily_available = None
    new_commitment_hours = None
    if draft.strategy == "increase_hours" and draft.new_goal_hours_per_day:
        if roadmap.has_commitment(goal):
            # For an agreed commitment the number means hours on a working day.
            if draft.new_goal_hours_per_day > goal.hours_per_day:
                new_commitment_hours = draft.new_goal_hours_per_day
                hpd = new_commitment_hours * goal.days_per_week / 7
        elif draft.new_goal_hours_per_day > hpd:
            extra = draft.new_goal_hours_per_day - hpd
            new_daily_available = round(user.daily_available_hours + extra, 2)
            hpd = draft.new_goal_hours_per_day

    capacity = (scheduler.even_pace(hpd) if new_daily_available or new_commitment_hours
                else roadmap.capacity_for(goal, hpd))
    mapping, finish = roadmap.compute_schedule(goal, today, capacity, skip_ids)
    changes = []
    for item in open_items:
        if item.id in skip_ids:
            changes.append({"item_id": item.id, "title": item.title, "action": "skip",
                            "old_due": _iso(item.planned_due), "new_due": None})
        elif item.id in mapping:
            slot = mapping[item.id]
            if slot.due != item.planned_due or slot.start != item.planned_start:
                changes.append({"item_id": item.id, "title": item.title, "action": "shift",
                                "old_due": _iso(item.planned_due), "new_due": slot.due.isoformat(),
                                "new_start": slot.start.isoformat()})
    proposal = ReplanProposal(
        goal_id=goal.id,
        reason=(draft.reason + (" " + draft.message if draft.message else "")).strip(),
        diff={
            "strategy": draft.strategy,
            "changes": changes,
            "new_finish_date": _iso(finish),
            "target_date": _iso(goal.target_date),
            "goal_hours_per_day": round(hpd, 2),
            "daily_available_hours": new_daily_available,
            "commitment_hours_per_day": new_commitment_hours,
            "status": status.as_dict(),
        },
    )
    session.add(proposal)
    return proposal


async def apply_replan(session: AsyncSession, user: User, goal: Goal, proposal: ReplanProposal, today: date) -> None:
    """Apply an accepted proposal: skip items / change hours, then re-date from today (same maths as the preview),
    which also makes it the new agreed baseline."""
    items = {i.id: i for i in roadmap.ordered_items(goal)}
    for change in proposal.diff.get("changes", []):
        if change["action"] == "skip" and (item := items.get(change["item_id"])) is not None:
            item.status = "skipped"
    if proposal.diff.get("daily_available_hours"):
        user.daily_available_hours = proposal.diff["daily_available_hours"]
    if proposal.diff.get("commitment_hours_per_day"):
        goal.hours_per_day = proposal.diff["commitment_hours_per_day"]
    await roadmap.reschedule(session, user, goal, today)
    proposal.status = "accepted"


async def pending_replan(session: AsyncSession, goal_id: int) -> ReplanProposal | None:
    return await session.scalar(
        select(ReplanProposal).where(ReplanProposal.goal_id == goal_id, ReplanProposal.status == "pending")
    )


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None
