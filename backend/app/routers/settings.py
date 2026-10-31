import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi_users import exceptions
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserManager, UserUpdate, current_user, get_user_manager
from app.core.config import get_settings
from app.core.db import get_session
from app.models import PushSubscription, User
from app.schemas import PasswordIn, PushSubIn, SettingsIn, SettingsOut
from app.services import backup, events, push

router = APIRouter(tags=["settings"])


def settings_out(user: User) -> SettingsOut:
    s = get_settings()
    return SettingsOut(
        name=user.name, email=user.email, timezone=user.timezone, reminder_time=user.reminder_time,
        morning_push=user.morning_push, daily_available_hours=user.daily_available_hours,
        email_reminders=user.email_reminders,
        email_enabled=bool(s.resend_api_key), calendar_token=user.calendar_token,
        vapid_public_key=s.vapid_public_key,
    )


@router.get("/me/settings", response_model=SettingsOut)
async def read_settings(user: User = Depends(current_user)):
    return settings_out(user)


@router.put("/me/settings", response_model=SettingsOut)
async def update_settings(body: SettingsIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    session.add(user)
    await session.commit()
    return settings_out(user)


@router.post("/push/subscribe", status_code=201)
async def subscribe(body: PushSubIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    sub = await session.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint)
        session.add(sub)
    sub.user_id, sub.p256dh, sub.auth = user.id, body.keys.get("p256dh", ""), body.keys.get("auth", "")
    await session.commit()
    return {"ok": True}


@router.post("/push/test")
async def test_push(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    sent = await push.send_to_user(session, user.id, {"title": "Notifications work!", "body": "You'll get a nightly "
                                                      "reminder to log your day.", "url": "/"})
    await session.commit()
    return {"sent": sent}


@router.put("/me/password")
async def change_password(body: PasswordIn, user: User = Depends(current_user),
                          manager: UserManager = Depends(get_user_manager)):
    verified, _ = PasswordHelper().verify_and_update(body.current_password, user.hashed_password)
    if not verified:
        raise HTTPException(400, "Your current password isn't right")
    try:
        await manager.update(UserUpdate(password=body.new_password), user)
    except exceptions.InvalidPasswordException as e:
        raise HTTPException(400, e.reason) from e
    return {"ok": True}


@router.get("/me/status")
async def status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Whether the things that run by themselves are really running."""
    s = get_settings()
    beat = await events.last(session, "heartbeat")
    saved = await events.last(session, "backup")
    error = await events.last(session, "error")
    subscriptions = await session.scalars(select(PushSubscription.id).where(PushSubscription.user_id == user.id))
    return {
        "scheduler_last_run": beat.created_at if beat else None,
        "last_reminder_day": user.last_reminded_on,
        "email_enabled": bool(s.resend_api_key),
        "push_devices": len(list(subscriptions)),
        "calendar_connected": bool(user.calendar_token),
        "last_backup": saved.created_at if saved else None,
        "errors_last_7_days": await events.count_since(session, "error", 7),
        "last_error": error.data | {"at": error.created_at} if error else None,
        "default_secrets": s.uses_default_secrets,
    }


@router.post("/me/calendar-token")
async def calendar_token(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Create the private calendar link. Calling it again replaces the old link, which then stops working."""
    user.calendar_token = secrets.token_urlsafe(32)
    session.add(user)
    await session.commit()
    return {"token": user.calendar_token}


@router.get("/me/export")
async def export_data(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Everything the app holds for you, as one JSON file."""
    data = await backup.export_user(session, user)
    await events.record("backup", {"source": "download"})
    return data
