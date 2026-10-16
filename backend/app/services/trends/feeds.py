"""Curated feed ingestion (arXiv, Hacker News, AI blogs via RSS; GitHub via search API)."""

import logging
import re
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser
import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TrendItem, TrendSource

log = logging.getLogger(__name__)

# (name, kind, url, ranking weight). Curated writers rank above firehoses like arXiv.
DEFAULT_SOURCES = [
    ("arXiv cs.CL (NLP/LLMs)", "rss", "https://rss.arxiv.org/rss/cs.CL", 1.0),
    ("arXiv cs.AI", "rss", "https://rss.arxiv.org/rss/cs.AI", 1.0),
    ("arXiv cs.LG", "rss", "https://rss.arxiv.org/rss/cs.LG", 1.0),
    ("Hacker News best", "rss", "https://hnrss.org/best", 2.0),
    ("Hugging Face blog", "rss", "https://huggingface.co/blog/feed.xml", 3.0),
    ("Simon Willison", "rss", "https://simonwillison.net/atom/everything/", 3.0),
    ("GitHub: new LLM repos", "github", "topic:llm", 1.5),
    ("GitHub: new AI agent repos", "github", "topic:ai-agents", 1.5),
]
USER_SOURCE_WEIGHT = 2.5  # sources the user picked themselves
MAX_PER_SOURCE = 60
KEEP_DAYS = 60
TAG_RE = re.compile(r"<[^>]+>")


def clean(text: str, limit: int = 500) -> str:
    return TAG_RE.sub("", text or "").strip()[:limit]


def parse_feed(content: bytes | str) -> list[dict]:
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries[:MAX_PER_SOURCE]:
        link = e.get("link")
        if not link:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        published = datetime.fromtimestamp(mktime(ts), tz=timezone.utc) if ts else datetime.now(timezone.utc)
        out.append({"title": clean(e.get("title", ""), 300), "url": link,
                    "summary": clean(e.get("summary", "")), "published_at": published})
    return out


def parse_github(payload: dict) -> list[dict]:
    out = []
    for repo in payload.get("items", [])[:MAX_PER_SOURCE]:
        created = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00"))
        out.append({"title": f"{repo['full_name']} (★{repo.get('stargazers_count', 0)})", "url": repo["html_url"],
                    "summary": clean(repo.get("description") or ""), "published_at": created})
    return out


async def ensure_default_sources(session: AsyncSession) -> None:
    existing = {s.url: s for s in await session.scalars(select(TrendSource).where(TrendSource.user_id.is_(None)))}
    for name, kind, url, weight in DEFAULT_SOURCES:
        if url not in existing:
            session.add(TrendSource(user_id=None, name=name, kind=kind, url=url, weight=weight))
        else:
            existing[url].weight = weight
    await session.flush()


async def fetch_source(client: httpx.AsyncClient, source: TrendSource) -> list[dict]:
    if source.kind == "github":
        since = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
        resp = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": f"{source.url} created:>{since}", "sort": "stars", "order": "desc", "per_page": 20},
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        return parse_github(resp.json())
    resp = await client.get(source.url, follow_redirects=True)
    resp.raise_for_status()
    return parse_feed(resp.content)


async def ingest_all(session: AsyncSession) -> int:
    await ensure_default_sources(session)
    sources = list(await session.scalars(select(TrendSource).where(TrendSource.enabled.is_(True))))
    added = 0
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "GoalCoach/0.1"}) as client:
        for source in sources:
            try:
                entries = await fetch_source(client, source)
            except Exception as e:  # one bad feed must not stop the rest
                log.warning("Feed %s failed: %r", source.url, e)
                continue
            urls = [e["url"] for e in entries]
            known = set(await session.scalars(select(TrendItem.url).where(TrendItem.url.in_(urls))))
            for e in entries:
                if e["url"] not in known:
                    session.add(TrendItem(source_id=source.id, **e))
                    known.add(e["url"])
                    added += 1
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    await session.execute(delete(TrendItem).where(TrendItem.published_at < cutoff))
    await session.flush()
    return added
