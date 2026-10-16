from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import RoadmapItem, TrendSource, TrendSuggestion, User
from app.schemas import TrendSourceIn, TrendSourceOut, TrendSuggestionOut
from app.services import roadmap
from app.services.trends.scan import scan_goal

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("", response_model=list[TrendSuggestionOut])
async def list_suggestions(status: str = "new", user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(TrendSuggestion).where(TrendSuggestion.user_id == user.id, TrendSuggestion.status == status)
        .order_by(TrendSuggestion.created_at.desc())
    )
    return list(rows)


@router.post("/scan/{goal_id}", response_model=list[TrendSuggestionOut])
async def scan_now(goal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    goal = await roadmap.load_goal(session, goal_id, user.id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    created = await scan_goal(session, user, goal, date.today())
    await session.commit()
    return created


async def _get(session: AsyncSession, sid: int, user: User) -> TrendSuggestion:
    s = await session.get(TrendSuggestion, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Suggestion not found")
    return s


@router.post("/{sid}/add", response_model=TrendSuggestionOut)
async def add_to_roadmap(sid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    s = await _get(session, sid, user)
    goal = await roadmap.load_goal(session, s.goal_id, user.id)
    item = RoadmapItem(type="topic", title=s.title, description=s.why_relevant, est_hours=s.est_hours,
                       resources=s.links, source="trend")
    roadmap.insert_after_current(goal, item)
    await session.flush()
    await roadmap.reschedule(session, user, goal, date.today())
    s.status = "added_to_roadmap"
    await session.commit()
    return s


@router.post("/{sid}/dismiss", response_model=TrendSuggestionOut)
async def dismiss(sid: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    s = await _get(session, sid, user)
    s.status = "dismissed"
    await session.commit()
    return s


@router.get("/sources", response_model=list[TrendSourceOut])
async def list_sources(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(TrendSource).where(or_(TrendSource.user_id.is_(None), TrendSource.user_id == user.id))
        .order_by(TrendSource.user_id.is_(None).desc(), TrendSource.id)
    )
    return list(rows)


@router.post("/sources", response_model=TrendSourceOut, status_code=201)
async def add_source(body: TrendSourceIn, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    src = TrendSource(user_id=user.id, **body.model_dump())
    session.add(src)
    await session.commit()
    return src


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: int, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    src = await session.get(TrendSource, source_id)
    if src is None or src.user_id != user.id:
        raise HTTPException(404, "Source not found (default sources can't be deleted)")
    await session.delete(src)
    await session.commit()
