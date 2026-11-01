"""Read-only views of study topics, interview results and metrics for the Study page and dashboard."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Goal, GoalMetric, InterviewSession, MetricEntry, StudyTopic, User
from app.schemas import MetricIn, MetricLogIn
from app.services import analysis, metrics, notes, roadmap
from app.services import topics as study
from app.services.push import local_now

router = APIRouter(prefix="/study", tags=["study"])
WEAKEST_SHOWN = 8


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
        "rest_day": await study.is_rest_day(session, user, goals, d),
        "topics": rows, "interviews": [session_out(s, title) for s, title in interviews],
        "tested_today": sorted(done_ids),
    }


@router.get("/upcoming")
async def upcoming(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """What's ahead: the next working days topic by topic, then every open roadmap step, prepared or not."""
    today = local_now(user.timezone).date()
    goals = await analysis.tracked_goals(session, user)
    days = await study.upcoming_days(session, user, goals, today)
    steps = []
    for g in goals:
        by_item: dict[int | None, list[StudyTopic]] = {}
        for t in await study.goal_topics(session, g):
            by_item.setdefault(t.roadmap_item_id, []).append(t)
        for i in roadmap.ordered_items(g):
            if i.status in roadmap.OPEN_STATUSES:
                rows = by_item.get(i.id, [])
                steps.append({"id": i.id, "goal": g.title, "title": i.title, "proof": i.proof, "status": i.status,
                              "planned_start": i.planned_start, "planned_due": i.planned_due,
                              "est_hours": i.est_hours, "topics": [topic_out(t) for t in rows],
                              "needs_topics": i.proof == "interview" and not rows})
    return {
        "days": [{"date": u.day, "minutes": u.minutes,
                  "topics": [{**topic_out(p.topic), "goal": g.title, "mode": p.mode, "minutes": p.minutes}
                             for g, p in u.topics]} for u in days],
        "steps": steps,
    }


@router.get("/topics/{topic_id}")
async def topic_detail(topic_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    topic = await session.scalar(select(StudyTopic).join(Goal).where(StudyTopic.id == topic_id, Goal.user_id == user.id))
    if topic is None:
        raise HTTPException(404, "Topic not found")
    sessions = await session.scalars(
        select(InterviewSession).where(InterviewSession.topic_id == topic.id).order_by(InterviewSession.id.desc()))
    note = await notes.for_topic(session, topic.id)
    return {**topic_out(topic), "note_id": note.id if note else None, "sessions": [session_out(s) for s in sessions]}


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
    return {"items": items, "metrics": await metrics.goal_metrics(session, goal, today)}


async def owned_metric(session: AsyncSession, metric_id: int, user: User) -> GoalMetric:
    metric = await session.scalar(select(GoalMetric).join(Goal).where(GoalMetric.id == metric_id, Goal.user_id == user.id))
    if metric is None:
        raise HTTPException(404, "Target not found")
    return metric


@router.post("/goals/{goal_id}/metrics", status_code=201)
async def add_metric(goal_id: int, body: MetricIn, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    goal = await roadmap.load_goal(session, goal_id, user.id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    today = local_now(user.timezone).date()
    metric = GoalMetric(goal_id=goal.id, start_date=today, **body.model_dump())
    session.add(metric)
    await session.flush()
    row = await metrics.metric_row(session, goal, metric, today)
    await session.commit()
    return row


@router.post("/metrics/{metric_id}/log")
async def log_metric(metric_id: int, body: MetricLogIn, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    """Record a reading, or add 1 to a count when no value is given."""
    metric = await owned_metric(session, metric_id, user)
    if metric.source:
        raise HTTPException(400, "This target counts itself")
    goal = await session.get(Goal, metric.goal_id)
    day = body.day or local_now(user.timezone).date()
    latest = await session.scalar(select(MetricEntry).where(MetricEntry.metric_id == metric.id)
                                  .order_by(MetricEntry.day.desc(), MetricEntry.id.desc()).limit(1))
    value = body.value if body.value is not None else (latest.value if latest else metric.start_value) + 1
    entry = await session.scalar(select(MetricEntry).where(MetricEntry.metric_id == metric.id, MetricEntry.day == day))
    if entry is None:
        session.add(MetricEntry(metric_id=metric.id, day=day, value=value))
    else:
        entry.value = value
    await session.flush()
    goal = await roadmap.load_goal(session, goal.id, user.id)
    row = await metrics.metric_row(session, goal, metric, day)
    await session.commit()
    return row


@router.delete("/metrics/{metric_id}", status_code=204)
async def delete_metric(metric_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await session.delete(await owned_metric(session, metric_id, user))
    await session.commit()


@router.get("/readiness")
async def readiness(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """How ready you are to be interviewed: topics proven, what's weakest across everything, and what's unprepared."""
    today = local_now(user.timezone).date()
    goals = await analysis.tracked_goals(session, user)
    rows, weak, due = [], [], 0
    unprepared = 0
    for g in goals:
        topics = await study.goal_topics(session, g)
        by_item: dict[int | None, list[StudyTopic]] = {}
        for t in topics:
            by_item.setdefault(t.roadmap_item_id, []).append(t)
            due += bool(t.status == "passed" and t.next_review_on and t.next_review_on <= today)
            for name in t.weak_concepts or []:
                weak.append({"concept": name, "topic": t.title, "topic_id": t.id,
                             "score": (t.concept_scores or {}).get(name)})
        for item in roadmap.ordered_items(g):
            if item.proof != "interview" or item.status == "skipped":
                continue
            mine = by_item.get(item.id, [])
            unprepared += not mine
            rows.append({"id": item.id, "title": item.title, "passed": sum(t.status == "passed" for t in mine),
                         "total": len(mine), "planned_due": item.planned_due})
    total = sum(r["total"] for r in rows)
    passed = sum(r["passed"] for r in rows)
    weak.sort(key=lambda w: w["score"] if w["score"] is not None else 5)
    return {"passed": passed, "total": total, "pct": round(100 * passed / total) if total else None,
            "items": rows, "weakest": weak[:WEAKEST_SHOWN], "retests_due": due, "unprepared_items": unprepared}


@router.get("/proof")
async def proof(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """What you can show for your work: finished steps, their links and the topics you've proven."""
    rows = []
    for g in await analysis.tracked_goals(session, user):
        for phase in g.phases:
            for i in phase.items:
                passed = [t.title for t in await study.item_topics(session, i.id) if t.status == "passed"]
                if i.status == "done" or i.proof_links or passed:
                    rows.append({"id": i.id, "goal": g.title, "title": i.title, "status": i.status,
                                 "completed_at": i.completed_at, "links": i.proof_links or [], "passed_topics": passed})
    return {"items": rows}
