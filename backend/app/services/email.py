"""Sends reminder emails through Resend's HTTP API. Without an API key it does nothing."""

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
            )
        if r.status_code >= 400:
            log.warning("Resend rejected the email: %s %s", r.status_code, r.text[:200])
        return r.status_code < 400
    except httpx.HTTPError as e:
        log.warning("Email failed: %r", e)
        return False
