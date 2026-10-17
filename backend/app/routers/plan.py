from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import PlanItem, User
from app.schemas import PlanItemIn, PlanItemOut, PlanPatch

router = APIRouter(prefix="/plan", tags=["plan"])


@router.get("", response_model=list[PlanItemOut])
async def get_plan(day: date, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(PlanItem).where(PlanItem.user_id == user.id, PlanItem.date_for == day)
        .order_by(PlanItem.time_block, PlanItem.id)
    )
    return list(rows)


@router.post("", response_model=PlanItemOut, status_code=201)
async def add_plan_item(body: PlanItemIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    item = PlanItem(user_id=user.id, **body.model_dump())
    session.add(item)
    await session.commit()
    return item


async def _get(session: AsyncSession, item_id: int, user: User) -> PlanItem:
    item = await session.get(PlanItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Plan item not found")
    return item


@router.patch("/{item_id}", response_model=PlanItemOut)
async def update_plan_item(item_id: int, body: PlanPatch, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    item = await _get(session, item_id, user)
    data = body.model_dump(exclude_unset=True)
    done_steps = data.pop("done_steps", None)
    for k, v in data.items():
        setattr(item, k, v)
    if done_steps is not None:
        ticked = set(done_steps)
        steps = [{**step, "done": i in ticked} for i, step in enumerate((item.details or {}).get("steps", []))]
        item.details = {**(item.details or {}), "steps": steps}
    await session.commit()
    return item


@router.delete("/{item_id}", status_code=204)
async def delete_plan_item(item_id: int, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    await session.delete(await _get(session, item_id, user))
    await session.commit()
