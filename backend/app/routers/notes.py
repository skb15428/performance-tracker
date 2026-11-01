"""Reading and searching Claude's topic notes. Claude writes them through the connector."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.db import get_session
from app.models import Goal, TopicNote, User
from app.services import notes

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("")
async def list_notes(q: str = "", user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [{"id": n.id, "topic_id": n.topic_id, "title": n.title, "snippet": notes.snippet(n, q),
             "updated_at": n.updated_at} for n in await notes.search(session, user, q)]


@router.get("/{note_id}")
async def read_note(note_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    note = await session.scalar(select(TopicNote).join(Goal).where(TopicNote.id == note_id, Goal.user_id == user.id))
    if note is None:
        raise HTTPException(404, "Note not found")
    return {"id": note.id, "topic_id": note.topic_id, "title": note.title, "content": note.content,
            "updated_at": note.updated_at}
