"""Single-user OAuth 2.1 authorization server for the remote MCP endpoint.

Flow (driven by Claude when you add the connector):
  1. Claude registers itself (dynamic client registration) -> register_client
  2. Claude sends you to /authorize -> authorize() stores the request and returns our login page URL
  3. You enter your GoalCoach password on /oauth/login -> complete_login() issues a one-time code
  4. Claude swaps the code (with PKCE) for access + refresh tokens -> exchange_authorization_code
  5. Claude refreshes tokens when they expire -> exchange_refresh_token (refresh tokens rotate)

Everything is stored in the database (hashed), so tokens survive restarts of the free Render instance.
"""

import hashlib
import secrets
import time

from fastapi_users.password import PasswordHelper
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import OAuthClient, OAuthRecord, User

PENDING_TTL = 10 * 60
CODE_TTL = 5 * 60
ACCESS_TTL = 24 * 60 * 60
REFRESH_TTL = 90 * 24 * 60 * 60
MAX_LOGIN_ATTEMPTS = 5


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(32)


async def _put(kind: str, key: str, client_id: str, data: dict, ttl: int) -> None:
    async with SessionLocal() as session:
        session.add(OAuthRecord(kind=kind, key_hash=_hash(key), client_id=client_id, data=data,
                                expires_at=time.time() + ttl))
        await session.commit()


async def _get(kind: str, key: str) -> OAuthRecord | None:
    async with SessionLocal() as session:
        rec = await session.scalar(select(OAuthRecord).where(OAuthRecord.kind == kind,
                                                             OAuthRecord.key_hash == _hash(key)))
        if rec is not None and rec.expires_at < time.time():
            await session.delete(rec)
            await session.commit()
            return None
        return rec


async def _delete(kind: str, key: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(OAuthRecord).where(OAuthRecord.kind == kind,
                                                        OAuthRecord.key_hash == _hash(key)))
        await session.execute(delete(OAuthRecord).where(OAuthRecord.expires_at < time.time()))
        await session.commit()


class GoalCoachOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with SessionLocal() as session:
            client = await session.get(OAuthClient, client_id)
            return OAuthClientInformationFull.model_validate(client.info) if client else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        async with SessionLocal() as session:
            session.add(OAuthClient(client_id=client_info.client_id, info=client_info.model_dump(mode="json")))
            await session.commit()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = _new_token()
        await _put("pending", request_id, client.client_id,
                   {"params": params.model_dump(mode="json"), "attempts": 0,
                    "client_name": client.client_name or "an app"}, PENDING_TTL)
        return f"{get_settings().public_url.rstrip('/')}/oauth/login?request={request_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        rec = await _get("code", authorization_code)
        if rec is None or rec.client_id != client.client_id:
            return None
        return AuthorizationCode.model_validate(rec.data)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        await _delete("code", authorization_code.code)  # one-time use
        return await self._issue(client.client_id, authorization_code.scopes, authorization_code.resource,
                                 authorization_code.subject)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        rec = await _get("refresh", refresh_token)
        if rec is None or rec.client_id != client.client_id:
            return None
        return RefreshToken.model_validate({**rec.data, "token": refresh_token})

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        await _delete("refresh", refresh_token.token)  # rotate
        return await self._issue(client.client_id, scopes or refresh_token.scopes, refresh_token.resource,
                                 refresh_token.subject)

    async def load_access_token(self, token: str) -> AccessToken | None:
        rec = await _get("access", token)
        return AccessToken.model_validate({**rec.data, "token": token}) if rec else None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await _delete("access" if isinstance(token, AccessToken) else "refresh", token.token)

    async def exchange_identity_assertion(self, client, params) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "Identity assertion grants are not supported")

    async def _issue(self, client_id: str, scopes: list[str], resource: str | None, subject: str | None) -> OAuthToken:
        access, refresh = _new_token(), _new_token()
        base = {"client_id": client_id, "scopes": scopes, "resource": resource, "subject": subject}
        await _put("access", access, client_id, {**base, "expires_at": int(time.time()) + ACCESS_TTL}, ACCESS_TTL)
        await _put("refresh", refresh, client_id, {**base, "expires_at": int(time.time()) + REFRESH_TTL}, REFRESH_TTL)
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, refresh_token=refresh,
                          scope=" ".join(scopes) if scopes else None)


async def pending_request(request_id: str) -> OAuthRecord | None:
    return await _get("pending", request_id)


async def complete_login(request_id: str, password: str) -> tuple[str | None, str | None]:
    """Check the owner's password for a pending authorization.

    Returns (redirect_url, None) on success or (None, error message) on failure.
    """
    async with SessionLocal() as session:
        rec = await session.scalar(select(OAuthRecord).where(OAuthRecord.kind == "pending",
                                                             OAuthRecord.key_hash == _hash(request_id)))
        if rec is None or rec.expires_at < time.time():
            return None, "This sign-in link has expired. Go back to Claude and connect again."
        email = get_settings().owner_email.lower()
        user = await session.scalar(select(User).where(func.lower(User.email) == email))
        verified = False
        if user is not None:
            verified, _ = PasswordHelper().verify_and_update(password, user.hashed_password)
        if not verified:
            attempts = rec.data.get("attempts", 0) + 1
            if attempts >= MAX_LOGIN_ATTEMPTS:
                await session.delete(rec)
                await session.commit()
                return None, "Too many wrong attempts. Go back to Claude and connect again."
            rec.data = {**rec.data, "attempts": attempts}
            await session.commit()
            return None, "Wrong password."

        params = AuthorizationParams.model_validate(rec.data["params"])
        code = _new_token()
        session.add(OAuthRecord(
            kind="code", key_hash=_hash(code), client_id=rec.client_id, expires_at=time.time() + CODE_TTL,
            data=AuthorizationCode(
                code=code, scopes=params.scopes or [], expires_at=time.time() + CODE_TTL,
                client_id=rec.client_id, code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource, subject=str(user.id),
            ).model_dump(mode="json"),
        ))
        await session.delete(rec)
        await session.commit()
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state), None
