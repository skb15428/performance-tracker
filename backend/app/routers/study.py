"""Read-only views of study topics, interview results and metrics for the Study page and dashboard."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Goal, GoalMetric, InterviewSession, MetricEntry, StudyTopic, User
from app.services import analysis, roadmap
from app.services import topics as study
from app.services.metrics import metric_status
from app.services.push import local_now

router = APIRouter(prefix="/study", tags=["study"])


def topic_out(t: StudyTopic) -> dict:
    return {"id": t.id, "goal_id": t.goal_id, "roadmap_item_id": t.roadmap_item_id, "title": t.title,
            "concepts": t.concepts, "est_minutes": t.est_minutes, "status": t.status, "source": t.source,
            "attempts": t.attempts, "best_pct": t.best_pct, "last_pct": t.last_pct,
            "concept_scores": t.concept_scores, "weak_concepts": t.weak_concepts,
            "passed_on": t.passed_on, "next_review_on": t.next_review_on}


def session_out(s: InterviewSession, title: str | None = None) -> dict:
    return {"id": s.id, "topic_id": s.topic_id, "topic": title, "day": s.day, "kind": s.kind, "minutes": s.minutes,
            "overall_pct": s.overall_pct, "passed": s.passed, "concept_scores": s.concept_scores,
            "weak_concepts": s.weak_concepts, "questions": s.questions}


@router.get("/today")
async def today_topics(day: date | None = None, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    d = day or local_now(user.timezone).date()
    goals = await analysis.tracked_goals(session, user)
    picked = await study.day_topics(session, user, goals, d)
    interviews = list(await session.execute(
        select(InterviewSession, StudyTopic.title).join(StudyTopic).join(Goal)
        .where(Goal.user_id == user.id, InterviewSession.day == d).order_by(InterviewSession.id)))
    done_ids = {s.topic_id for s, _ in interviews}
    rows = [{**topic_out(p.topic), "goal": g.title, "mode": p.mode, "minutes": p.minutes} for g, p in picked]
    for s, _ in interviews:  # a topic passed today leaves the queue but still belongs on today's page
        if s.topic_id not in {r["id"] for r in rows}:
            t = await session.get(StudyTopic, s.topic_id)
            goal = await session.get(Goal, t.goal_id)
            rows.append({**topic_out(t), "goal": goal.title, "mode": "done", "minutes": 0})
    return {
        "date": d, "available_minutes": sum([await roadmap.goal_target_minutes(session, user, g, d) for g in goals]),
        "topics": rows, "interviews": [session_out(s, title) for s, title in interviews],
        "tested_today": sorted(done_ids),
    }


@router.get("/topics/{topic_id}")
async def topic_detail(topic_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    topic = await session.scalar(select(StudyTopic).join(Goal).where(StudyTopic.id == topic_id, Goal.user_id == user.id))
    if topic is None:
        raise HTTPException(404, "Topic not found")
    sessions = await session.scalars(
        select(InterviewSession).where(InterviewSession.topic_id == topic.id).order_by(InterviewSession.id.desc()))
    return {**topic_out(topic), "sessions": [session_out(s) for s in sessions]}


@router.get("/goals/{goal_id}")
async def goal_study(goal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Topics per roadmap item and the goal's measurable targets."""
    goal = await roadmap.load_goal(session, goal_id, user.id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    today = local_now(user.timezone).date()
    items = {}
    for t in await study.goal_topics(session, goal):
        row = items.setdefault(str(t.roadmap_item_id or "offplan"), {"passed": 0, "total": 0})
        row["total"] += 1
        row["passed"] += t.status == "passed"
    metrics = []
    for m in await session.scalars(select(GoalMetric).where(GoalMetric.goal_id == goal.id)):
        entries = list(await session.scalars(select(MetricEntry).where(MetricEntry.metric_id == m.id).order_by(MetricEntry.day)))
        latest = entries[-1].value if entries else None
        metrics.append({"id": m.id, "name": m.name, "unit": m.unit, "start_value": m.start_value,
                        "target_value": m.target_value, "start_date": m.start_date, "latest_value": latest,
                        "entries": [{"day": e.day, "value": e.value} for e in entries],
                        **metric_status(m.start_value, m.target_value, m.start_date, goal.target_date, latest, today)})
    return {"items": items, "metrics": metrics}
