from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import User, WeeklyReview
from app.schemas import WeeklyOut
from app.services import weekly

router = APIRouter(prefix="/reviews/weekly", tags=["reviews"])


@router.get("", response_model=list[WeeklyOut])
async def list_reviews(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(WeeklyReview).where(WeeklyReview.user_id == user.id).order_by(WeeklyReview.week_start.desc()).limit(26)
    )
    return list(rows)


@router.post("", response_model=WeeklyOut)
async def generate(week: date | None = None, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    start = weekly.week_start_of(week or date.today())
    if start > date.today():
        raise HTTPException(400, "That week hasn't started yet")
    review = await weekly.generate(session, user, start)
    await session.commit()
    return review
