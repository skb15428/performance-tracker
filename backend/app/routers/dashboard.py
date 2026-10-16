from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Activity, ActivityLink, DailyEntry, DailyReview, TrendSuggestion, User
from app.routers.goals import goal_out
from app.services import roadmap, timeline, weekly
from app.services.analysis import load_goals_with_items, plan_for, streak_before
from app.services.timeline import planned_fraction
from app.services.weekly import week_start_of

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary(days: int = 30, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    today = date.today()
    start = today - timedelta(days=days - 1)
    heat_start = today - timedelta(days=125)
    goals = await load_goals_with_items(session, user)

    reviews = list(await session.execute(
        select(DailyEntry.date, DailyReview.total_score, DailyReview.adherence, DailyReview.per_goal,
               DailyReview.went_well, DailyReview.went_badly, DailyReview.tip, DailyReview.rest_day,
               DailyReview.breakdown)
        .join(DailyReview, DailyReview.entry_id == DailyEntry.id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date >= heat_start)
        .order_by(DailyEntry.date)
    ))
    minutes_rows = list(await session.execute(
        select(DailyEntry.date, ActivityLink.goal_id, func.sum(Activity.minutes * ActivityLink.relevance))
        .join(Activity, Activity.entry_id == DailyEntry.id)
        .join(ActivityLink, ActivityLink.activity_id == Activity.id)
        .where(DailyEntry.user_id == user.id)
        .group_by(DailyEntry.date, ActivityLink.goal_id)
    ))

    weekly_minutes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    daily_goal_hours: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for d, gid, mins in minutes_rows:
        mins = float(mins or 0)
        daily_goal_hours[gid][d] += mins / 60
        if d >= today - timedelta(weeks=8):
            weekly_minutes[week_start_of(d).isoformat()][str(gid)] += round(mins)

    goal_cards = []
    for g in goals:
        items = [i for i in roadmap.ordered_items(g) if i.status != "skipped"]
        series = []
        for offset in range(days):
            d = start + timedelta(days=offset)
            if g.baseline.get("points") is not None:  # the agreed plan, from the day it was agreed
                bl_start = date.fromisoformat(g.baseline["start"])
                planned = roadmap.baseline_planned(g.baseline, d) if d >= bl_start else None
            else:
                planned = sum(i.est_hours * planned_fraction(i.planned_start, i.planned_due, d) for i in items)
            actual = sum(h for day, h in daily_goal_hours[g.id].items() if day <= d)
            series.append({"date": d.isoformat(), "planned": round(planned, 1) if planned is not None else None,
                           "actual": round(actual, 1)})
        out = await goal_out(session, user, g)
        card = {**out.model_dump(mode="json"), "burnup": series}
        if g.intake_status == "active":
            st = await timeline.goal_status(session, user, g, today)
            dx = await timeline.diagnose(session, user, g, today, st)
            card["insight"] = {k: dx[k] for k in ("likely_cause", "actual_hours_per_week", "planned_hours_per_week",
                                                  "forecast_finish_at_actual_pace", "forecast_misses_target",
                                                  "target_date")}
        goal_cards.append(card)

    scored = [r for r in reviews if not r.rest_day]  # rest days aren't scored and don't count in averages
    latest = scored[-1] if scored else None
    today_plan = await plan_for(session, user.id, today)
    new_trends = await session.scalar(
        select(func.count()).select_from(TrendSuggestion)
        .where(TrendSuggestion.user_id == user.id, TrendSuggestion.status == "new")
    )
    adherence = [r.adherence for r in scored if r.date >= start and r.adherence is not None]
    logged_today = bool(latest and latest.date == today)
    return {
        "scores": [{"date": r.date.isoformat(), "score": r.total_score} for r in scored if r.date >= start],
        "heatmap": [{"date": r.date.isoformat(), "score": r.total_score, "rest": r.rest_day} for r in reviews],
        "weekly_effort": [{"week": w, **v} for w, v in sorted(weekly_minutes.items())],
        "goals": goal_cards,
        "latest": {
            "date": latest.date.isoformat(), "score": latest.total_score,
            "per_goal": {k: v for k, v in latest.per_goal.items() if not k.startswith("_")},
            "went_well": latest.went_well, "went_badly": latest.went_badly, "tip": latest.tip,
            "explanation": (latest.breakdown or {}).get("explanation"),
        } if latest else None,
        "streak": await streak_before(session, user.id, today) + (1 if logged_today else 0),
        "adherence_avg": round(sum(adherence) / len(adherence), 2) if adherence else None,
        "today_plan": [{"id": p.id, "title": p.title, "time_block": p.time_block, "minutes": p.minutes,
                        "goal_id": p.goal_id, "status": p.status} for p in today_plan],
        "new_trends": new_trends or 0,
        "weekly_focus": await weekly.current_focus(session, user, today),
    }
