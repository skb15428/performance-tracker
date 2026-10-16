from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Goal, ReplanProposal, User
from app.schemas import ReplanOut
from app.services import roadmap, timeline

router = APIRouter(prefix="/replans", tags=["replans"])


async def _get(session: AsyncSession, proposal_id: int, user: User) -> ReplanProposal:
    proposal = await session.scalar(
        select(ReplanProposal).join(Goal).where(ReplanProposal.id == proposal_id, Goal.user_id == user.id)
    )
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    return proposal


@router.get("", response_model=list[ReplanOut])
async def list_replans(status: str = "pending", user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(ReplanProposal).join(Goal).where(Goal.user_id == user.id, ReplanProposal.status == status)
        .order_by(ReplanProposal.created_at.desc())
    )
    return list(rows)


@router.post("/goal/{goal_id}", response_model=ReplanOut)
async def request_replan(goal_id: int, user: User = Depends(current_user),
                         session: AsyncSession = Depends(get_session)):
    """Ask for a replan proposal now (normally created by the nightly check)."""
    goal = await roadmap.load_goal(session, goal_id, user.id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    if existing := await timeline.pending_replan(session, goal.id):
        existing.status = "rejected"
    status = await timeline.goal_status(session, user, goal, date.today())
    proposal = await timeline.build_replan(session, user, goal, status, date.today())
    if proposal is None:
        raise HTTPException(400, "Nothing left to reschedule")
    await session.commit()
    return proposal


@router.post("/{proposal_id}/accept", response_model=ReplanOut)
async def accept(proposal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    proposal = await _get(session, proposal_id, user)
    if proposal.status != "pending":
        raise HTTPException(400, "Proposal already resolved")
    goal = await roadmap.load_goal(session, proposal.goal_id, user.id)
    await timeline.apply_replan(session, user, goal, proposal, date.today())
    await session.commit()
    return proposal


@router.post("/{proposal_id}/reject", response_model=ReplanOut)
async def reject(proposal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    proposal = await _get(session, proposal_id, user)
    proposal.status = "rejected"
    await session.commit()
    return proposal
