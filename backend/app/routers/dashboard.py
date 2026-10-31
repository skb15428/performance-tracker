from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import DailyEntry, DailyReview, TrendSuggestion, User
from app.routers.goals import goal_out
from app.services import metrics, push, roadmap, timeline, timelogs, weekly
from app.services.analysis import daily_targets, load_goals_with_items, plan_for, streak_before
from app.services.push import local_now
from app.services.timeline import planned_fraction
from app.services.weekly import week_start_of

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
WEEKS_CHARTED = 8


@router.get("/summary")
async def summary(days: int = 30, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    today = local_now(user.timezone).date()  # the user's day, not the server's (UTC on Render)
    start = today - timedelta(days=days - 1)
    heat_start = today - timedelta(days=125)
    goals = goals_all = await load_goals_with_items(session, user)

    reviews = list(await session.execute(
        select(DailyEntry.date, DailyReview.total_score, DailyReview.adherence, DailyReview.per_goal,
               DailyReview.went_well, DailyReview.went_badly, DailyReview.tip, DailyReview.rest_day,
               DailyReview.breakdown)
        .join(DailyReview, DailyReview.entry_id == DailyEntry.id)
        .where(DailyEntry.user_id == user.id, DailyEntry.date >= heat_start)
        .order_by(DailyEntry.date)
    ))
    worked = await timelogs.worked_minutes(session, user.id, heat_start - timedelta(weeks=52), today)

    weekly_minutes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    daily_goal_hours: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    day_minutes: dict[date, float] = defaultdict(float)
    for (d, gid), mins in worked.items():
        daily_goal_hours[gid][d] += mins / 60
        day_minutes[d] += mins
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
            card["alert"] = timeline.alert(g, st, dx)
            card["insight"] = {k: dx[k] for k in ("likely_cause", "actual_hours_per_week", "planned_hours_per_week",
                                                  "forecast_finish_at_actual_pace", "forecast_misses_target",
                                                  "target_date")}
        goal_cards.append(card)

    scored = [r for r in reviews if not r.rest_day]  # rest days aren't scored and don't count in averages
    latest = scored[-1] if scored else None
    await push.todays_plan(session, user, today, create=True)  # today always has a plan, even without a review
    today_plan = await plan_for(session, user.id, today)
    new_trends = await session.scalar(
        select(func.count()).select_from(TrendSuggestion)
        .where(TrendSuggestion.user_id == user.id, TrendSuggestion.status == "new")
    )
    adherence = [r.adherence for r in scored if r.date >= start and r.adherence is not None]
    logged_today = bool(latest and latest.date == today)
    # Mon-Sun strip for this week: what each day was/is. A day with no work only counts as missed if the week is behind.
    tracked = [g for g in goals_all if g.intake_status == "active"]
    by_day = {r.date: r for r in reviews}
    week_from = week_start_of(today)
    this_week = await weekly.week_score(session, user, week_from, today)
    started = min((weekly.goal_start(user, g) for g in tracked), default=today)
    async def days_of(monday: date, week: dict | None) -> list[dict]:
        out = []
        for n in range(7):
            d = monday + timedelta(days=n)
            target = sum((await daily_targets(session, user, tracked, d)).values())
            r = by_day.get(d)
            minutes = week["minutes_by_day"][d.isoformat()] if week else 0
            if not target:
                state = "bonus" if minutes else "rest"
            elif minutes or (r is not None and not r.rest_day):
                state = "done"
            elif d < started:
                state = "before"
            elif d >= today:
                state = "today" if d == today else "upcoming"
            else:
                state = "covered" if week["ahead_hours"] >= 0 else "missed"
            kind, per_goal = await roadmap.day_types(session, user, d)
            out.append({"date": d.isoformat(), "state": state, "is_today": d == today, "minutes": minutes,
                        "planned_minutes": sum(p.minutes for p in await plan_for(session, user.id, d)
                                               if p.status != "skipped") or target,
                        "day_type": kind, "goal_day_types": per_goal,
                        "usual": any([await roadmap.usual_minutes(session, user, g, d) for g in tracked])})
        return out

    week = await days_of(week_from, this_week)
    next_week = await days_of(week_from + timedelta(days=7), None)
    week_scores = []
    for n in range(WEEKS_CHARTED - 1, -1, -1):
        monday = week_from - timedelta(weeks=n)
        if monday + timedelta(days=6) >= started:
            past = await weekly.week_score(session, user, monday, today)
            if past["score"] is not None:
                week_scores.append({"week": monday.isoformat(), "score": past["score"]})

    attention = [line for g in goal_cards if (line := g.pop("alert", None))]
    quiet = await push.days_since_logged(session, user, today)
    if quiet is not None and quiet >= push.QUIET_DAYS:
        attention.insert(0, f"Nothing logged for {quiet} days. Add your time below, or catch up with Claude.")
    scorecard = [{"goal": g.title, **{k: m[k] for k in ("id", "name", "unit", "target_value", "start_value",
                                                        "latest_value", "progress_pct", "state", "source")}}
                 for g in tracked for m in await metrics.goal_metrics(session, g, today)]

    result = {
        "today": today.isoformat(),
        "reviewed_today": today in by_day,
        "this_week": this_week,
        "week": week,
        "next_week": next_week,
        "week_scores": week_scores,
        "attention": attention,
        "scorecard": scorecard,
        "heatmap": [{"date": d.isoformat(), "minutes": round(day_minutes.get(d, 0)),
                     "rest": d in by_day and by_day[d].rest_day and not day_minutes.get(d)}
                    for d in sorted({*by_day, *day_minutes}) if d >= heat_start],
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
                        "goal_id": p.goal_id, "roadmap_item_id": p.roadmap_item_id, "status": p.status,
                        "done_minutes": p.done_minutes, "details": p.details or {}} for p in today_plan],
        "new_trends": new_trends or 0,
        "weekly_focus": await weekly.current_focus(session, user, today),
    }
    await session.commit()  # today's new plan and finished weeks are worth keeping
    return result
