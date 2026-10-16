"""Weekly per-goal trend scan: feed candidates + grounded web search -> <=3 suggestions."""

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Goal, TrendItem, TrendSource, TrendSuggestion, User
from app.services import prompts, roadmap
from app.services.analysis import focus_items
from app.services.llm import LLMError, get_llm
from app.services.llm.outputs import Resource, TrendPick, TrendPicks

STOPWORDS = {
    "with", "from", "into", "your", "this", "that", "basics", "fundamentals", "introduction", "intro", "learn",
    "build", "project", "using", "advanced", "practice", "study", "first", "apply", "and", "the", "for",
}
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{2,}")


def keywords(topics: list[str]) -> list[str]:
    words = []
    for t in topics:
        for w in WORD_RE.findall(t):
            lw = w.lower().strip(".-")
            if lw not in STOPWORDS and (len(lw) > 3 or w.isupper()) and lw not in words:
                words.append(lw)
    return words[:12]


ARXIV_CAP = 8  # arXiv posts hundreds of papers a day; keep it from drowning curated sources
TITLE_HIT, SUMMARY_HIT = 3.0, 1.0


def term_regex(term: str) -> re.Pattern:
    """Whole-word/phrase match, case-insensitive, also matching a plural ("transformer" ~ "transformers")."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term.strip().lower())}(?:s|es)?(?![A-Za-z0-9])")


def search_terms(goal: Goal, today: date) -> list[tuple[str, str]]:
    """(term, what it's for): the focus items' search terms (or keywords from their titles) plus the goal's
    watch topics."""
    out: list[tuple[str, str]] = []
    for item in focus_items(goal, today, limit=4):
        for term in item.search_terms or keywords([item.title]):
            out.append((term, item.title))
    for topic in goal.watch_topics or []:
        for term in topic.get("terms") or keywords([topic.get("topic", "")]):
            out.append((term, f"watch: {topic.get('topic', '')}"))
    seen, unique = set(), []
    for term, why in out:
        if term.strip() and term.lower() not in seen:
            seen.add(term.lower())
            unique.append((term, why))
    return unique


def recency(published: datetime, now: datetime) -> float:
    published = published if published.tzinfo else published.replace(tzinfo=timezone.utc)
    age = (now - published).total_seconds() / 86400
    return 1.0 if age <= 3 else max(0.5, 1 - (age - 3) / 22)


async def already_suggested_urls(session: AsyncSession, goal_id: int) -> set[str]:
    rows = await session.scalars(select(TrendSuggestion.links).where(TrendSuggestion.goal_id == goal_id))
    return {link.get("url") for links in rows for link in links or [] if link.get("url")}


async def rank_candidates(session: AsyncSession, user: User, goal: Goal, today: date, days: int = 14,
                          limit: int = 25) -> list[dict]:
    """Recent feed items scored by search-term hits (title > summary) x source weight x recency, minus anything
    already suggested for this goal, with arXiv capped."""
    terms = [(t, w, term_regex(t)) for t, w in search_terms(goal, today)]
    if not terms:
        return []
    now = datetime.now(timezone.utc)
    rows = await session.execute(
        select(TrendItem, TrendSource.weight, TrendSource.name)
        .join(TrendSource)
        .where(TrendItem.published_at >= now - timedelta(days=days), TrendSource.enabled.is_(True),
               or_(TrendSource.user_id.is_(None), TrendSource.user_id == user.id))
        .order_by(TrendItem.published_at.desc())
        .limit(3000)
    )
    skip = await already_suggested_urls(session, goal.id)
    scored = []
    for item, weight, source in rows:
        if item.url in skip:
            continue
        title, summary = item.title.lower(), (item.summary or "").lower()
        hits, matched = 0.0, []
        for term, why, rx in terms:
            h = TITLE_HIT if rx.search(title) else SUMMARY_HIT if rx.search(summary) else 0
            if h:
                hits += h
                matched.append({"term": term, "for": why})
        if hits:
            scored.append((hits * (weight or 1.0) * recency(item.published_at, now), item, source, matched))
    scored.sort(key=lambda x: -x[0])
    out, arxiv = [], 0
    for score, item, source, matched in scored:
        if "arxiv.org" in item.url:
            if arxiv >= ARXIV_CAP:
                continue
            arxiv += 1
        out.append({"title": item.title, "url": item.url, "source": source, "summary": (item.summary or "")[:300],
                    "published": item.published_at.date().isoformat(), "score": round(score, 2),
                    "matched": matched})
        if len(out) >= limit:
            break
    return out


async def scan_goal(session: AsyncSession, user: User, goal: Goal, today: date) -> list[TrendSuggestion]:
    focus = focus_items(goal, today, limit=4)
    topics = [i.title for i in focus] or [goal.title]
    candidates = await rank_candidates(session, user, goal, today)

    previous = set(
        (t or "").lower()
        for t in await session.scalars(select(TrendSuggestion.title).where(TrendSuggestion.goal_id == goal.id))
    )
    in_roadmap = [i.title for i in roadmap.ordered_items(goal)]

    picks: list[TrendPick] = []
    llm = get_llm(user)
    if llm is not None:
        grounded_text, sources = "", []
        try:
            grounded = await llm.search_grounded(prompts.trend_search_query(goal, topics))
            grounded_text, sources = grounded.text, grounded.sources
        except LLMError:
            pass
        try:
            result = await llm.complete_json(
                prompts.TREND_SYSTEM,
                prompts.trend_prompt(goal, topics, in_roadmap,
                                     [f"- {c['title']} | {c['url']} | {c['summary'][:200]}" for c in candidates],
                                     grounded_text, sources),
                TrendPicks,
            )
            picks = result.suggestions[:3]
        except LLMError:
            picks = []
    if not picks and llm is None:
        picks = [TrendPick(title=c["title"], why_relevant=f"Matches: {', '.join(m['term'] for m in c['matched'][:3])}",
                           links=[Resource(title=c["title"], url=c["url"])]) for c in candidates[:3]]

    created = []
    for p in picks:
        if p.title.lower() in previous:
            continue
        s = TrendSuggestion(user_id=user.id, goal_id=goal.id, title=p.title, why_relevant=p.why_relevant,
                            est_hours=p.est_hours, links=[link.model_dump() for link in p.links])
        session.add(s)
        created.append(s)
    await session.flush()
    return created
