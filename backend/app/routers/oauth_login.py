"""The password page Claude sends you to when you add GoalCoach as a connector."""

import asyncio
from html import escape

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import get_settings
from app.services import oauth

router = APIRouter(prefix="/oauth", tags=["oauth"], include_in_schema=False)

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect GoalCoach</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fafafa; --card:#fff; --text:#18181b; --muted:#71717a; --line:#e4e4e7; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#09090b; --card:#18181b; --text:#f4f4f5; --muted:#a1a1aa; --line:#3f3f46; }} }}
  body {{ margin:0; min-height:100dvh; display:grid; place-items:center; background:var(--bg); color:var(--text);
         font:15px/1.5 -apple-system, system-ui, sans-serif; padding:16px; box-sizing:border-box; }}
  .card {{ width:100%; max-width:360px; background:var(--card); border:1px solid var(--line); border-radius:16px; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }} p {{ color:var(--muted); margin:0 0 20px; }}
  input {{ width:100%; box-sizing:border-box; padding:10px 12px; border-radius:10px; border:1px solid var(--line);
          background:transparent; color:inherit; font-size:16px; }}
  button {{ width:100%; margin-top:12px; padding:10px; border:0; border-radius:10px; background:#4f46e5; color:#fff;
           font-size:15px; font-weight:600; }}
  .err {{ color:#dc2626; margin:12px 0 0; }}
</style></head><body><form class="card" method="post" action="/oauth/login">
<h1>Connect GoalCoach</h1><p>Allow <b>{client}</b> to access your goals and daily logs as <b>{email}</b>.</p>
<input type="hidden" name="request" value="{request}">
<input type="password" name="password" placeholder="GoalCoach password" autocomplete="current-password" autofocus required>
<button type="submit">Allow access</button>{error}</form></body></html>"""


def render(request_id: str, client: str, error: str = "") -> HTMLResponse:
    return HTMLResponse(PAGE.format(
        client=escape(client), email=escape(get_settings().owner_email), request=escape(request_id),
        error=f'<p class="err">{escape(error)}</p>' if error else "",
    ), status_code=400 if error else 200)


@router.get("/login")
async def login_page(request: str):
    pending = await oauth.pending_request(request)
    if pending is None:
        return render(request, "this app", "This sign-in link has expired. Go back to Claude and connect again.")
    return render(request, pending.data.get("client_name", "an app"))


@router.post("/login")
async def login_submit(request: str = Form(...), password: str = Form(...)):
    pending = await oauth.pending_request(request)
    redirect, error = await oauth.complete_login(request, password)
    if redirect:
        return RedirectResponse(redirect, status_code=302)
    await asyncio.sleep(1)  # slow down password guessing
    return render(request, pending.data.get("client_name", "an app") if pending else "this app", error or "")
