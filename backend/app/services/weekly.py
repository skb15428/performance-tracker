"""Weekly review: aggregate stats, then let the LLM (or a template) write the narrative."""

from datetime import date, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import (
    Activity,
    DailyEntry,
    DailyReview,
    Goal,
    InterviewSession,
    PlanItem,
    RoadmapItem,
    RoadmapPhase,
    StudyTopic,
    TrendSuggestion,
    User,
    WeeklyReview,
    WeekPlan,
)
from app.services import metrics, prompts, roadmap, scoring, timeline, timelogs
from app.services.analysis import load_goals_with_items, tracked_goals
from app.services.llm import LLMError, get_llm
from app.services.llm.outputs import WeeklyText
from app.services.push import local_now


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PATTERN_DAYS = 28
METRIC_MARKS = {"ahead": 10.0, "on_track": 8.0, "behind": 3.0}  # a measurable target's state, as a 0-10 quality mark


def time_of_day(time_block: str) -> str | None:
    try:
        hour = int(time_block.split("-")[0].split(":")[0])
    except (ValueError, IndexError):
        return None
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"


def pct(done: float, total: float) -> float | None:
    return round(done / total, 2) if total else None


def goal_start(user: User, goal: Goal) -> date:
    """The user's local date the goal started; nothing was expected before it."""
    created = goal.created_at if goal.created_at.tzinfo else goal.created_at.replace(tzinfo=timezone.utc)
    return local_now(user.timezone, created).date()


async def frozen_minutes(session: AsyncSession, user: User, goal: Goal, start: date, today: date) -> dict[str, int]:
    """The routine's minutes per day for this week. Once a week is over they're kept, so changing the routine later
    can't rewrite its score."""
    saved = await session.scalar(select(WeekPlan).where(WeekPlan.goal_id == goal.id, WeekPlan.week_start == start))
    if saved is not None:
        return saved.minutes
    days = [start + timedelta(days=n) for n in range(7)]
    minutes = {d.isoformat(): await roadmap.usual_minutes(session, user, goal, d) for d in days}
    if days[-1] < today:
        session.add(WeekPlan(goal_id=goal.id, week_start=start, minutes=minutes))
        await session.flush()
    return minutes


async def freeze_past_weeks(session: AsyncSession, user: User, goal: Goal, today: date) -> None:
    """Keep every finished week as it was. Call before changing a routine."""
    start = week_start_of(goal_start(user, goal))
    while start + timedelta(days=6) < today:
        await frozen_minutes(session, user, goal, start, today)
        start += timedelta(days=7)


def is_log_goal(goal: Goal) -> bool:
    """Fitness and habit goals are judged on sessions done: a 45-minute run in a one-hour slot still counts as a run."""
    items = [i for i in roadmap.ordered_items(goal) if i.status != "skipped"]
    return bool(items) and all(i.proof == "log" for i in items)


async def week_goals(session: AsyncSession, user: User, start: date) -> list[Goal]:
    """Goals tracked now, plus any that counted that week and have since been paused or finished."""
    goals = await tracked_goals(session, user)
    past = await session.scalars(
        select(Goal).join(WeekPlan, WeekPlan.goal_id == Goal.id)
        .where(Goal.user_id == user.id, WeekPlan.week_start == start, Goal.id.not_in([g.id for g in goals]))
        .options(selectinload(Goal.phases).selectinload(RoadmapPhase.items)))
    return goals + list(past)


