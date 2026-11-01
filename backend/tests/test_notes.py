"""Topic notes: reading, searching, privacy, surviving a topic being replaced, and export."""

from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.models import StudyTopic
from app.services import notes, topics
from tests.conftest import register
from tests.test_api_flow import setup_flexible_goal

ALL_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def add_note(goal_id: int, title: str, content: str) -> tuple[int, int]:
    async with SessionLocal() as s:
        topic = StudyTopic(goal_id=goal_id, roadmap_item_id=None, title=title, concepts=[])
        s.add(topic)
        await s.flush()
        note = await notes.save(s, topic, content)
        await s.commit()
        return note.id, topic.id


async def setup(client, email: str) -> tuple[dict, int]:
    today = datetime.now(timezone.utc).date()
    h, goal_id, _ = await setup_flexible_goal(client, email, today, ALL_DAYS)
    return h, goal_id


async def test_search_finds_titles_first_then_text(client):
    h, goal_id = await setup(client, "notes-search@example.com")
    await add_note(goal_id, "Attention", "## Why\n\n**Queries**, keys and values. See also tokenization.")
    await add_note(goal_id, "Tokenization", "BPE merges pairs. 100% of text_ becomes tokens.")

    assert [n["title"] for n in (await client.get("/notes", headers=h)).json()] == ["Attention", "Tokenization"]
    found = (await client.get("/notes?q=TOKENIZATION", headers=h)).json()
    assert [n["title"] for n in found] == ["Tokenization", "Attention"]
    assert "tokenization" in found[1]["snippet"]
    assert (await client.get("/notes", headers=h)).json()[0]["snippet"].startswith("Why Queries, keys")
    assert [n["title"] for n in (await client.get("/notes?q=bpe merges", headers=h)).json()] == ["Tokenization"]
    assert (await client.get("/notes?q=bpe keys", headers=h)).json() == []

    # Search characters are taken literally
    assert [n["title"] for n in (await client.get("/notes", headers=h, params={"q": "100%"})).json()] == ["Tokenization"]
    assert (await client.get("/notes", headers=h, params={"q": "%%%"})).json() == []
    assert [n["title"] for n in (await client.get("/notes", headers=h, params={"q": "t_"})).json()] == ["Tokenization"]


async def test_notes_are_private(client):
    h, goal_id = await setup(client, "notes-a@example.com")
    note_id, topic_id = await add_note(goal_id, "Private", "My notes")
    other = await register(client, "notes-b@example.com")
    assert (await client.get("/notes?q=private", headers=other)).json() == []
    assert (await client.get(f"/notes/{note_id}", headers=other)).status_code == 404
    assert (await client.get(f"/notes/{note_id}", headers=h)).json()["content"] == "My notes"
    assert (await client.get(f"/study/topics/{topic_id}", headers=h)).json()["note_id"] == note_id


async def test_a_note_outlives_its_topic(client):
    h, goal_id = await setup(client, "notes-keep@example.com")
    note_id, topic_id = await add_note(goal_id, "Replaced later", "Still here")
    async with SessionLocal() as s:
        await s.delete(await s.get(StudyTopic, topic_id))
        await s.commit()
    note = (await client.get(f"/notes/{note_id}", headers=h)).json()
    assert note["content"] == "Still here" and note["topic_id"] is None


async def test_notes_are_in_the_export(client):
    h, goal_id = await setup(client, "notes-export@example.com")
    await add_note(goal_id, "Kept", "Backed up")
    data = (await client.get("/me/export", headers=h)).json()
    assert [n["content"] for n in data["tables"]["topic_notes"]] == ["Backed up"]


def test_a_topic_in_progress_only_needs_the_rest_of_its_time():
    topic = StudyTopic(status="new", est_minutes=120, understood=["A"],
                       concepts=[{"name": n} for n in "ABCD"])
    assert topics.topic_minutes(topic) == 90
