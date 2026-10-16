"""Set the password for the owner account (OWNER_EMAIL), creating the account if needed.

You use this password to log in to the web dashboard and to approve Claude when adding the connector.
Locally:        uv run python scripts/set_password.py
Cloud (Neon):   DATABASE_URL='postgresql://...' OWNER_EMAIL=you@example.com uv run python scripts/set_password.py
"""

import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable when run as a script

from fastapi_users.password import PasswordHelper  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


def local_timezone() -> str:
    """This computer's IANA timezone (e.g. Asia/Kolkata), so reminders and "today" match the user's day."""
    try:
        return os.readlink("/etc/localtime").split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


async def main() -> None:
    email = get_settings().owner_email.lower()
    password = getpass.getpass(f"New GoalCoach password for {email}: ")
    if len(password) < 8 or password != getpass.getpass("Repeat: "):
        print("Passwords must match and be at least 8 characters.")
        return
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            user = User(email=email, hashed_password="", is_active=True, is_verified=True, timezone=local_timezone())
            session.add(user)
            print(f"Created account {email}.")
        user.hashed_password = PasswordHelper().hash(password)
        await session.commit()
    print("Password set.")


if __name__ == "__main__":
    asyncio.run(main())