async def week_score(session: AsyncSession, user: User, start: date, today: date) -> dict:
    """One week's score, so far while it's running. Only the week's total hours matter, so any split across days is
    fine. A marked rest day takes its hours off the target; a marked work day can't raise it above the routine's total,
    so offering extra time is never a bigger bar to clear. Today counts once it's reviewed or its time is in."""
    days = [start + timedelta(days=n) for n in range(7)]
    end = days[-1]
    goals = await week_goals(session, user, start)
    reviews = {d: (per_goal, breakdown) for d, per_goal, breakdown in await session.execute(
        select(DailyEntry.date, DailyReview.per_goal, DailyReview.breakdown).join(DailyReview)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end)))}
    logged = await timelogs.logged_minutes(session, user.id, start, end)
    types = {d: (kind, per_goal or {}) for d, kind, per_goal in await session.execute(
        select(DailyEntry.date, DailyEntry.day_type, DailyEntry.goal_day_types)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end)))}

    by_day = dict.fromkeys(days, 0.0)
    rows, inputs = [], []
    for g in goals:
        first = goal_start(user, g)
        usual = await frozen_minutes(session, user, g, start, today)
        working_day = await roadmap.working_day_minutes(session, user, g)
        targets = {}
        for d in days:
            kind, per_goal = types.get(d, (None, {}))
            targets[d] = roadmap.adjusted_minutes(usual.get(d.isoformat(), 0), per_goal.get(str(g.id), kind), working_day)
        active = [d for d in days if d >= first]
        full = min(sum(usual.get(d.isoformat(), 0) for d in active), sum(targets[d] for d in active))
        counted = rated = rated_minutes = sessions = 0.0
        worked_today = 0.0
        log_goal = is_log_goal(g)
        for d in days:
            row = reviews[d][0].get(str(g.id), {}) if d in reviews else {}
            minutes = row.get("minutes", 0)
            unreviewed = max(logged.get((d, g.id), 0) - minutes, 0)  # in the app, but no review has covered it
            worked = minutes + unreviewed
            by_day[d] += worked
            if d == today:
                worked_today = worked
            if log_goal:
                sessions += worked > 0
                counted += (targets[d] or working_day) if worked else 0
            else:
                counted += row.get("counted_minutes", 0) + unreviewed
            if row.get("llm") is not None and minutes:
                rated += row["llm"] * minutes
                rated_minutes += minutes
        so_far = min(full, sum(targets[d] for d in active if d < today or (
            d == today and (d in reviews or worked_today >= targets[d]))))
        quality = rated / rated_minutes if rated_minutes else None
        states = [m["state"] for m in await metrics.goal_metrics(session, g, min(end, today))]
        marks = [METRIC_MARKS[s] for s in states if s in METRIC_MARKS]
        if marks:  # a measurable target going the right way is part of how good the week was
            mark = sum(marks) / len(marks)
            quality = mark if quality is None else (quality + mark) / 2
        inputs.append(scoring.WeekGoal(g.id, g.priority, so_far, counted, quality))
        row = {"goal_id": g.id, "title": g.title, "hours_done": round(counted / 60, 1),
               "hours_target": round(full / 60, 1), "quality": round(quality, 1) if quality is not None else None}
        if log_goal and working_day:
            row |= {"sessions_done": int(sessions), "sessions_target": round(full / working_day)}
        rows.append(row)

    value = value_minutes = waste = 0.0
    for per_goal, breakdown in reviews.values():
        waste += breakdown.get("waste_minutes") or 0
        spent = sum(v.get("minutes", 0) for k, v in per_goal.items() if not k.startswith("_"))
        if breakdown.get("time_value") is not None and spent:
            value += breakdown["time_value"] * spent
            value_minutes += spent
    result = scoring.score_week(inputs, value / value_minutes if value_minutes else None, round(waste),
                                get_settings().llm_weight)
    done = sum(g.counted_minutes for g in inputs)
    expected = sum(g.target_minutes for g in inputs)
    return {
        "week_start": start.isoformat(), "final": end < today,
        "score": result.total if result else None, "explanation": result.explanation if result else None,
        "hours_pct": result.hours_pct if result else None, "quality": result.quality if result else None,
        "hours_done": round(done / 60, 1), "hours_target": round(sum(r["hours_target"] for r in rows), 1),
        "hours_expected_so_far": round(expected / 60, 1), "ahead_hours": round((done - expected) / 60, 1),
        "rest_days_marked": sum(1 for kind, _ in types.values() if kind == "rest"), "goals": rows,
        "minutes_by_day": {d.isoformat(): round(m) for d, m in by_day.items()},
    }


async def week_basics(session: AsyncSession, user: User, start: date, today: date) -> dict:
    """Headline numbers for one week (up to today if it's the current week)."""
    end = min(start + timedelta(days=6), today)
    reviews = list(await session.execute(
        select(DailyReview.total_score).join(DailyEntry)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end), DailyReview.rest_day.is_(False))))
    plans = list(await session.scalars(select(PlanItem).where(
        PlanItem.user_id == user.id, PlanItem.date_for.between(start, end))))
    hours = sum((await timelogs.worked_minutes(session, user.id, start, end)).values())
    scores = [float(r.total_score) for r in reviews]
    adherence = scoring.plan_adherence([scoring.PlanBlock(p.status, p.minutes, p.done_minutes) for p in plans])
    return {"week_start": start.isoformat(), "days_scored": len(scores),
            "score": (await week_score(session, user, start, today))["score"],
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "plan_done_pct": round(adherence, 2) if adherence is not None else None,
            "goal_hours": round(float(hours) / 60, 1)}


