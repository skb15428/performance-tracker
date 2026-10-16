import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.auth import UserCreate, UserRead, auth_backend, fastapi_users
from app.core.config import get_settings
from app.routers import dashboard, entries, goals, jobs, oauth_login, plan, replans, reviews, settings, trends
from app.services import oauth as oauth_service

logging.basicConfig(level=logging.INFO)

# Remote MCP (Claude web/mobile): served from the same process at /mcp when PUBLIC_URL is set.
mcp_app = None
if get_settings().public_url:
    from app.mcp_server import mcp

    # Stateless JSON mode: no in-memory sessions to lose when the free instance sleeps or restarts.
    mcp_app = mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if mcp_app is None:
        yield
        return
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="GoalCoach API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
if get_settings().allow_registration:
    app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
for module in (goals, entries, plan, replans, trends, reviews, dashboard, settings, jobs, oauth_login):
    app.include_router(module.router)


@app.get("/health")
async def health():
    return {"ok": True}


AUDITED = ("/register", "/authorize", "/token", "/revoke", "/oauth/", "/.well-known/")


@app.middleware("http")
async def oauth_audit(request: Request, call_next):
    """Log how Claude's connector requests went (path, status, error text, never secrets) for troubleshooting."""
    response = await call_next(request)
    path = request.url.path
    if mcp_app is None or not (path.startswith(AUDITED) or (path == "/mcp" and response.status_code >= 400)):
        return response
    entry = {"method": request.method, "path": path, "status": response.status_code,
             "user_agent": request.headers.get("user-agent", "")[:120],
             "auth_header": request.headers.get("authorization", "").split(" ")[0] or None}
    if response.status_code >= 400 and path in ("/token", "/register", "/authorize"):
        body = b"".join([chunk async for chunk in response.body_iterator])
        entry["error"] = body.decode(errors="replace")[:300]
        response = Response(body, status_code=response.status_code, headers=dict(response.headers),
                            media_type=response.media_type)
    try:
        await oauth_service.audit(entry)
    except Exception:  # never let logging break a login
        logging.getLogger(__name__).exception("audit failed")
    return response


if mcp_app is not None:
    # Must come last: it serves /mcp plus the OAuth endpoints (/.well-known/*, /authorize, /token, /register).
    app.mount("/", mcp_app)
