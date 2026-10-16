"""Set the password for the owner account (OWNER_EMAIL), creating the account if needed.

You use this password to log in to the web dashboard and to approve Claude when adding the connector.
Locally:        uv run python scripts/set_password.py
Cloud (Neon):   DATABASE_URL='postgresql://...' OWNER_EMAIL=you@example.com uv run python scripts/set_password.py
"""

import asyncio
import getpass

from fastapi_users.password import PasswordHelper
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import User


async def main() -> None:
    email = get_settings().owner_email.lower()
    password = getpass.getpass(f"New GoalCoach password for {email}: ")
    if len(password) < 8 or password != getpass.getpass("Repeat: "):
        print("Passwords must match and be at least 8 characters.")
        return
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            user = User(email=email, hashed_password="", is_active=True, is_verified=True)
            session.add(user)
            print(f"Created account {email}.")
        user.hashed_password = PasswordHelper().hash(password)
        await session.commit()
    print("Password set.")


if __name__ == "__main__":
    asyncio.run(main())