async def patterns(session: AsyncSession, user: User, end: date, today: date) -> dict:
    """Last 4 weeks: when planned blocks get done, best/worst days, energy vs score, wasted time by weekday."""
    last = min(end, today - timedelta(days=1))  # today isn't over yet
    first = last - timedelta(days=PATTERN_DAYS - 1)
    plans = list(await session.scalars(select(PlanItem).where(
        PlanItem.user_id == user.id, PlanItem.date_for.between(first, last))))
    by_day: dict[str, list] = {}
    by_time: dict[str, list] = {}
    for p in plans:
        block = scoring.PlanBlock(p.status, p.minutes, p.done_minutes)
        by_day.setdefault(WEEKDAY_NAMES[p.date_for.weekday()], []).append(block)
        if (tod := time_of_day(p.time_block)) is not None:
            by_time.setdefault(tod, []).append(block)

    days = list(await session.execute(
        select(DailyEntry.date, DailyEntry.energy, DailyReview.total_score).join(DailyReview)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(first, last),
               DailyReview.rest_day.is_(False))))
    score_by_day: dict[str, list[float]] = {}
    by_energy: dict[str, list[float]] = {}
    for d, energy, score in days:
        score_by_day.setdefault(WEEKDAY_NAMES[d.weekday()], []).append(float(score))
        if energy:
            by_energy.setdefault("low (1-2)" if energy <= 2 else "medium (3)" if energy == 3 else "high (4-5)",
                                 []).append(float(score))

    waste_rows = await session.execute(
        select(DailyEntry.date, func.sum(Activity.minutes)).join(Activity, Activity.entry_id == DailyEntry.id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(first, last), Activity.kind == "waste")
        .group_by(DailyEntry.date))
    waste_by_day: dict[str, int] = {}
    for d, mins in waste_rows:
        waste_by_day[WEEKDAY_NAMES[d.weekday()]] = waste_by_day.get(WEEKDAY_NAMES[d.weekday()], 0) + int(mins or 0)

    def adherence_map(groups: dict[str, list]) -> dict:
        return {k: round(a, 2) for k, v in groups.items() if len(v) >= 2
                and (a := scoring.plan_adherence(v)) is not None}

    avg_by_day = {k: round(sum(v) / len(v), 1) for k, v in score_by_day.items()}
    return {
        "window": f"{first.isoformat()} to {last.isoformat()}",
        "plan_done_by_weekday": {d: v for d in WEEKDAY_NAMES if (v := adherence_map(by_day).get(d)) is not None},
        "plan_done_by_time_of_day": adherence_map(by_time),
        "avg_score_by_weekday": {d: avg_by_day[d] for d in WEEKDAY_NAMES if d in avg_by_day},
        "avg_score_by_energy": {k: round(sum(v) / len(v), 1) for k, v in by_energy.items()},
        "wasted_minutes_by_weekday": {d: waste_by_day[d] for d in WEEKDAY_NAMES if d in waste_by_day},
    }


async def week_stats(session: AsyncSession, user: User, start: date, today: date | None = None) -> dict:
    today = today or local_now(user.timezone).date()
    end = start + timedelta(days=6)
    goals = await load_goals_with_items(session, user)

    reviews = list(await session.execute(
        select(DailyEntry.date, DailyReview.total_score, DailyReview.adherence, DailyReview.drift_minutes,
               DailyReview.rest_day)
        .join(DailyReview, DailyReview.entry_id == DailyEntry.id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end))
        .order_by(DailyEntry.date)
    ))
    minutes: dict[int, float] = {}
    for (_, gid), m in (await timelogs.worked_minutes(session, user.id, start, end)).items():
        minutes[gid] = minutes.get(gid, 0) + m
    completed_rows = await session.execute(
        select(Goal.id, RoadmapItem.title)
        .join(RoadmapPhase, RoadmapPhase.goal_id == Goal.id)
        .join(RoadmapItem, RoadmapItem.phase_id == RoadmapPhase.id)
        .where(Goal.user_id == user.id, RoadmapItem.completed_at.between(start, end))
    )
    completed: dict[int, list[str]] = {}
    for gid, title in completed_rows:
        completed.setdefault(gid, []).append(title)
    plan_rows = list(await session.scalars(
        select(PlanItem.status).where(PlanItem.user_id == user.id,
                                      PlanItem.date_for.between(start, min(end, today)))
    ))
    adopted = await session.scalar(
        select(func.count()).select_from(TrendSuggestion)
        .where(TrendSuggestion.user_id == user.id, TrendSuggestion.status == "added_to_roadmap",
               func.date(TrendSuggestion.created_at).between(start, end))
    )

    elapsed = [start + timedelta(days=n) for n in range(7) if start + timedelta(days=n) <= today]
    per_goal = []
    for g in goals:
        st = await timeline.goal_status(session, user, g, min(end, today))
        committed = sum([await roadmap.goal_target_minutes(session, user, g, d) for d in elapsed]) / 60
        hours = minutes.get(g.id, 0) / 60
        per_goal.append({"goal_id": g.id, "title": g.title, "minutes": round(minutes.get(g.id, 0)),
                         "hours": round(hours, 1), "committed_hours": round(committed, 1),
                         "pct_of_commitment": pct(hours, committed),
                         "completed_items": completed.get(g.id, []), "timeline": st.state,
                         "behind_days": st.behind_days})
    scored = [r for r in reviews if not r.rest_day]
    scores = [float(r.total_score) for r in scored]

    interviews = list(await session.scalars(
        select(InterviewSession).join(StudyTopic).join(Goal)
        .where(Goal.user_id == user.id, InterviewSession.day.between(start, end))))
    study = {"topics_passed": sum(1 for s in interviews if s.passed and s.kind == "first"),
             "topics_not_passed_yet": sum(1 for s in interviews if not s.passed and s.kind == "first"),
             "retests_held": sum(1 for s in interviews if s.passed and s.kind == "retest"),
             "retests_lost": sum(1 for s in interviews if not s.passed and s.kind == "retest"),
             "average_pct": round(sum(s.overall_pct for s in interviews) / len(interviews), 1) if interviews else None}

    previous_review = await session.scalar(select(WeeklyReview).where(
        WeeklyReview.user_id == user.id, WeeklyReview.week_start == start - timedelta(days=7)))
    trend = [await week_basics(session, user, start - timedelta(days=7 * n), today) for n in range(3, -1, -1)]
    return {
        "week_start": start.isoformat(),
        "week_score": await week_score(session, user, start, today),
        "days_logged": len(scored),
        "rest_days": [r.date.isoformat() for r in reviews if r.rest_day],
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "daily_scores": [{"date": r.date.isoformat(), "score": r.total_score} for r in scored],
        "drift_minutes": sum(r.drift_minutes for r in reviews),
        "plan_items": len(plan_rows),
        "plan_done": sum(1 for s in plan_rows if s == "done"),
        "plan_partial": sum(1 for s in plan_rows if s == "partial"),
        "trends_adopted": adopted or 0,
        "goals": per_goal,
        "study": study,
        "previous_week": trend[-2],
        "last_4_weeks": trend,
        "patterns_last_4_weeks": await patterns(session, user, end, today),
        "last_week_focus": previous_review.focus if previous_review else [],
    }


