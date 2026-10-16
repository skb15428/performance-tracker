"""Weekly review: aggregate stats, then let the LLM (or a template) write the narrative."""

from datetime import date, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Activity,
    ActivityLink,
    DailyEntry,
    DailyReview,
    Goal,
    PlanItem,
    RoadmapItem,
    RoadmapPhase,
    TrendSuggestion,
    User,
    WeeklyReview,
)
from app.services import prompts, roadmap, scoring, timeline
from app.services.analysis import load_goals_with_items
from app.services.llm import LLMError, get_llm
from app.services.llm.outputs import WeeklyText


def week_start_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PATTERN_DAYS = 28


def time_of_day(time_block: str) -> str | None:
    try:
        hour = int(time_block.split("-")[0].split(":")[0])
    except (ValueError, IndexError):
        return None
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"


def pct(done: float, total: float) -> float | None:
    return round(done / total, 2) if total else None


async def week_basics(session: AsyncSession, user: User, start: date, today: date) -> dict:
    """Headline numbers for one week (up to today if it's the current week)."""
    end = min(start + timedelta(days=6), today)
    reviews = list(await session.execute(
        select(DailyReview.total_score).join(DailyEntry)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end), DailyReview.rest_day.is_(False))))
    plans = list(await session.scalars(select(PlanItem).where(
        PlanItem.user_id == user.id, PlanItem.date_for.between(start, end))))
    hours = await session.scalar(
        select(func.coalesce(func.sum(Activity.minutes * ActivityLink.relevance), 0)).select_from(ActivityLink)
        .join(Activity, Activity.id == ActivityLink.activity_id).join(DailyEntry, DailyEntry.id == Activity.entry_id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end)))
    scores = [float(r.total_score) for r in reviews]
    adherence = scoring.plan_adherence([scoring.PlanBlock(p.status, p.minutes, p.done_minutes) for p in plans])
    return {"week_start": start.isoformat(), "days_scored": len(scores),
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
    today = today or date.today()
    end = start + timedelta(days=6)
    goals = await load_goals_with_items(session, user)

    reviews = list(await session.execute(
        select(DailyEntry.date, DailyReview.total_score, DailyReview.adherence, DailyReview.drift_minutes,
               DailyReview.rest_day)
        .join(DailyReview, DailyReview.entry_id == DailyEntry.id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end))
        .order_by(DailyEntry.date)
    ))
    minutes_rows = await session.execute(
        select(ActivityLink.goal_id, func.sum(Activity.minutes * ActivityLink.relevance))
        .join(Activity, Activity.id == ActivityLink.activity_id)
        .join(DailyEntry, DailyEntry.id == Activity.entry_id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end))
        .group_by(ActivityLink.goal_id)
    )
    minutes = {gid: float(m or 0) for gid, m in minutes_rows}
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

    previous_review = await session.scalar(select(WeeklyReview).where(
        WeeklyReview.user_id == user.id, WeeklyReview.week_start == start - timedelta(days=7)))
    trend = [await week_basics(session, user, start - timedelta(days=7 * n), today) for n in range(3, -1, -1)]
    return {
        "week_start": start.isoformat(),
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

    wins = []
    best = max(stats["daily_scores"], key=lambda d: d["score"], default=None)
    if best and best["score"] >= 50:
        wins.append(f"Best day: {best['date']} (score {round(best['score'])})")
    wins += [f"Completed: {t}" for g in goals for t in g["completed_items"]][:4]
    if stats["plan_items"] and stats["plan_done"] / stats["plan_items"] >= 0.7:
        wins.append(f"Followed your plan: {stats['plan_done']}/{stats['plan_items']} blocks done")

    return WeeklyText(
        summary=f"You logged {stats['days_logged']}/7 days with an average score of {stats['avg_score'] or 0}. "
                f"Effort split: {dist}.",
        wins=wins,
        gaps=[f"No time on '{t}' this week" for t in neglected] + [f"'{t}' is behind schedule" for t in behind],
        recommendations=["Log every night - consistency compounds."]
        + [f"Block at least 3 focused sessions for '{t}' next week" for t in (neglected + behind)[:3]],
    )


async def generate(session: AsyncSession, user: User, start: date) -> WeeklyReview:
    stats = await week_stats(session, user, start)
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
