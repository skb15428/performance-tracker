from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Goal, RoadmapItem, RoadmapPhase, User
from app.schemas import (
    ApproveIn,
    ChatIn,
    ChatMessageOut,
    ChatOut,
    FeasibilityOut,
    GoalIn,
    GoalOut,
    GoalPatch,
    ItemIn,
    ItemPatch,
    RoadmapItemOut,
    RoadmapOut,
    RoadmapPhaseOut,
    TimelineOut,
)
from app.services import intake, roadmap, timeline
from app.services.push import local_now

router = APIRouter(prefix="/goals", tags=["goals"])


async def goal_out(session: AsyncSession, user: User, goal: Goal) -> GoalOut:
    out = GoalOut.model_validate(goal)
    items = [i for i in roadmap.ordered_items(goal) if i.status != "skipped"]
    total = sum(i.est_hours for i in items)
    done = sum(i.est_hours if i.status == "done" else min(i.hours_logged, i.est_hours) for i in items)
    out.progress_pct = round(100 * done / total, 1) if total else 0
    if goal.intake_status == "active":
        out.timeline = TimelineOut(**(await timeline.goal_status(session, user, goal, local_now(user.timezone).date())).as_dict())
        pending = await timeline.pending_replan(session, goal.id)
        out.pending_replan_id = pending.id if pending else None
    return out


async def get_goal_or_404(session: AsyncSession, goal_id: int, user: User) -> Goal:
    goal = await roadmap.load_goal(session, goal_id, user.id)
    if goal is None:
        raise HTTPException(404, "Goal not found")
    return goal


async def roadmap_out(session: AsyncSession, user: User, goal: Goal, feasibility=None) -> RoadmapOut:
    return RoadmapOut(
        goal=await goal_out(session, user, goal),
        phases=[RoadmapPhaseOut.model_validate(p) for p in goal.phases],
        feasibility=FeasibilityOut(**feasibility.__dict__) if feasibility else None,
    )


@router.get("", response_model=list[GoalOut])
async def list_goals(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    goals = await session.scalars(
        select(Goal).where(Goal.user_id == user.id)
        .options(selectinload(Goal.phases).selectinload(RoadmapPhase.items))
        .order_by(Goal.status, Goal.priority.desc(), Goal.id)
    )
    return [await goal_out(session, user, g) for g in goals]


@router.post("", response_model=ChatOut, status_code=201)
async def create_goal(body: GoalIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    goal = Goal(user_id=user.id, **body.model_dump())
    goal.phases = []
    session.add(goal)
    await session.flush()
    await intake.run_turn(session, user, goal, None)  # the coach opens the interview
    await session.commit()
    goal = await get_goal_or_404(session, goal.id, user)
    messages = await intake.chat_history(session, goal.id)
    return ChatOut(messages=[ChatMessageOut.model_validate(m) for m in messages],
                   goal=await goal_out(session, user, goal))


@router.get("/{goal_id}", response_model=GoalOut)
async def get_goal(goal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await goal_out(session, user, await get_goal_or_404(session, goal_id, user))


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(goal_id: int, body: GoalPatch, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(goal, k, v)
    await session.commit()
    return await goal_out(session, user, goal)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(goal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    await session.delete(goal)
    await session.commit()


# ----- intake chat -----
@router.get("/{goal_id}/chat", response_model=ChatOut)
async def get_chat(goal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    messages = await intake.chat_history(session, goal.id)
    return ChatOut(messages=[ChatMessageOut.model_validate(m) for m in messages],
                   goal=await goal_out(session, user, goal))


@router.post("/{goal_id}/chat", response_model=ChatOut)
async def post_chat(goal_id: int, body: ChatIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    await intake.run_turn(session, user, goal, body.message)
    await session.commit()
    messages = await intake.chat_history(session, goal.id)
    return ChatOut(messages=[ChatMessageOut.model_validate(m) for m in messages],
                   goal=await goal_out(session, user, goal))


# ----- roadmap -----
@router.get("/{goal_id}/roadmap", response_model=RoadmapOut)
async def get_roadmap(goal_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await roadmap_out(session, user, await get_goal_or_404(session, goal_id, user))


@router.post("/{goal_id}/roadmap/approve", response_model=RoadmapOut)
async def approve_roadmap(goal_id: int, body: ApproveIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    if not body.roadmap.phases:
        raise HTTPException(400, "Roadmap needs at least one phase")
    feas = await roadmap.approve_draft(session, user, goal, body.roadmap, body.target_date, date.today())
    await session.commit()
    goal = await get_goal_or_404(session, goal.id, user)
    return await roadmap_out(session, user, goal, feas)


@router.post("/{goal_id}/roadmap/reschedule", response_model=RoadmapOut)
async def reschedule_roadmap(goal_id: int, user: User = Depends(current_user),
                             session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    feas = await roadmap.reschedule(session, user, goal, date.today())
    await session.commit()
    return await roadmap_out(session, user, goal, feas)


@router.post("/{goal_id}/roadmap/phases", response_model=RoadmapOut)
async def add_phase(goal_id: int, body: dict, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    title = str(body.get("title", "")).strip() or "New phase"
    goal.phases.append(RoadmapPhase(title=title, order=len(goal.phases), items=[]))
    if goal.intake_status != "active":
        goal.intake_status = "active"  # building the roadmap by hand
    await session.commit()
    goal = await get_goal_or_404(session, goal_id, user)
    return await roadmap_out(session, user, goal)


async def _item_for_user(session: AsyncSession, item_id: int, user: User) -> RoadmapItem:
    item = await session.scalar(
        select(RoadmapItem).join(RoadmapPhase).join(Goal)
        .where(RoadmapItem.id == item_id, Goal.user_id == user.id)
    )
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


@router.post("/{goal_id}/roadmap/items", response_model=RoadmapItemOut, status_code=201)
async def add_item(goal_id: int, body: ItemIn, user: User = Depends(current_user),
                   session: AsyncSession = Depends(get_session)):
    goal = await get_goal_or_404(session, goal_id, user)
    phase = next((p for p in goal.phases if p.id == body.phase_id), None)
    if phase is None:
        raise HTTPException(404, "Phase not found")
    item = RoadmapItem(order=len(phase.items), type=body.type, title=body.title, description=body.description,
                       est_hours=body.est_hours, source="user")
    phase.items.append(item)
    await session.commit()
    return RoadmapItemOut.model_validate(item)


@router.patch("/roadmap/items/{item_id}", response_model=RoadmapItemOut)
async def update_item(item_id: int, body: ItemPatch, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    item = await _item_for_user(session, item_id, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    if "planned_start" in data or "planned_due" in data:
        goal = await session.get(Goal, (await session.get(RoadmapPhase, item.phase_id)).goal_id)
        goal.baseline = {}  # dates set by hand: measure progress against them instead of the scheduler's plan
    if data.get("status") == "done" and item.completed_at is None:
        item.completed_at = date.today()
    elif "status" in data and data["status"] != "done":
        item.completed_at = None
    await session.commit()
    return RoadmapItemOut.model_validate(item)


@router.delete("/roadmap/items/{item_id}", status_code=204)
async def delete_item(item_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    item = await _item_for_user(session, item_id, user)
    await session.delete(item)
    await session.commit()
