"""Goal intake interview: chat with the LLM until it can propose a roadmap."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, GoalChatMessage, User
from app.services import prompts
from app.services.llm import LLMError, get_llm
from app.services.llm.outputs import IntakeTurn

NO_LLM_MESSAGE = (
    "The AI coach isn't available right now (no API key configured or quota reached). "
    "You can still build your roadmap manually in the Roadmap tab, or add your own Gemini key in Settings."
)


async def chat_history(session: AsyncSession, goal_id: int) -> list[GoalChatMessage]:
    rows = await session.scalars(
        select(GoalChatMessage).where(GoalChatMessage.goal_id == goal_id).order_by(GoalChatMessage.id)
    )
    return list(rows)


def render_turn(turn: IntakeTurn) -> str:
    text = turn.message.strip()
    if turn.action == "ask" and turn.questions:
        text += "\n\n" + "\n".join(f"- {q}" for q in turn.questions)
    return text


async def run_turn(session: AsyncSession, user: User, goal: Goal, user_message: str | None) -> IntakeTurn | None:
    """Store the user's message (if any), ask the LLM for the next turn and store its reply."""
    if user_message:
        session.add(GoalChatMessage(goal_id=goal.id, role="user", content=user_message))
        await session.flush()

    llm = get_llm(user)
    if llm is None:
        session.add(GoalChatMessage(goal_id=goal.id, role="assistant", content=NO_LLM_MESSAGE))
        return None

    history = await chat_history(session, goal.id)
    prompt = prompts.intake_prompt(
        goal,
        [(m.role, m.content) for m in history],
        goal.context or {},
        user.daily_available_hours,
        date.today().isoformat(),
    )
    try:
        turn = await llm.complete_json(prompts.INTAKE_SYSTEM, prompt, IntakeTurn)
    except LLMError as e:
        session.add(GoalChatMessage(goal_id=goal.id, role="assistant", content=f"{NO_LLM_MESSAGE}\n\n({e})"))
        return None

    goal.context = {**(goal.context or {}), **{f.key: f.value for f in turn.facts}}
    if turn.action == "propose" and turn.roadmap and turn.roadmap.phases:
        goal.proposed_roadmap = turn.roadmap.model_dump()
        goal.intake_status = "roadmap_proposed" if goal.intake_status == "interviewing" else goal.intake_status
        content = turn.message.strip() or "Here's a roadmap proposal. Review it, edit anything, then approve."
    else:
        content = render_turn(turn)
    session.add(GoalChatMessage(goal_id=goal.id, role="assistant", content=content))
    return turn
