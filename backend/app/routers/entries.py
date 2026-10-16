from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import DailyEntry, User
from app.schemas import ConfirmIn, DraftOut, EntryIn, EntryOut
from app.services import analysis

router = APIRouter(prefix="/entries", tags=["entries"])


async def get_entry(session: AsyncSession, user: User, day: date) -> DailyEntry | None:
    return await session.scalar(select(DailyEntry).where(DailyEntry.user_id == user.id, DailyEntry.date == day))


get_or_create = analysis.get_or_create_entry


@router.get("", response_model=list[EntryOut])
async def list_entries(start: date, end: date, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(DailyEntry).where(DailyEntry.user_id == user.id, DailyEntry.date.between(start, end))
        .order_by(DailyEntry.date.desc())
    )
    return list(rows)


@router.get("/{day}", response_model=EntryOut)
async def read_entry(day: date, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    entry = await get_entry(session, user, day)
    if entry is None:
        return EntryOut(date=day, schedule=[], free_text="", energy=None, draft=None, analyzed_at=None)
    return entry


@router.put("/{day}", response_model=EntryOut)
async def save_entry(day: date, body: EntryIn, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    entry = await get_or_create(session, user, day)
    entry.schedule = [b.model_dump(exclude_none=True) for b in body.schedule]
    entry.free_text = body.free_text
    entry.energy = body.energy
    await session.commit()
    return entry


@router.post("/{day}/analyze", response_model=DraftOut)
async def analyze(day: date, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    entry = await get_entry(session, user, day)
    if entry is None or not (entry.schedule or entry.free_text.strip()):
        raise HTTPException(400, "Add your schedule or notes for the day first")
    draft, used_llm = await analysis.build_draft(session, user, entry)
    entry.draft = {"analysis": draft.model_dump(), "used_llm": used_llm}
    await session.commit()
    return DraftOut(draft=draft, used_llm=used_llm)


@router.post("/{day}/confirm", response_model=EntryOut)
async def confirm(day: date, body: ConfirmIn, user: User = Depends(current_user),
                  session: AsyncSession = Depends(get_session)):
    entry = await get_or_create(session, user, day)
    await analysis.confirm(session, user, entry, body.analysis, body.used_llm)
    await session.commit()
    await session.refresh(entry, ["activities", "review"])
    return entry
