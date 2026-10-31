"""Stops password guessing: the same counter covers the web login and the page Claude sends you to."""

from datetime import datetime, timedelta, timezone

from app.models import User

MAX_FAILED = 5
LOCK_MINUTES = 15


def is_locked(user: User) -> bool:
    until = user.locked_until
    if until is None:
        return False
    until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
    return until > datetime.now(timezone.utc)


def record(user: User, succeeded: bool) -> None:
    if succeeded:
        user.failed_logins, user.locked_until = 0, None
        return
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED:
        user.failed_logins = 0
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)
