import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.auth import UserCreate, UserRead, auth_backend, fastapi_users
from app.core.config import get_settings
from app.routers import dashboard, entries, goals, jobs, oauth_login, plan, replans, reviews, settings, trends

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


if mcp_app is not None:
    # Must come last: it serves /mcp plus the OAuth endpoints (/.well-known/*, /authorize, /token, /register).
    app.mount("/", mcp_app)
