"""Exporting and restoring everything a user has. Secrets (password, tokens) are never part of an export."""

import base64
import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models import User

EXPORT_VERSION = 1
SECRET_COLUMNS = {"hashed_password", "gemini_key_enc", "calendar_token", "failed_logins", "locked_until"}
OWNED = (  # parents before children, so a restore can run in this order
    models.Goal, models.RoadmapPhase, models.RoadmapItem, models.StudyTopic, models.TopicNote, models.InterviewSession,
    models.GoalMetric, models.MetricEntry, models.DailyEntry, models.Activity, models.ActivityLink, models.DailyReview, models.PlanItem,
    models.TimeLog, models.WeekPlan, models.WeeklyReview, models.ReplanProposal, models.JobApplication,
)


def _row(obj) -> dict:
    out = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.key)
        if column.key in SECRET_COLUMNS:
            continue
        if isinstance(value, (dt.date, dt.datetime)):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, bytes):
            value = base64.b64encode(value).decode()
        out[column.key] = value
    return out


async def _owned_rows(session: AsyncSession, user: User) -> dict[str, list]:
    goals = list(await session.scalars(select(models.Goal.id).where(models.Goal.user_id == user.id)))
    entries = list(await session.scalars(select(models.DailyEntry.id).where(models.DailyEntry.user_id == user.id)))
    phases = list(await session.scalars(select(models.RoadmapPhase.id).where(models.RoadmapPhase.goal_id.in_(goals))))
    topics = list(await session.scalars(select(models.StudyTopic.id).where(models.StudyTopic.goal_id.in_(goals))))
    metrics = list(await session.scalars(select(models.GoalMetric.id).where(models.GoalMetric.goal_id.in_(goals))))
    activities = list(await session.scalars(select(models.Activity.id).where(models.Activity.entry_id.in_(entries))))
    filters = {
        models.Goal: models.Goal.user_id == user.id,
        models.RoadmapPhase: models.RoadmapPhase.goal_id.in_(goals),
        models.RoadmapItem: models.RoadmapItem.phase_id.in_(phases),
        models.StudyTopic: models.StudyTopic.goal_id.in_(goals),
        models.TopicNote: models.TopicNote.goal_id.in_(goals),
        models.InterviewSession: models.InterviewSession.topic_id.in_(topics),
        models.GoalMetric: models.GoalMetric.goal_id.in_(goals),
        models.MetricEntry: models.MetricEntry.metric_id.in_(metrics),
        models.DailyEntry: models.DailyEntry.user_id == user.id,
        models.Activity: models.Activity.entry_id.in_(entries),
        models.ActivityLink: models.ActivityLink.activity_id.in_(activities),
        models.DailyReview: models.DailyReview.entry_id.in_(entries),
        models.PlanItem: models.PlanItem.user_id == user.id,
        models.TimeLog: models.TimeLog.user_id == user.id,
        models.WeekPlan: models.WeekPlan.goal_id.in_(goals),
        models.WeeklyReview: models.WeeklyReview.user_id == user.id,
        models.ReplanProposal: models.ReplanProposal.goal_id.in_(goals),
        models.JobApplication: models.JobApplication.user_id == user.id,
    }
    return {m.__tablename__: list(await session.scalars(select(m).where(filters[m]).order_by(m.id))) for m in OWNED}


async def export_user(session: AsyncSession, user: User) -> dict:
    tables = await _owned_rows(session, user)
    return {"version": EXPORT_VERSION, "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(), "user": _row(user),
            "tables": {name: [_row(obj) for obj in rows] for name, rows in tables.items()}}


def _parse(model, row: dict, user_id: uuid.UUID) -> dict:
    out = {}
    for column in model.__table__.columns:
        if column.key not in row:
            continue
        value = row[column.key]
        if column.key == "user_id":
            value = user_id
        elif value is not None and isinstance(column.type, DateTime):
            value = dt.datetime.fromisoformat(value)
        elif value is not None and isinstance(column.type, Date):
            value = dt.date.fromisoformat(value)
        elif value is not None and isinstance(column.type, Boolean):
            value = bool(value)
        out[column.key] = value
    return out


async def restore_user(session: AsyncSession, user: User, export: dict) -> dict[str, int]:
    """Put an export back into an empty account. Refuses to mix with existing data."""
    if await session.scalar(select(models.Goal.id).where(models.Goal.user_id == user.id).limit(1)) is not None:
        raise ValueError("This account already has goals. Restore into an empty account.")
    counts = {}
    for model in OWNED:
        rows = export["tables"].get(model.__tablename__, [])
        for row in rows:
            session.add(model(**_parse(model, row, user.id)))
        await session.flush()
        counts[model.__tablename__] = len(rows)
    return counts
