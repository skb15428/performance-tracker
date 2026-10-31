"""Logging time straight from the app, without waiting for a review in Claude."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Goal, RoadmapItem, RoadmapPhase, TimeLog, User
from app.schemas import TimeLogIn, TimeLogOut
from app.services import timelogs

router = APIRouter(prefix="/time-logs", tags=["time"])


@router.get("", response_model=list[TimeLogOut])
async def list_logs(day: date, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await timelogs.for_day(session, user.id, day)


@router.post("", response_model=TimeLogOut, status_code=201)
async def add_log(body: TimeLogIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    goal = await session.scalar(select(Goal).where(Goal.id == body.goal_id, Goal.user_id == user.id))
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if body.roadmap_item_id is not None and await session.scalar(
            select(RoadmapItem.id).join(RoadmapPhase)
            .where(RoadmapItem.id == body.roadmap_item_id, RoadmapPhase.goal_id == goal.id)) is None:
        raise HTTPException(404, "Roadmap step not found")
    log = await timelogs.add(session, user, body.day, goal.id, body.minutes, body.roadmap_item_id, body.note)
    await session.commit()
    return log


@router.delete("/{log_id}", status_code=204)
async def delete_log(log_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    log = await session.get(TimeLog, log_id)
    if log is None or log.user_id != user.id:
        raise HTTPException(404, "Log not found")
    await timelogs.remove(session, log)
    await session.commit()
