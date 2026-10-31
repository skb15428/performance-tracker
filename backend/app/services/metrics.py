"""Measurable targets for goals, such as body weight or applications sent: is the number on course for the target date?
Targets with a `source` count themselves from the job search and the proof page; the others are logged by hand."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, GoalMetric, JobApplication, MetricEntry, RoadmapItem, RoadmapPhase

SOURCES = ("applications", "final_rounds", "offers", "proof_links")

# How far off the straight line from start to target still counts as on track (share of the total change).
TOLERANCE = 0.1


def metric_status(start_value: float, target_value: float, start_date: date, target_date: date | None,
                  latest_value: float | None, today: date) -> dict:
    """Compare the latest value with where a straight line from start to target says it should be today."""
    change = target_value - start_value
    done = (latest_value - start_value) / change if latest_value is not None and change else 0.0
    progress_pct = round(min(max(done, 0), 1) * 100, 1)
    if latest_value is None:
        return {"state": "no_data", "progress_pct": 0.0, "expected_value": None}
    if not target_date or target_date <= start_date:
        return {"state": "no_target_date", "progress_pct": progress_pct, "expected_value": None}
    elapsed = min(max((today - start_date).days / (target_date - start_date).days, 0), 1)
    state = "behind" if done < elapsed - TOLERANCE else "ahead" if done > elapsed + TOLERANCE else "on_track"
    return {"state": state, "progress_pct": progress_pct, "expected_value": round(start_value + change * elapsed, 2)}


async def counted_value(session: AsyncSession, goal: Goal, source: str) -> float:
    """The live count behind a target with a source."""
    if source == "proof_links":
        rows = await session.scalars(select(RoadmapItem.proof_links).join(RoadmapPhase)
                                     .where(RoadmapPhase.goal_id == goal.id))
        return float(sum(len(links or []) for links in rows))
    jobs = select(func.count()).select_from(JobApplication).where(JobApplication.user_id == goal.user_id)
    if source == "applications":
        jobs = jobs.where(JobApplication.stage != "saved")
    elif source == "final_rounds":
        jobs = jobs.where(JobApplication.reached_final.is_(True))
    else:
        jobs = jobs.where(JobApplication.stage == "offer")
    return float(await session.scalar(jobs))


async def metric_row(session: AsyncSession, goal: Goal, metric: GoalMetric, today: date) -> dict:
    entries = list(await session.scalars(
        select(MetricEntry).where(MetricEntry.metric_id == metric.id).order_by(MetricEntry.day)))
    latest = entries[-1].value if entries else None
    if metric.source:
        latest = await counted_value(session, goal, metric.source)
    return {"metric_id": metric.id, "id": metric.id, "name": metric.name, "unit": metric.unit,
            "start_value": metric.start_value, "target_value": metric.target_value, "start_date": metric.start_date,
            "source": metric.source, "latest_value": latest, "entries": [{"day": e.day, "value": e.value} for e in entries],
            **metric_status(metric.start_value, metric.target_value, metric.start_date, goal.target_date, latest, today)}


async def goal_metrics(session: AsyncSession, goal: Goal, today: date) -> list[dict]:
    rows = await session.scalars(select(GoalMetric).where(GoalMetric.goal_id == goal.id).order_by(GoalMetric.id))
    return [await metric_row(session, goal, m, today) for m in rows]
