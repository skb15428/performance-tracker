"""Restore a GoalCoach export (the JSON from Settings, or a backup) into an empty account.

Usage: DATABASE_URL=... OWNER_EMAIL=you@example.com uv run python scripts/restore_backup.py export.json

On Postgres the id counters don't move on their own, so the script advances them afterwards.
"""

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.models import User  # noqa: E402
from app.services import backup  # noqa: E402


async def main(path: str) -> None:
    export = json.loads(pathlib.Path(path).read_text())
    async with SessionLocal() as session:
        email = get_settings().owner_email.lower()
        user = await session.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            sys.exit(f"No account for {email}. Create it first with scripts/set_password.py.")
        counts = await backup.restore_user(session, user, export)
        if engine.dialect.name == "postgresql":
            for model in backup.OWNED:
                table = model.__tablename__
                await session.execute(text(
                    f"select setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1)) from {table}"))
        await session.commit()
    await engine.dispose()
    print(counts)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
