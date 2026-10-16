"""Remote MCP over HTTPS + OAuth, the way Claude web/mobile connects: runs the real app under uvicorn."""

import base64
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "test-owner-pass-123"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> tuple[subprocess.Popen, dict]:
    db = Path(tempfile.mkdtemp()) / "remote.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "OWNER_EMAIL": "owner@example.com",
           "PUBLIC_URL": f"http://127.0.0.1:{port}", "GEMINI_API_KEY": ""}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   capture_output=True)
    subprocess.run([sys.executable, "-c", f"""
import asyncio
from fastapi_users.password import PasswordHelper
from app.core.db import SessionLocal
from app.models import User
async def m():
    async with SessionLocal() as s:
        s.add(User(email="owner@example.com", hashed_password=PasswordHelper().hash("{PASSWORD}"),
                   is_active=True, is_verified=True, timezone="Asia/Kolkata"))
        await s.commit()
asyncio.run(m())"""], cwd=BACKEND, env=env, check=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=BACKEND,
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    return proc, env


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def test_remote_mcp_oauth_flow():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc, _ = start_server(port)
    try:
        async with httpx.AsyncClient(base_url=base) as http:
            # Unauthenticated MCP call is refused and points at the resource metadata.
            r = await http.post("/mcp", json={})
            assert r.status_code == 401 and "resource_metadata" in r.headers.get("www-authenticate", "")

            meta = (await http.get("/.well-known/oauth-authorization-server")).json()
            assert meta["registration_endpoint"].endswith("/register")

            client = (await http.post("/register", json={
                "client_name": "Claude", "redirect_uris": [REDIRECT], "grant_types": ["authorization_code",
                "refresh_token"], "response_types": ["code"], "token_endpoint_auth_method": "none"})).json()
            verifier, challenge = pkce()
            r = await http.get("/authorize", params={
                "response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT,
                "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
                "resource": f"{base}/mcp"})
            assert r.status_code in (302, 307)
            login_url = r.headers["location"]
            request_id = parse_qs(urlparse(login_url).query)["request"][0]
            page = await http.get(login_url)
            assert "Connect GoalCoach" in page.text and "Claude" in page.text

            bad = await http.post("/oauth/login", data={"request": request_id, "password": "nope"})
            assert bad.status_code == 400 and "Wrong password" in bad.text

            ok = await http.post("/oauth/login", data={"request": request_id, "password": PASSWORD})
            assert ok.status_code == 302
            callback = parse_qs(urlparse(ok.headers["location"]).query)
            assert callback["state"] == ["xyz"]
            # A second click / back button sends the user on to Claude again instead of "expired"
            again_click = await http.post("/oauth/login", data={"request": request_id, "password": PASSWORD})
            assert again_click.status_code == 302 and again_click.headers["location"] == ok.headers["location"]

            token = (await http.post("/token", data={
                "grant_type": "authorization_code", "code": callback["code"][0], "redirect_uri": REDIRECT,
                "client_id": client["client_id"], "code_verifier": verifier})).json()
            assert token["access_token"] and token["refresh_token"]

            # The code is single use.
            again = await http.post("/token", data={
                "grant_type": "authorization_code", "code": callback["code"][0], "redirect_uri": REDIRECT,
                "client_id": client["client_id"], "code_verifier": verifier})
            assert again.status_code == 400

            refreshed = (await http.post("/token", data={
                "grant_type": "refresh_token", "refresh_token": token["refresh_token"],
                "client_id": client["client_id"]})).json()
            assert refreshed["access_token"] != token["access_token"]

        # Use the MCP tools with the bearer token, like Claude does.
        auth = {"Authorization": f"Bearer {refreshed['access_token']}"}
        async with httpx2.AsyncClient(headers=auth, timeout=30) as h2, \
                streamable_http_client(f"{base}/mcp", http_client=h2) as (read, write), \
                ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert "save_day_review" in names
            result = await session.call_tool("create_goal", {"title": "Ship my micro-SaaS", "priority": 3})
            assert not result.is_error
            overview = await session.call_tool("get_overview", {})
            assert "Ship my micro-SaaS" in overview.content[0].text

        # The regular web API keeps working alongside.
        assert httpx.get(f"{base}/health").json() == {"ok": True}
    finally:
        proc.terminate()
        proc.wait(timeout=10)
