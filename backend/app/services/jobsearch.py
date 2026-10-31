"""Job applications: shared by the web page and Claude, so a stage change means the same thing from either."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobApplication, User

STAGES = ("saved", "applied", "screen", "technical", "final", "offer", "rejected", "withdrawn")


def update(row: JobApplication, data: dict, today: date) -> None:
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    if row.stage != "saved" and row.applied_on is None:
        row.applied_on = today
    if row.stage in ("final", "offer"):
        row.reached_final = True


async def add(session: AsyncSession, user: User, data: dict, today: date) -> JobApplication:
    row = JobApplication(user_id=user.id, company=data["company"])
    update(row, data, today)
    session.add(row)
    await session.flush()
    return row


def view(row: JobApplication) -> dict:
    return {"id": row.id, "company": row.company, "role": row.role, "url": row.url, "referral": row.referral,
            "stage": row.stage, "reached_final": row.reached_final,
            "applied_on": row.applied_on.isoformat() if row.applied_on else None, "next_step": row.next_step,
            "notes": row.notes}
