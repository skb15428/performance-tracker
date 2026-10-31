"""A private calendar feed. Subscribing to it puts your plan in your phone's calendar, with its normal alerts."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models import User
from app.services import analysis, commitment, push, roadmap
from app.services import topics as study

router = APIRouter(tags=["calendar"], include_in_schema=False)
DAYS_AHEAD = 14
ALERT_MINUTES = 10


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def fold(line: str) -> str:
    """Long lines must wrap at 75 bytes, with each continuation starting with a space."""
    chunks, data = [], line.encode()
    while len(data) > 74:
        cut = 74
        while data[cut] & 0xC0 == 0x80:  # don't split a multi-byte letter
            cut -= 1
        chunks.append(data[:cut].decode())
        data = data[cut:]
    chunks.append(data.decode())
    return "\r\n ".join(chunks)


def event(uid: str, tz: str, day: date, start: str, end: str, title: str, description: str, stamp: str) -> list[str]:
    def at(hhmm: str) -> str:
        return f"{day:%Y%m%d}T{hhmm.replace(':', '')}00"

    return ["BEGIN:VEVENT", f"UID:{uid}@goalcoach", f"DTSTAMP:{stamp}", f"DTSTART;TZID={tz}:{at(start)}",
            f"DTEND;TZID={tz}:{at(end)}", f"SUMMARY:{escape(title)}", f"DESCRIPTION:{escape(description)}",
            "BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-PT{ALERT_MINUTES}M", f"DESCRIPTION:{escape(title)}",
            "END:VALARM", "END:VEVENT"]


async def build(session: AsyncSession, user: User, today: date) -> str:
    goals = await analysis.tracked_goals(session, user)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    forecast = {u.day: u for u in await study.upcoming_days(session, user, goals, today, count=DAYS_AHEAD)}
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GoalCoach//Plan//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:GoalCoach", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        plan = [p for p in await analysis.plan_for(session, user.id, day) if p.status != "skipped"]
        blocks = [(p.time_block, p.title, (p.details or {}).get("why", "")) for p in plan if "-" in p.time_block]
        working = False
        for g in goals:
            if not await roadmap.goal_target_minutes(session, user, g, day):
                continue
            working = True
            if blocks or plan:
                continue
            topic = forecast[day].topics[0][1].topic.title if day in forecast and forecast[day].topics else None
            for b in commitment.routine_blocks_on(g.routine, day) or commitment.usual_blocks(g.routine):
                blocks.append((f"{b['start']}-{b['end']}", topic or b.get("activity") or g.title, g.title))
        for n, (span, title, why) in enumerate(blocks):
            start, end = span.split("-")
            lines += event(f"{day}-{n}", user.timezone, day, start.strip(), end.strip(), title, why, stamp)
        if working:
            hour, minute = map(int, user.reminder_time.split(":"))
            end = f"{(hour + (minute + 10) // 60) % 24:02d}:{(minute + 10) % 60:02d}"
            lines += event(f"{day}-log", user.timezone, day, user.reminder_time, end, "Log your day",
                           push.claude_link("Log my day"), stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


@router.get("/calendar/{token}.ics")
async def calendar_feed(token: str, session: AsyncSession = Depends(get_session)):
    user = await session.scalar(select(User).where(User.calendar_token == token)) if len(token) >= 32 else None
    if user is None:
        raise HTTPException(404, "Not found")
    body = await build(session, user, push.local_now(user.timezone).date())
    return Response(body, media_type="text/calendar; charset=utf-8")
