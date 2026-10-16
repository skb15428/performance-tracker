import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models import User

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


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = settings.jwt_secret
    verification_token_secret = settings.jwt_secret


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
    if x_jobs_secret != settings.jobs_secret:
        raise HTTPException(status_code=403, detail="Invalid jobs secret")
