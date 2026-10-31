"""The job search: where you've applied and how far each application got."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import JobApplication, User
from app.schemas import ApplicationIn, ApplicationOut, ApplicationPatch
from app.services import jobsearch
from app.services.push import local_now

router = APIRouter(prefix="/applications", tags=["job search"])


async def _get(session: AsyncSession, application_id: int, user: User) -> JobApplication:
    row = await session.get(JobApplication, application_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Application not found")
    return row


@router.get("", response_model=list[ApplicationOut])
async def list_applications(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(JobApplication).where(JobApplication.user_id == user.id)
                                      .order_by(JobApplication.updated_at.desc())))


@router.post("", response_model=ApplicationOut, status_code=201)
async def add_application(body: ApplicationIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    row = await jobsearch.add(session, user, body.model_dump(), local_now(user.timezone).date())
    await session.commit()
    return row


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update_application(application_id: int, body: ApplicationPatch, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    row = await _get(session, application_id, user)
    jobsearch.update(row, body.model_dump(exclude_unset=True), local_now(user.timezone).date())
    await session.commit()
    return row


@router.delete("/{application_id}", status_code=204)
async def delete_application(application_id: int, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    await session.delete(await _get(session, application_id, user))
    await session.commit()