def template_text(stats: dict) -> WeeklyText:
    goals = stats["goals"]
    total = sum(g["minutes"] for g in goals) or 1
    dist = ", ".join(f"{g['title']}: {round(100 * g['minutes'] / total)}%" for g in goals)
    neglected = [g["title"] for g in goals if g["minutes"] == 0]
    behind = [g["title"] for g in goals if g["timeline"] == "behind"]

    wins = [f"Completed: {t}" for g in goals for t in g["completed_items"]][:4]
    if stats["plan_items"] and stats["plan_done"] / stats["plan_items"] >= 0.7:
        wins.append(f"Followed your plan: {stats['plan_done']}/{stats['plan_items']} blocks done")

    week = stats["week_score"]
    return WeeklyText(
        summary=f"You did {week['hours_done']}h of {week['hours_target']}h for a week score of {week['score'] or 0}. "
                f"Effort split: {dist}.",
        wins=wins,
        gaps=[f"No time on '{t}' this week" for t in neglected] + [f"'{t}' is behind schedule" for t in behind],
        recommendations=["Log every night - consistency compounds."]
        + [f"Block at least 3 focused sessions for '{t}' next week" for t in (neglected + behind)[:3]],
    )


async def generate(session: AsyncSession, user: User, start: date, today: date | None = None) -> WeeklyReview:
    stats = await week_stats(session, user, start, today)
    text = template_text(stats)
    llm = get_llm(user)
    if llm is not None and stats["days_logged"]:
        try:
            text = await llm.complete_json(prompts.WEEKLY_SYSTEM, f"WEEK STATS:\n{stats}", WeeklyText)
        except LLMError:
            pass
    review = await session.scalar(
        select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.week_start == start)
    )
    if review is None:
        review = WeeklyReview(user_id=user.id, week_start=start)
        session.add(review)
    review.stats, review.summary = stats, text.summary
    review.wins, review.gaps, review.recommendations = text.wins, text.gaps, text.recommendations
    await session.flush()
    return review


async def current_focus(session: AsyncSession, user: User, today: date) -> list[str]:
    """Focus points from the most recent weekly review written in the last 10 days."""
    recent = await session.scalars(
        select(WeeklyReview).where(WeeklyReview.user_id == user.id).order_by(WeeklyReview.created_at.desc()).limit(3))
    review = next((r for r in recent if r.focus), None)  # filtered here: Postgres can't compare JSON values
    if review is None:
        return []
    created = review.created_at if review.created_at.tzinfo else review.created_at.replace(tzinfo=timezone.utc)
    if (today - created.date()).days > 10:
        return []
    return [f["text"] for f in review.focus]
