from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_user
from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import encrypt
from app.models import PushSubscription, User
from app.schemas import PushSubIn, SettingsIn, SettingsOut
from app.services import push

router = APIRouter(tags=["settings"])


def settings_out(user: User) -> SettingsOut:
    s = get_settings()
    return SettingsOut(
        name=user.name, email=user.email, timezone=user.timezone, reminder_time=user.reminder_time,
        morning_push=user.morning_push, daily_available_hours=user.daily_available_hours,
        has_own_key=bool(user.gemini_key_enc), server_llm_available=bool(s.gemini_api_key),
        vapid_public_key=s.vapid_public_key,
    )


@router.get("/me/settings", response_model=SettingsOut)
async def read_settings(user: User = Depends(current_user)):
    return settings_out(user)


@router.put("/me/settings", response_model=SettingsOut)
async def update_settings(body: SettingsIn, user: User = Depends(current_user),
                          session: AsyncSession = Depends(get_session)):
    data = body.model_dump(exclude_unset=True)
    key = data.pop("gemini_api_key", None)
    if key is not None:
        try:
            user.gemini_key_enc = encrypt(key.strip()) if key.strip() else None
        except RuntimeError as e:
            raise HTTPException(500, str(e)) from e
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
