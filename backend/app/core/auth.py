import secrets
import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException, Request
from fastapi_users import BaseUserManager, FastAPIUsers, InvalidPasswordException, UUIDIDMixin, exceptions, schemas
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lockout
from app.core.config import DEFAULT_JOBS_SECRET, get_settings
from app.core.db import get_session
from app.models import User
from app.services.email import send_email

settings = get_settings()


class UserRead(schemas.BaseUser[uuid.UUID]):
    name: str | None = None
    timezone: str
    reminder_time: str
    morning_push: bool
    daily_available_hours: float


class UserCreate(schemas.BaseUserCreate):
    name: str | None = None
    timezone: str = "UTC"


class UserUpdate(schemas.BaseUserUpdate):
    name: str | None = None


async def get_user_db(session: AsyncSession = Depends(get_session)) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


MIN_PASSWORD_LENGTH = 10


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = settings.jwt_secret
    verification_token_secret = settings.jwt_secret

    async def validate_password(self, password: str, user) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidPasswordException(f"Use at least {MIN_PASSWORD_LENGTH} characters")

    async def authenticate(self, credentials):
        try:
            user = await self.get_by_email(credentials.username)
        except exceptions.UserNotExists:
            user = None
        if user is not None and lockout.is_locked(user):
            self.password_helper.hash(credentials.password)  # takes the same time as a real check
            return None
        result = await super().authenticate(credentials)
        if user is not None:
            lockout.record(user, result is not None)
            await self.user_db.update(user, {"failed_logins": user.failed_logins, "locked_until": user.locked_until})
        return result

    async def on_after_forgot_password(self, user: User, token: str, request: Request | None = None) -> None:
        link = f"{settings.app_url}/reset-password?token={token}"
        await send_email(user.email, "Reset your GoalCoach password", (
            f'<p>Someone asked to reset your password. If that was you:</p><p><a href="{link}">Choose a new password'
            f"</a></p><p>The link works for one hour. If it wasn't you, ignore this email.</p>"))


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.jwt_secret, lifetime_seconds=settings.jwt_lifetime_seconds)


auth_backend = AuthenticationBackend(
    name="jwt", transport=BearerTransport(tokenUrl="auth/jwt/login"), get_strategy=get_jwt_strategy
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
current_user = fastapi_users.current_user(active=True)


async def require_jobs_secret(x_jobs_secret: str = Header(default="")) -> None:
    if settings.jobs_secret == DEFAULT_JOBS_SECRET and not settings.allow_default_jobs_secret:
        raise HTTPException(status_code=503, detail="JOBS_SECRET isn't set")  # its default value is public
    if not secrets.compare_digest(x_jobs_secret.encode(), settings.jobs_secret.encode()):
        raise HTTPException(status_code=403, detail="Invalid jobs secret")
