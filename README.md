# GoalCoach: AI goal coach & performance tracker

Add your goals. The coach interviews you, builds a roadmap with a timeline, and every night scores your day against your goals:
- which goals you moved,
- what went well and what went badly,
- a time-blocked plan for tomorrow.

It flags when you fall behind and proposes a replan. It also surfaces new developments relevant to what you're studying, such as a new RAG technique while you're on the RAG phase.

- **Backend**: FastAPI, SQLAlchemy (async), Postgres, Alembic, fastapi-users (JWT)
- **Frontend**: a read-only dashboard (React, Vite, TypeScript, Tailwind, TanStack Query, Recharts). It installs as a PWA with push reminders that open Claude. Coaching itself happens in Claude through the MCP server.
- **Coach**: Claude, through the MCP server. The app has no model of its own and uses simple rules where it acts alone.

## How progress is proven

Each roadmap item has a proof type:
- **Interview (knowledge):** the Study page lists today's topics and subtopics. You learn by questioning Claude, then Claude interviews you, by voice or text. Passing needs 85% overall and at least 4/5 on every core subtopic. Failing brings back only the weak subtopics, and passed topics get re-tests after 3, 7 and 21 days. An item is done only when all its topics pass.
- **Log (physical or habit):** you tell Claude what you did, and it judges that against your routine and measurable targets such as body weight.
- **Deliverable (projects and tasks):** done when the outcome is reported.

## How scoring works

The score is weekly, out of 100, so you can spread your hours however you like. Four hours today and nothing tomorrow is fine.

- **Hours set the ceiling:** hours done against the week's target. Extra hours can't take you past 100%, and low-value work counts for less: relevance, and kinds such as admin.
- **Quality decides how much of it you keep:** Claude's rating of the work, 70% progress on the goal and 30% how well the time was used. The poorest work keeps half of what the hours earned, and the best keeps all of it. Quality scales the hours rather than adding to them, so one great hour in a twelve-hour week still scores low.
- **Wasted time:** minus 1 point per hour, up to 15.

Goals are weighted by priority. While a week is running, the score compares your hours with what was expected up to your last logged day.

Each day still gets a review from Claude: the good, the bad and tomorrow's plan. Its daily rating is only used to spot patterns.

`job` (your day job) and `leisure` are neutral; untagged other time counts as "off-goal" drift.

## Flexible days

Tap a day in the week strip, or tell Claude:

- **Make it a rest day:** the day's open blocks are set aside and its hours come off the week's target, so it can't lower your score. Your roadmap dates don't move, so too many rest days will show up as falling behind.
- **Make it a work day:** a rest day gets a usual day's time and a plan. It can't raise the week's target above your routine's total.
- **Back to normal:** undoes either, and brings set-aside blocks back.

A day with no work only shows as missed if the week is behind. Otherwise it shows as covered.

The Study page shows your next topics, the coming days and the roadmap ahead, and any topic can be started early. Work on a rest day counts toward the week.

## Use with Claude Desktop (local, single user)

Claude acts as the coach. `backend/app/mcp_server.py` is a local MCP server: goals, roadmap, day review, timeline/replan, trends and weekly review. It stores everything in `backend/goalcoach.db` (SQLite) and runs the scheduling and scoring rules. No Gemini key is needed.

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

Paste the generated secrets into `backend/.env`. Then:

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
7. **Email reminder (optional):** create a free [Resend](https://resend.com) account and set `RESEND_API_KEY` on Render. Its default sender only delivers to the Resend account's own email, so use the address you want reminders on. The cron-job.org reminders job sends these emails.
8. **Feed refresh (optional):** a cron-job.org job that POSTs `/jobs/ingest-feeds` once a day, with the same `X-Jobs-Secret` header. Claude also refreshes the feeds itself when they're more than a day old. Weekly reviews and "what's new" are done with Claude, so they aren't scheduled. `.github/workflows/cron.yml` can run any job by hand from the Actions tab (needs repo secrets `API_URL` and `JOBS_SECRET`).

Use one place for your data: once the connector works, remove the local `goalcoach` entry from Claude Desktop's config and use the connector everywhere. The local SQLite file and Neon are separate databases.

## Reminders, your data and status

The app runs its own scheduler inside the web process, so reminders, daily checks and feed updates need only the keep-alive ping. Settings shows whether each part is working. Email needs `RESEND_API_KEY` on Render; the calendar link in Settings works without it.

Download your data from Settings about once a month, and restore it with `scripts/restore_backup.py` if you ever need to. There's deliberately no bulk export endpoint or automatic copy to another service, so your data only leaves the app when you download it.

## Project layout

```
backend/app/
  models.py, schemas.py, main.py
  core/        config, db, auth, encryption
  routers/     goals (+chat, roadmap), entries, plan, replans, trends, reviews, dashboard, settings, jobs
  services/
    llm/       structured output schemas, and a hook tests use for a fake model
    prompts.py intake.py analysis.py scoring.py scheduler.py timeline.py
    roadmap.py weekly.py push.py trends/{feeds,scan}.py
frontend/src/
  pages/       Dashboard, DailyLog, Goals, GoalDetail (chat/roadmap), Trends, Weekly, Settings
  components/  ui, Layout, ReplanBanner
  lib/         api client, types, dates, push
  sw.ts        service worker (precache + push)
```
