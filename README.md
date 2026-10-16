# GoalCoach: AI goal coach & performance tracker

Add your goals. The coach interviews you, builds a roadmap with a timeline, and every night scores your day against your goals:
- which goals you moved,
- what went well and what went badly,
- a time-blocked plan for tomorrow.

It flags when you fall behind and proposes a replan. It also surfaces new developments relevant to what you're studying, such as a new RAG technique while you're on the RAG phase.

- **Backend**: FastAPI, SQLAlchemy (async), Postgres, Alembic, fastapi-users (JWT)
- **Frontend**: a read-only dashboard (React, Vite, TypeScript, Tailwind, TanStack Query, Recharts). It installs as a PWA with push reminders that open Claude. Coaching itself happens in Claude through the MCP server.
- **LLM**: Google Gemini free tier, behind a provider interface (`backend/app/services/llm/`). Every feature falls back to rules when no key is configured or the quota runs out.

## How scoring works

For each goal, on a 0–10 scale:
- **Rule score** = minutes × activity-kind weight × relevance, compared against the goal's share of your daily hours. Your daily hours are split across goals by priority.
- **AI impact** = the LLM's 0–10 judgement of real progress.
- **Goal score** = the average of the two, or the rule score alone without an LLM.

The daily score (0–100) is built from the per-goal scores:
1. Take the priority-weighted average of goal scores.
2. Blend in 20% plan adherence (how much of yesterday's plan you did).
3. Subtract up to 15 points for wasted time.
4. Add up to 5 points for your logging streak.

`job` (your day job) and `leisure` are neutral; untagged other time counts as "off-goal" drift.

## Use with Claude Desktop (local, single user)

Claude acts as the coach. `backend/app/mcp_server.py` is a local MCP server with 21 tools: goals, roadmap, day review, timeline/replan, trends and weekly review. It stores everything in `backend/goalcoach.db` (SQLite) and runs the scheduling and scoring rules. No Gemini key is needed.

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`, then restart Claude Desktop:

```json
"mcpServers": {
  "goalcoach": {
    "command": "/opt/homebrew/bin/uv",
    "args": ["run", "--directory", "/path/to/backend", "python", "-m", "app.mcp_server"]
  }
}
```

In a chat, use the prompts from the **+** menu (Log my day, New goal, What's new for me, Weekly review), or just talk. The account in `OWNER_EMAIL` is created on first use.

To also use the web dashboard on the same data:

```bash
cd backend && uv run python scripts/set_password.py
```

## Run locally

```bash
docker compose up -d                 # Postgres on :5432
```

```bash
cd backend && cp .env.example .env && uv run python scripts/gen_keys.py
```

Paste the generated secrets into `backend/.env`, and add `GEMINI_API_KEY` (free at https://aistudio.google.com/apikey). Then:

```bash
cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
```

```bash
cd frontend && cp .env.example .env && npm install && npm run dev
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

### Tests

```bash
cd backend && uv run pytest
```

This runs against SQLite by default. To run against Postgres, set `TEST_DATABASE_URL=postgresql+asyncpg://goalcoach:goalcoach@localhost:5432/goalcoach_test`. The suite covers:
- scoring, scheduling, timeline and feed parsing,
- a full API flow with a fake LLM: intake → roadmap → nightly log → replan → trends → weekly review,
- the rules-only fallback,
- isolation between users.

## Use from your phone: Render + Neon (free)

The same app serves the web API and a **remote MCP endpoint** at `/mcp`, protected by OAuth. Claude web and mobile connect to it as a custom connector.

1. **Push this repo to GitHub.** It can be private.
2. **Neon:**
   1. Create a free project.
   2. Copy the connection string (`postgresql://…?sslmode=require`).
   3. Create your account there:
      ```bash
      cd backend
      ```
      ```bash
      DATABASE_URL='postgresql://…' uv run alembic upgrade head
      ```
      ```bash
      DATABASE_URL='postgresql://…' OWNER_EMAIL=you@example.com uv run python scripts/set_password.py
      ```
3. **Render:** New → Blueprint → pick the repo (it reads `render.yaml`). Fill in:
   - `DATABASE_URL`: the Neon string
   - `OWNER_EMAIL`: same email as above
   - `PUBLIC_URL`: `https://<service-name>.onrender.com`
   - `FERNET_KEY`: from `uv run python scripts/gen_keys.py`
4. **Claude:**
   1. On claude.ai, open Settings → Connectors → *Add custom connector*.
   2. Enter `https://<service-name>.onrender.com/mcp`.
   3. A GoalCoach page asks for your password; enter it.
   
   The connector then also works in the Claude phone app.
5. **Dashboard on Vercel (free):**
   1. Import the repo with root directory `frontend`.
   2. Set `VITE_API_URL=https://<service-name>.onrender.com`.
   3. Put the Vercel URL in Render's `CORS_ORIGINS`, e.g. `["https://goalcoach.vercel.app"]`.
   4. On your phone, open the Vercel URL and use **Add to Home Screen**.
   5. In Settings, tap **Enable notifications**.
6. **Keep-alive and reminders** (cron-job.org, free):
   - A job that GETs `https://<service-name>.onrender.com/health` every 10 minutes keeps Render awake, so Claude's first call doesn't time out.
   - A job that POSTs `/jobs/send-reminders` every 15 minutes, with header `X-Jobs-Secret: <JOBS_SECRET>`, sends the reminders:
     - the nightly reminder opens Claude with "Log my day" and is skipped on rest days, days off and days you've already logged;
     - the 7 am reminder shows today's plan, built from your routine if needed.
7. **Optional scheduled jobs:** add repo secrets `API_URL` and `JOBS_SECRET` for `.github/workflows/cron.yml`. It runs the feed refresh, timeline checks and weekly review.

Use one place for your data: once the connector works, remove the local `goalcoach` entry from Claude Desktop's config and use the connector everywhere. The local SQLite file and Neon are separate databases.

## Project layout

```
backend/app/
  models.py, schemas.py, main.py
  core/        config, db, auth, encryption
  routers/     goals (+chat, roadmap), entries, plan, replans, trends, reviews, dashboard, settings, jobs
  services/
    llm/       provider interface, Gemini, structured output schemas
    prompts.py intake.py analysis.py scoring.py scheduler.py timeline.py
    roadmap.py weekly.py push.py trends/{feeds,scan}.py
frontend/src/
  pages/       Dashboard, DailyLog, Goals, GoalDetail (chat/roadmap), Trends, Weekly, Settings
  components/  ui, Layout, ReplanBanner
  lib/         api client, types, dates, push
  sw.ts        service worker (precache + push)
```
