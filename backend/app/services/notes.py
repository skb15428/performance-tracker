"""Claude's notes on study topics: one Markdown note per topic, searchable by its title and text."""

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, StudyTopic, TopicNote, User, utcnow

MAX_CHARS = 200_000
SNIPPET_CHARS = 160


async def for_topic(session: AsyncSession, topic_id: int) -> TopicNote | None:
    return await session.scalar(select(TopicNote).where(TopicNote.topic_id == topic_id))


async def save(session: AsyncSession, topic: StudyTopic, content: str) -> TopicNote:
    """Writes the topic's note, replacing any earlier version."""
    note = await for_topic(session, topic.id)
    if note is None:
        note = TopicNote(goal_id=topic.goal_id, topic_id=topic.id, title=topic.title, content=content)
        session.add(note)
    else:
        note.title, note.content, note.updated_at = topic.title, content, utcnow()
    await session.flush()
    return note


def snippet(note: TopicNote, query: str) -> str:
    """A short piece of the note around the first search word, or its opening."""
    text = " ".join(re.sub(r"[#*`>~]+", "", note.content).replace("|", " ").split())  # plain words, not Markdown marks
    at = min((i for i in (text.lower().find(w) for w in query.lower().split()) if i >= 0), default=0)
    start = max(at - SNIPPET_CHARS // 4, 0)
    return ("…" if start else "") + text[start:start + SNIPPET_CHARS] + ("…" if len(text) > start + SNIPPET_CHARS else "")


async def search(session: AsyncSession, user: User, query: str = "") -> list[TopicNote]:
    """Notes containing every word of the query, those with it in the title first."""
    words = query.lower().split()
    stmt = select(TopicNote).join(Goal).where(Goal.user_id == user.id)
    for word in words:
        pattern = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(TopicNote.title.ilike(pattern, escape="\\"), TopicNote.content.ilike(pattern, escape="\\")))
    rows = await session.scalars(stmt)
    return sorted(rows, key=lambda n: (not all(w in n.title.lower() for w in words), n.title.lower()))
