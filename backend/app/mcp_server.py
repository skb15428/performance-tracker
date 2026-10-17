"""GoalCoach as a local MCP server: Claude (in Claude Desktop) is the coach, this server is its memory and maths.

Claude does the thinking (interviews, roadmaps, day reviews, replans, what's new); these tools store the results
and run the rule-based parts (scheduling, scoring, timeline tracking). Single user: everything happens as the
account in OWNER_EMAIL, created on first use.

Run: uv run --directory backend python -m app.mcp_server
"""

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from alembic import command
from alembic.config import Config
from fastapi_users.password import PasswordHelper
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, get_settings
from app.core.db import SessionLocal
from app.models import (
    Activity,
    ActivityLink,
    DailyEntry,
    DailyReview,
    Goal,
    PlanItem,
    ReplanProposal,
    RoadmapItem,
    RoadmapPhase,
    TrendItem,
    TrendSource,
    TrendSuggestion,
    User,
    WeeklyReview,
)
from app.routers.goals import goal_out
from app.services import analysis, commitment, roadmap, timeline, weekly
from app.services.llm.outputs import DayAnalysis, PlanDetails, ReplanDraft, Resource, RoadmapDraft
from app.services.push import local_now
from app.services.trends.feeds import USER_SOURCE_WEIGHT, ensure_default_sources, ingest_all
from app.services.trends.scan import rank_candidates, search_terms

INSTRUCTIONS = """GoalCoach tracks the user's goals, roadmaps and daily work. You are their coach: honest, specific,
encouraging. Their goals are ambitious (e.g. a strong role at an AI company, or becoming self-employed).

Always start a conversation with get_overview. Never invent ids; use the ids the tools return.
DURING THE DAY: if the user asks what to do today, or today_plan_missing is true, call plan_day and fill in each
block's short title and details (why, steps, resources, done_when) with edit_plan. Use edit_plan whenever their day
changes; set_plan_item_status as they finish blocks.
If get_overview lists unlogged_days, briefly offer to log them (a quick summary is enough; if they don't remember or
took the day off, save it with day_off=True). Don't nag more than once per conversation.

NEW GOAL = an intake loop with 3 checkpoints the user must explicitly agree to (call get_intake_status any time to
see what's missing; a goal is only tracked and scored once all three are confirmed). Keep chatting until each is
settled; never confirm a checkpoint without a clear "yes" from the user.
 1. EXACT GOAL: create_goal, then interview (1-3 questions at a time): current level/skills, constraints, why it
    matters, and what success concretely looks like. Store facts with save_goal_facts. Propose one specific,
    measurable goal statement + 2-4 success criteria (e.g. "AI Engineer offer at an AI-first company, >= X salary,
    by June 2027"). Refine until the user agrees -> confirm_goal_definition.
 2. ROADMAP: draft 3-7 phases with 2-8 items each (topics to study, skills to practise, tasks/projects, milestones;
    honest est_hours; 1-3 quality resources). Walk the user through it, change what they want, and when they
    approve -> set_roadmap. Then call set_search_terms with search terms for each item (specific phrases and
    synonyms) and 3-5 watch topics for the goal beyond the roadmap (e.g. for a career goal: job requirements,
    interview formats, tools in job posts); mention the watch topics so the user can adjust them.
 3. TIMELINE + DAILY COMMITMENT (agree together, they depend on each other): ask by when they want it and how much
    time they can give on a working day and how many days a week. Call propose_commitment to show the trade-off
    (finish date for each pace, hours/day needed for their date, and whether it fits with their other goals).
    Agree on hours/day, days/week and a target date, then design a weekly routine of time blocks (which days,
    start-end, what kind of work: e.g. Mon-Fri 07:00-08:30 study roadmap topic, Sat 10:00-13:00 build project).
    Give each block a focus: learn (topics/skills), build (tasks/milestones like projects and applications) or
    any. Learn and build blocks advance different items in parallel within a phase (phases still run in order),
    so if the user wants to build while learning, put a project task in the early phases.
    Show it; when the user agrees -> confirm_commitment. That activates the goal and dates the roadmap. If it warns
    that blocks overlap with another goal's routine, sort it out with the user and confirm again.
Then summarise the agreed plan: goal, roadmap phases with dates, routine, target date.
If the user later wants to change the goal, roadmap or commitment, repeat that checkpoint.

NIGHTLY REVIEW: call get_day_context(date). If the user hasn't described their day, ask for it (time blocks + notes).
Ask which of the day's planned blocks they did: done, partly (how many minutes) or skipped.
Steps they ticked in the dashboard show as details.steps[].done in plan_for_this_day; use them. Then analyse: split into activities (kind: learn/build/ship/network/
apply/admin/job/leisure/waste/other; day job = job, rest/meals/family/exercise = leisure, doom-scrolling = waste),
link each to the goal(s) and roadmap item it advanced (relevance 0-1, reason), rate each goal's progress 0-10
(calibrated: 2-4 is a normal light day), credit hours to roadmap items, list 2-4 went_well and went_badly points,
write tomorrow's time-blocked plan by filling each goal's routine_tomorrow blocks with the next/overdue roadmap
items (if a goal has no routine, fit its planned_minutes_tomorrow). Make every block concrete and easy to follow: a short title (max ~8 words) plus details:
why (one sentence linking it to the goal), 2-5 ordered steps with minutes that add up to the block, 1-3 resources
with real links, and done_when (a checkable finish line, e.g. "your output matches PyTorch on a 4-token example").
Before saving, ask if tomorrow is different (meetings, travel) and adjust. Then
one tip. Call save_day_review and present the score with its one-line score_explanation, the score per goal, the
good/bad points and tomorrow's plan. A rest day has no score: just acknowledge it and show tomorrow's plan.
If it returns items_over_estimate, ask whether each is done or how many more hours it needs, then call
update_roadmap_item (status="done", or est_hours = logged + extra) with reschedule=True and mention any date change.

FALLING BEHIND: save_day_review returns timeline_alerts; if there are any, mention them in one line at the end and
offer to look at it (once, don't lecture). When the user wants to, call get_timeline and follow its diagnosis: the
likely cause decides the fix (re-estimate overrunning items / agree a smaller realistic routine with
confirm_commitment / shift or reduce_scope via preview_replan / for goals that are ahead, an earlier target or a
stretch item). Show the forecast at their actual pace vs the target. Apply changes only after the user agrees
(resolve_replan for proposals).

WHAT'S NEW: call get_trend_candidates for the goal (refresh_feeds first if feeds_stale). If current items lack
search terms, set them with set_search_terms first. Also do your own web search on the current items and watch
topics (last few weeks). Pick at most 3 genuinely new and useful things (skip hype and anything in
previously_suggested), call record_trend_suggestions, and present each with why it matters, the link, the hours, and
the finish-date effect it returns. Then resolve_trend_suggestion add/dismiss per the user's answer.
If get_overview shows trends_check_due for a goal, offer once: "Want me to check what's new for <goal>?"
The user can add their own sources (newsletters, blogs, GitHub topics) with manage_sources.

WEEKLY REVIEW: if get_overview shows weekly_review_due_for_week, offer it once. Call get_weekly_stats for that
week. Start by following up last_week_focus: ask (or infer from the stats) whether each was kept. Then write a candid
review: compare with the previous week and the 4-week trend, show each goal's hours vs committed hours, and point out
the 1-2 patterns that matter most (e.g. evening blocks rarely get done, Mondays are weak, low energy follows late
scrolling). Recommendations must be concrete actions. Offer to turn the ones the user accepts into real changes now
(routine tweak via confirm_commitment, replan, plan edits), and agree 1-3 short, checkable focus points for next
week. Save with save_weekly_review (focus, last_week_focus_kept).
DASHBOARD: when the user asks to see their progress, stats or a dashboard, call get_dashboard and draw 2-4 clear
charts right in the chat (e.g. weekly hours vs planned per goal, score trend, plan-done % by week), then give a 2-3
line takeaway.
In the nightly review, if weekly_focus is set, briefly check the day against it (one line, no lecture)."""

def _remote_auth() -> dict:
    """When PUBLIC_URL is set (cloud deploy) the server is also reachable over HTTPS and requires OAuth."""
    public_url = get_settings().public_url.rstrip("/")
    if not public_url:
        return {}
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

    from app.services.oauth import GoalCoachOAuthProvider

    return {
        "auth_server_provider": GoalCoachOAuthProvider(),
        "auth": AuthSettings(
            issuer_url=public_url,
            resource_server_url=f"{public_url}/mcp",
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
            validate_token_resource=False,  # tokens are only ever issued for this server
        ),
    }


mcp = MCPServer("GoalCoach", instructions=INSTRUCTIONS, **_remote_auth())
_schema_ready = False


# ---------------------------------------------------------------- helpers

def _system_timezone() -> str:
    try:
        path = os.readlink("/etc/localtime")
        return path.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


@asynccontextmanager
async def owner_session():
    """Yield (session, owner user); creates tables/owner on first use and commits at the end."""
    global _schema_ready
    if not _schema_ready:
        # Bring the database up to date (creates backend/goalcoach.db on first run). Alembic's env runs its own
        # event loop, so do it in a worker thread.
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        await asyncio.to_thread(command.upgrade, cfg, "head")
        _schema_ready = True
    async with SessionLocal() as session:
        email = get_settings().owner_email.lower()
        user = await session.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            user = User(
                email=email,
                hashed_password=PasswordHelper().hash(secrets.token_urlsafe(32)),
                is_active=True,
                is_verified=True,
                timezone=_system_timezone(),
            )
            session.add(user)
            await session.flush()
        yield session, user
        await session.commit()


def today_for(user: User) -> date:
    return local_now(user.timezone).date()


def parse_day(value: str | None, user: User) -> date:
    return date.fromisoformat(value) if value else today_for(user)


async def get_goal(session: AsyncSession, user: User, goal_id: int) -> Goal:
    goal = await roadmap.load_goal(session, goal_id, user.id)
    if goal is None:
        raise ToolError(f"No goal with id {goal_id}. Call get_overview to see goal ids.")
    return goal


async def get_item(session: AsyncSession, user: User, item_id: int) -> RoadmapItem:
    item = await session.scalar(
        select(RoadmapItem).join(RoadmapPhase).join(Goal).where(RoadmapItem.id == item_id, Goal.user_id == user.id)
    )
    if item is None:
        raise ToolError(f"No roadmap item with id {item_id}.")
    return item


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def item_view(i: RoadmapItem, with_details: bool = True) -> dict:
    view = {"id": i.id, "type": i.type, "title": i.title, "status": i.status, "est_hours": i.est_hours,
            "hours_logged": round(i.hours_logged, 2), "planned_start": iso(i.planned_start),
            "planned_due": iso(i.planned_due), "source": i.source}
    if over_estimate(i):
        view["over_estimate"] = True
    if with_details:
        view["description"] = i.description
        view["resources"] = i.resources
    return view


def over_estimate(i: RoadmapItem) -> bool:
    return i.status in roadmap.OPEN_STATUSES and i.hours_logged >= i.est_hours


def roadmap_view(goal: Goal, with_details: bool = False) -> list[dict]:
    return [{"phase_id": p.id, "title": p.title, "start": iso(p.start_date), "due": iso(p.due_date),
             "items": [item_view(i, with_details) for i in p.items]} for p in goal.phases]


def feasibility_view(f) -> dict:
    return {"feasible": f.feasible, "realistic_finish": iso(f.realistic_date),
            "required_hours_per_day_for_target": f.required_hours_per_day}


def intake_checklist(goal: Goal) -> dict:
    steps = [
        ("goal_definition", goal.definition_agreed_at,
         "Agree an exact, measurable goal statement + success criteria, then call confirm_goal_definition."),
        ("roadmap", goal.roadmap_agreed_at, "Draft the roadmap, get the user's approval, then call set_roadmap."),
        ("timeline_and_daily_commitment", goal.commitment_agreed_at,
         "Use propose_commitment to agree target date + hours/day + days/week, design a weekly routine, "
         "then call confirm_commitment."),
    ]
    missing = [(name, hint) for name, done, hint in steps if done is None]
    return {
        "checkpoints": {name: done is not None for name, done, _ in steps},
        "complete": not missing,
        "next_step": missing[0][1] if missing else "Intake complete; the goal is active and tracked.",
    }


def refresh_intake_status(goal: Goal) -> None:
    if goal.definition_agreed_at and goal.roadmap_agreed_at and goal.commitment_agreed_at:
        goal.intake_status = "active"
    elif goal.roadmap_agreed_at:
        goal.intake_status = "commitment_pending"
    elif goal.intake_status != "active":  # goals activated in the web app stay active
        goal.intake_status = "interviewing"


def commitment_view(goal: Goal) -> dict | None:
    if not roadmap.has_commitment(goal):
        return None
    return {"hours_per_day": goal.hours_per_day, "days_per_week": goal.days_per_week,
            "weekly_hours": round(goal.hours_per_day * goal.days_per_week, 2), "routine": goal.routine}


async def goal_summary(session: AsyncSession, user: User, goal: Goal) -> dict:
    out = await goal_out(session, user, goal)
    data = out.model_dump(mode="json", exclude={"proposed_roadmap", "created_at"})
    data["pace_hours_per_calendar_day"] = round(await roadmap.goal_hours_per_day(session, user, goal), 2)
    data["statement"] = goal.statement
    data["success_criteria"] = goal.success_criteria
    data["commitment"] = commitment_view(goal)
    data["intake"] = intake_checklist(goal)
    checked = goal.trends_checked_at
    if checked is not None and checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    data["trends_last_checked"] = checked.date().isoformat() if checked else None
    data["trends_check_due"] = goal.intake_status == "active" and (
        checked is None or datetime.now(timezone.utc) - checked > timedelta(days=7))
    return data


# ---------------------------------------------------------------- overview & settings

async def unlogged_days(session: AsyncSession, user: User, goals: list[Goal], logged: set[date],
                        today: date) -> list[str]:
    """Working days in the last week (since the user started tracking) with no review."""
    tracked = [g for g in goals if g.status == "active" and g.intake_status == "active"]
    if not tracked:
        return []
    started = min(local_now(user.timezone, g.created_at if g.created_at.tzinfo
                            else g.created_at.replace(tzinfo=timezone.utc)).date() for g in tracked)
    rest_wd = analysis.rest_weekdays(tracked)
    days = [today - timedelta(days=n) for n in range(7, 0, -1)]
    return [d.isoformat() for d in days if d >= started and d not in logged and d.weekday() not in rest_wd]

@mcp.tool()
async def get_overview() -> dict:
    """Start here. The user's settings, today's date, all goals (priority, progress %, timeline status, hours/day
    share), whether today is logged, today's plan, recent scores and pending replan proposals."""
    async with owner_session() as (session, user):
        today = today_for(user)
        goals = list(await session.scalars(select(Goal).where(Goal.user_id == user.id).order_by(Goal.id)))
        recent = list(await session.execute(
            select(DailyEntry.date, DailyReview.total_score, DailyReview.rest_day).join(DailyReview)
            .where(DailyEntry.user_id == user.id, DailyEntry.date >= today - timedelta(days=7))
            .order_by(DailyEntry.date)
        ))
        pending = list(await session.scalars(
            select(ReplanProposal).join(Goal).where(Goal.user_id == user.id, ReplanProposal.status == "pending")
        ))
        plan = await analysis.plan_for(session, user.id, today)
        unlogged = await unlogged_days(session, user, goals, {r.date for r in recent}, today)
        return {
            "today": today.isoformat(),
            "weekday": today.strftime("%A"),
            "settings": {"name": user.name, "timezone": user.timezone,
                         "daily_available_hours": user.daily_available_hours},
            "goals": [await goal_summary(session, user, g) for g in goals],
            "today_logged": any(r.date == today for r in recent),
            "streak_days": await analysis.streak_before(session, user.id, today)
            + (1 if any(r.date == today for r in recent) else 0),
            "recent_scores": [{"date": r.date.isoformat(), "score": None if r.rest_day else r.total_score,
                               "rest_day": r.rest_day} for r in recent],
            "unlogged_days": unlogged,
            "weekly_review_due_for_week": await weekly_review_due(session, user, today),
            "weekly_focus": await weekly.current_focus(session, user, today),
            "today_plan": plan_view(plan),
            "today_plan_missing": not plan and bool(await analysis.rule_plan(session, user, today)),
            "pending_replans": [{"id": p.id, "goal_id": p.goal_id, "reason": p.reason} for p in pending],
        }


@mcp.tool()
async def update_settings(daily_available_hours: float | None = None, timezone_name: str | None = None,
                          name: str | None = None) -> dict:
    """Change how many hours per day the user can spend on goals (split across goals by priority), their IANA
    timezone (e.g. Asia/Kolkata) or name."""
    async with owner_session() as (session, user):
        if daily_available_hours is not None:
            user.daily_available_hours = daily_available_hours
        if timezone_name:
            user.timezone = timezone_name
        if name is not None:
            user.name = name
        return {"name": user.name, "timezone": user.timezone, "daily_available_hours": user.daily_available_hours}


# ---------------------------------------------------------------- goals & roadmap

@mcp.tool()
async def create_goal(title: str, description: str = "", why: str = "",
                      category: Literal["career", "venture", "learning", "health", "other"] = "other",
                      priority: int = Field(default=3, ge=1, le=5), target_date: str | None = None) -> dict:
    """Create a goal. Then interview the user and build its roadmap with set_roadmap. target_date: YYYY-MM-DD."""
    async with owner_session() as (session, user):
        goal = Goal(user_id=user.id, title=title, description=description, why=why, category=category,
                    priority=priority, target_date=date.fromisoformat(target_date) if target_date else None,
                    context={}, phases=[])
        session.add(goal)
        await session.flush()
        return {"goal_id": goal.id, "title": goal.title, "intake": intake_checklist(goal)}


@mcp.tool()
async def update_goal(goal_id: int, title: str | None = None, description: str | None = None,
                      why: str | None = None, priority: int | None = None, target_date: str | None = None,
                      status: Literal["active", "paused", "done"] | None = None) -> dict:
    """Edit a goal's details, priority (1-5), target date (YYYY-MM-DD) or status."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        for field, value in {"title": title, "description": description, "why": why, "priority": priority,
                             "status": status}.items():
            if value is not None:
                setattr(goal, field, value)
        if target_date is not None:
            goal.target_date = date.fromisoformat(target_date) if target_date else None
        return await goal_summary(session, user, goal)


@mcp.tool()
async def save_goal_facts(goal_id: int, facts: dict[str, str]) -> dict:
    """Remember facts learned about the user for this goal (e.g. {"experience": "5y backend", "hours_per_day": "2"}).
    Merged with existing facts."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        goal.context = {**(goal.context or {}), **facts}
        return {"goal_id": goal.id, "facts": goal.context}


@mcp.tool()
async def set_roadmap(goal_id: int, roadmap_draft: RoadmapDraft, target_date: str | None = None) -> dict:
    """Intake checkpoint 2. Save the roadmap the user approved (replaces the current one; progress on items with the
    same title is kept) and schedule it from today. Only call after the user agreed to this roadmap. Dates use a
    provisional pace until the daily commitment is confirmed."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        feas = await roadmap.approve_draft(session, user, goal, roadmap_draft,
                                           date.fromisoformat(target_date) if target_date else None, today_for(user),
                                           activate=False)
        goal.roadmap_agreed_at = datetime.now(timezone.utc)
        refresh_intake_status(goal)
        await session.flush()
        total = sum(i.est_hours for i in roadmap.ordered_items(goal) if i.status != "skipped")
        return {"goal": await goal_summary(session, user, goal), "total_hours": round(total, 1),
                "feasibility": feasibility_view(feas), "phases": roadmap_view(goal)}


@mcp.tool()
async def confirm_goal_definition(goal_id: int, statement: str, success_criteria: list[str],
                                  title: str | None = None, priority: int | None = None,
                                  category: Literal["career", "venture", "learning", "health", "other"] | None = None
                                  ) -> dict:
    """Intake checkpoint 1. Save the exact, measurable goal statement and success criteria the user agreed to
    (optionally a sharper title / priority / category). Only call after the user said yes to this wording."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        goal.statement, goal.success_criteria = statement, success_criteria
        for field, value in {"title": title, "priority": priority, "category": category}.items():
            if value is not None:
                setattr(goal, field, value)
        goal.definition_agreed_at = datetime.now(timezone.utc)
        refresh_intake_status(goal)
        return {"goal_id": goal.id, "statement": goal.statement, "success_criteria": goal.success_criteria,
                "intake": intake_checklist(goal)}


@mcp.tool()
async def get_intake_status(goal_id: int) -> dict:
    """Which intake checkpoints (goal definition, roadmap, timeline + daily commitment) are agreed, and what to do next.
    Use it to resume an unfinished goal setup."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        return {"goal_id": goal.id, "title": goal.title, "statement": goal.statement,
                "commitment": commitment_view(goal), "target_date": iso(goal.target_date),
                **intake_checklist(goal)}


async def capacity(session: AsyncSession, user: User, goal: Goal, weekly_hours_for_goal: float) -> dict:
    others = [g for g in await analysis.load_goals_with_items(session, user)
              if g.id != goal.id and roadmap.has_commitment(g)]
    other_weekly = sum(g.hours_per_day * g.days_per_week for g in others)
    available = user.daily_available_hours * 7
    total = other_weekly + weekly_hours_for_goal
    return {"available_hours_per_week": round(available, 1),
            "other_goals_hours_per_week": round(other_weekly, 1),
            "this_goal_hours_per_week": round(weekly_hours_for_goal, 1),
            "fits": total <= available + 1e-9,
            "over_by_hours_per_week": round(max(total - available, 0), 1)}


@mcp.tool()
async def propose_commitment(goal_id: int, target_date: str | None = None, hours_per_day: float | None = None,
                             days_per_week: int = Field(default=6, ge=1, le=7)) -> dict:
    """Intake checkpoint 3 helper (saves nothing). Shows the trade-off between time per day and finish date for the
    goal's remaining roadmap work: the finish date at the given pace, the hours/day needed to hit target_date, a menu
    of paces, and whether it fits the user's available time alongside their other goals' commitments."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        today = today_for(user)
        remaining = sum(roadmap.remaining_hours(i) for i in roadmap.ordered_items(goal)
                        if i.status in roadmap.OPEN_STATUSES)
        target = date.fromisoformat(target_date) if target_date else goal.target_date
        out: dict = {"remaining_roadmap_hours": round(remaining, 1), "target_date": iso(target)}
        if target:
            out["hours_per_day_needed_for_target"] = {
                f"{dpw}_days_per_week": commitment.required_hours_per_day(remaining, today, target, dpw)
                for dpw in (5, 6, 7)}
        if hours_per_day:
            fin = commitment.finish_date(remaining, today, hours_per_day, days_per_week)
            out["at_your_pace"] = {"hours_per_day": hours_per_day, "days_per_week": days_per_week,
                                   "finish_date": iso(fin), "meets_target": fin <= target if target else None}
            out["capacity"] = await capacity(session, user, goal, hours_per_day * days_per_week)
        out["options"] = [{"hours_per_day": o.hours_per_day, "days_per_week": o.days_per_week,
                           "weekly_hours": o.weekly_hours, "finish_date": iso(o.finish),
                           "meets_target": o.meets_target}
                          for o in commitment.options(remaining, today, target)]
        return out


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def routine_clashes(goal: Goal, blocks: list[dict], goals: list[Goal]) -> list[str]:
    """Time blocks that overlap within this routine or with other active goals' routines."""
    labelled = [(goal.title, b) for b in blocks] + [
        (g.title, b) for g in goals if g.id != goal.id and g.status == "active" for b in (g.routine or [])]
    clashes = []
    for i, (title_a, a) in enumerate(labelled[: len(blocks)]):
        for title_b, b in labelled[i + 1:]:
            days = sorted(set(a["days"]) & set(b["days"]), key=commitment.WEEKDAYS.index)
            if days and _minutes(a["start"]) < _minutes(b["end"]) and _minutes(b["start"]) < _minutes(a["end"]):
                clashes.append(f"'{title_a}' {a['start']}-{a['end']} overlaps '{title_b}' {b['start']}-{b['end']} "
                               f"on {', '.join(days)}. Move one of them.")
    return clashes


class RoutineBlock(BaseModel):
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
    start: str = Field(description="HH:MM")
    end: str = Field(description="HH:MM")
    activity: str = Field(description="What kind of work, e.g. 'Study current roadmap topic', 'Build project'")
    focus: Literal["learn", "build", "any"] = Field(
        default="any", description="learn = topics/skills, build = tasks/milestones (project work, applications), "
                                   "any = next item in order. Learn and build blocks advance items in parallel.")


@mcp.tool()
async def confirm_commitment(goal_id: int, target_date: str, routine: list[RoutineBlock]) -> dict:
    """Intake checkpoint 3. Save the timeline and daily commitment the user agreed to: target date (YYYY-MM-DD) and
    the weekly routine of time blocks (the routine defines the commitment: hours per day and days per week are
    derived from it). Only call after the user said yes. Activates the goal (if the definition and roadmap are
    agreed) and re-dates the roadmap at this pace. Also use it to change an existing commitment."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        blocks = [b.model_dump() for b in routine]
        if not blocks or any(commitment.block_minutes(b["start"], b["end"]) <= 0 or not b["days"] for b in blocks):
            raise ToolError("Give at least one routine block; each needs days and a start before its end (HH:MM).")
        days_per_week = len({d for b in blocks for d in b["days"]})
        weekly = commitment.routine_weekly_minutes(blocks) / 60
        goal.target_date = date.fromisoformat(target_date)
        goal.hours_per_day, goal.days_per_week, goal.routine = round(weekly / days_per_week, 2), days_per_week, blocks
        goal.commitment_agreed_at = datetime.now(timezone.utc)
        refresh_intake_status(goal)
        feas = await roadmap.reschedule(session, user, goal, today_for(user))
        await session.flush()

        warnings = routine_clashes(goal, blocks, await analysis.load_goals_with_items(session, user))
        cap = await capacity(session, user, goal, weekly)
        if not cap["fits"]:
            warnings.append(f"All goals together exceed the user's available time by {cap['over_by_hours_per_week']}h"
                            "/week. Consider raising daily_available_hours (update_settings) or lowering a goal.")
        if not feas.feasible:
            warnings.append(f"At this pace the roadmap finishes {iso(feas.realistic_date)}, after the target date.")
        return {"goal": await goal_summary(session, user, goal), "feasibility": feasibility_view(feas),
                "capacity": cap, "warnings": warnings, "phases": roadmap_view(goal)}


@mcp.tool()
async def get_roadmap(goal_id: int, include_details: bool = False) -> dict:
    """A goal's roadmap: phases and items with ids, status, estimated vs logged hours and planned dates.
    include_details adds descriptions and resources."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        return {"goal": await goal_summary(session, user, goal), "facts": goal.context,
                "phases": roadmap_view(goal, include_details)}


@mcp.tool()
async def add_roadmap_item(goal_id: int, title: str, est_hours: float = 2, description: str = "",
                           type: Literal["topic", "skill", "task", "milestone"] = "topic",
                           resources: list[Resource] | None = None, phase_id: int | None = None,
                           source: Literal["user", "trend", "ai"] = "user", preview: bool = False) -> dict:
    """Add an item to a goal's roadmap and reschedule. Without phase_id it goes right after the current item so it
    is worked on soon. preview=True only shows how the finish date would change, without adding anything."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        if preview:
            capacity = roadmap.capacity_for(goal, await roadmap.goal_hours_per_day(session, user, goal))
            before, after = roadmap.finish_with_extra(goal, today_for(user), capacity, est_hours, type)
            return {"finish_now": iso(before), "finish_if_added": iso(after), "target_date": iso(goal.target_date)}
        item = RoadmapItem(type=type, title=title, description=description, est_hours=est_hours,
                           resources=[r.model_dump() for r in resources or []], source=source)
        if phase_id is None:
            roadmap.insert_after_current(goal, item)
        else:
            phase = next((p for p in goal.phases if p.id == phase_id), None)
            if phase is None:
                raise ToolError(f"Phase {phase_id} is not part of goal {goal_id}.")
            item.order = len(phase.items)
            phase.items.append(item)
        goal.intake_status = "active"
        await session.flush()
        feas = await roadmap.reschedule(session, user, goal, today_for(user))
        return {"item": item_view(item), "feasibility": feasibility_view(feas)}


@mcp.tool()
async def update_roadmap_item(item_id: int, status: Literal["todo", "in_progress", "done", "skipped"] | None = None,
                              title: str | None = None, description: str | None = None,
                              est_hours: float | None = None, hours_logged: float | None = None,
                              reschedule: bool = False) -> dict:
    """Edit a roadmap item (mark done/skipped, fix estimates, correct logged hours). For an item that ran over its
    estimate, ask the user whether it's done or how many more hours it needs, then set status="done" or
    est_hours = hours_logged + extra. reschedule=True re-dates the goal's remaining items afterwards (the finish
    date may move; tell the user)."""
    async with owner_session() as (session, user):
        item = await get_item(session, user, item_id)
        for field, value in {"title": title, "description": description, "est_hours": est_hours,
                             "hours_logged": hours_logged}.items():
            if value is not None:
                setattr(item, field, value)
        if status is not None:
            item.status = status
            item.completed_at = today_for(user) if status == "done" else None
        out = {}
        if reschedule or status == "skipped":
            goal = await roadmap.load_goal(session, (await session.get(RoadmapPhase, item.phase_id)).goal_id, user.id)
            feas = await roadmap.reschedule(session, user, goal, today_for(user))
            out["feasibility"] = feasibility_view(feas)
        return {"item": item_view(item), **out}  # after rescheduling, so the dates are current


@mcp.tool()
async def reschedule_goal(goal_id: int) -> dict:
    """Recompute dates for all unfinished items of a goal from today using the current hours/day."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        feas = await roadmap.reschedule(session, user, goal, today_for(user))
        return {"feasibility": feasibility_view(feas), "phases": roadmap_view(goal)}


# ---------------------------------------------------------------- daily review

class ScheduleBlock(BaseModel):
    start: str = Field(default="", description="HH:MM")
    end: str = Field(default="", description="HH:MM")
    activity: str


class PlanStatus(BaseModel):
    plan_item_id: int
    status: Literal["done", "partial", "skipped", "open"]
    done_minutes: int | None = Field(default=None, description="For partial: minutes of the block actually done")


@mcp.tool()
async def get_day_context(day: str | None = None) -> dict:
    """Everything needed to review a day (default today, YYYY-MM-DD): active goals with ids, priority, hours/day
    and timeline status; the roadmap items in focus (in progress, overdue, next up); the plan that was set for that
    day (with ids, to mark done/skipped); and any review already saved for it."""
    async with owner_session() as (session, user):
        d = parse_day(day, user)
        goals = await analysis.load_goals_with_items(session, user)
        goal_views = []
        for g in goals:
            st = await timeline.goal_status(session, user, g, d)
            tomorrow = d + timedelta(days=1)
            goal_views.append({
                "goal_id": g.id, "title": g.title, "priority": g.priority, "intake_complete": g.intake_status == "active",
                "planned_minutes_today": await roadmap.goal_target_minutes(session, user, g, d),
                "routine_today": commitment.routine_blocks_on(g.routine, d),
                "planned_minutes_tomorrow": await roadmap.goal_target_minutes(session, user, g, tomorrow),
                "routine_tomorrow": commitment.routine_blocks_on(g.routine, tomorrow),
                "timeline": st.state, "behind_days": st.behind_days,
                "focus_items": [item_view(i, False) for i in analysis.focus_items(g, d, limit=5)],
            })
        plan = await analysis.plan_for(session, user.id, d)
        entry = await session.scalar(select(DailyEntry).where(DailyEntry.user_id == user.id, DailyEntry.date == d))
        existing = None
        if entry and entry.review:
            r = entry.review
            existing = {"score": None if r.rest_day else r.total_score, "rest_day": r.rest_day,
                        "score_explanation": (r.breakdown or {}).get("explanation"),
                        "went_well": r.went_well, "went_badly": r.went_badly,
                        "schedule": entry.schedule, "notes": entry.free_text}
        return {
            "date": d.isoformat(), "weekday": d.strftime("%A"),
            "daily_available_hours": user.daily_available_hours,
            "weekly_focus": await weekly.current_focus(session, user, d),
            "goals": goal_views,
            "plan_for_this_day": [{"plan_item_id": p.id, "time_block": p.time_block, "title": p.title,
                                   "minutes": p.minutes, "goal_id": p.goal_id, "status": p.status,
                                   "done_minutes": p.done_minutes} for p in plan],
            "existing_review": existing,
        }


@mcp.tool()
async def save_day_review(review: DayAnalysis, day: str | None = None, schedule: list[ScheduleBlock] | None = None,
                          notes: str = "", energy: int | None = Field(default=None, ge=1, le=5),
                          plan_status: list[PlanStatus] | None = None, day_off: bool = False) -> dict:
    """Save your review of the user's day (default today) and score it. `review` holds the activities with goal /
    roadmap-item links, goal_impacts (0-10 per goal), item_progress (hours to credit, completed flag), went_well,
    went_badly, tomorrow's plan and a tip. plan_status marks the day's planned blocks done / partial (with
    done_minutes) / skipped. day_off=True records a deliberate day off (sick, holiday): not scored, doesn't break
    the streak. Saving again for the same day replaces the previous review. Returns the daily score (0-100) with an
    explanation of how it was computed, the per-goal breakdown, and tomorrow's plan."""
    async with owner_session() as (session, user):
        d = parse_day(day, user)
        for ps in plan_status or []:
            item = await session.get(PlanItem, ps.plan_item_id)
            if item is not None and item.user_id == user.id:
                item.status = ps.status
                item.done_minutes = ps.done_minutes if ps.status == "partial" else None
        entry = await analysis.get_or_create_entry(session, user, d)
        if schedule is not None:
            entry.schedule = [b.model_dump() for b in schedule]
        if notes:
            entry.free_text = notes
        if energy is not None:
            entry.energy = energy
        result = await analysis.confirm(session, user, entry, review, used_llm=True, day_off=day_off)
        per_goal = {k: v for k, v in result.per_goal.items() if not k.startswith("_")}
        tomorrow = await analysis.plan_for(session, user.id, d + timedelta(days=1))
        credited = [await session.get(RoadmapItem, p["roadmap_item_id"])
                    for p in result.per_goal.get("_item_progress", [])]
        overruns = [{"id": i.id, "title": i.title, "est_hours": i.est_hours, "hours_logged": round(i.hours_logged, 2)}
                    for i in credited if i is not None and over_estimate(i)]
        alerts = []
        for g in await analysis.load_goals_with_items(session, user):
            if g.intake_status != "active":
                continue
            st = await timeline.goal_status(session, user, g, d + timedelta(days=1))
            if line := timeline.alert(g, st, await timeline.diagnose(session, user, g, d + timedelta(days=1), st)):
                alerts.append({"goal_id": g.id, "message": line})
        return {
            "date": d.isoformat(),
            "score": None if result.rest_day else result.total_score,
            "rest_day": result.rest_day,
            "score_explanation": result.breakdown.get("explanation"),
            "breakdown": result.breakdown,
            "per_goal": per_goal,
            "plan_adherence": result.adherence,
            "off_goal_minutes": result.drift_minutes,
            "credited_items": result.per_goal.get("_item_progress", []),
            "tomorrow_plan": [{"time_block": p.time_block, "title": p.title, "minutes": p.minutes}
                              for p in tomorrow],
            "items_over_estimate": overruns,
            "timeline_alerts": alerts,
        }


@mcp.tool()
async def set_plan_item_status(plan_item_id: int, status: Literal["done", "partial", "skipped", "open"],
                               done_minutes: int | None = None) -> dict:
    """Mark one planned block as done / partial (with done_minutes) / skipped, e.g. during the day."""
    async with owner_session() as (session, user):
        item = await session.get(PlanItem, plan_item_id)
        if item is None or item.user_id != user.id:
            raise ToolError(f"No plan item {plan_item_id}.")
        item.status = status
        item.done_minutes = done_minutes if status == "partial" else None
        return {"plan_item_id": item.id, "title": item.title, "status": item.status,
                "done_minutes": item.done_minutes}


def plan_view(items: list[PlanItem]) -> list[dict]:
    return [{"plan_item_id": p.id, "time_block": p.time_block, "title": p.title, "minutes": p.minutes,
             "goal_id": p.goal_id, "roadmap_item_id": p.roadmap_item_id, "status": p.status,
             "done_minutes": p.done_minutes, "details": p.details or {}} for p in items]


@mcp.tool()
async def plan_day(day: str | None = None, replace: bool = False) -> dict:
    """Get the plan for a day (default today), creating it from the user's routines and next roadmap items if there
    isn't one (e.g. they didn't log last night). replace=True rebuilds the unfinished blocks. The generated blocks
    only carry the roadmap item name: give each a short title and details (why, timed steps, resources,
    done_when) via edit_plan."""
    async with owner_session() as (session, user):
        d = parse_day(day, user)
        existing = await analysis.plan_for(session, user.id, d)
        created = False
        if replace or not existing:
            existing = await analysis.save_plan(session, user, d, await analysis.rule_plan(session, user, d))
            created = True
        return {"date": d.isoformat(), "weekday": d.strftime("%A"), "created_now": created,
                "rest_day": not existing, "plan": plan_view(existing)}


class PlanBlockIn(BaseModel):
    time_block: str = Field(default="", description="HH:MM-HH:MM")
    title: str = Field(description="Short task name, max ~8 words, e.g. 'Attention from scratch'")
    minutes: int = Field(default=60, ge=5, le=720)
    goal_id: int | None = None
    roadmap_item_id: int | None = None
    details: PlanDetails | None = Field(default=None, description="why, timed steps, resources, done_when")


class PlanBlockUpdate(BaseModel):
    plan_item_id: int
    time_block: str | None = None
    title: str | None = None
    minutes: int | None = Field(default=None, ge=5, le=720)
    details: PlanDetails | None = None


@mcp.tool()
async def edit_plan(day: str | None = None, add: list[PlanBlockIn] | None = None,
                    update: list[PlanBlockUpdate] | None = None, remove: list[int] | None = None) -> dict:
    """Change a day's plan (default today): add blocks, move/rename/shorten blocks (update), or remove blocks by
    plan_item_id. Use it when the user's day is different (meetings, travel, low energy) or to make titles concrete.
    Returns the updated plan."""
    async with owner_session() as (session, user):
        d = parse_day(day, user)
        goal_ids = {g.id for g in await analysis.load_goals_with_items(session, user)}
        for pid in remove or []:
            item = await session.get(PlanItem, pid)
            if item is not None and item.user_id == user.id:
                await session.delete(item)
        for u in update or []:
            item = await session.get(PlanItem, u.plan_item_id)
            if item is None or item.user_id != user.id:
                raise ToolError(f"No plan item {u.plan_item_id}.")
            for field in ("time_block", "title", "minutes"):
                if (value := getattr(u, field)) is not None:
                    setattr(item, field, value)
            if u.details is not None:
                item.details = u.details.model_dump()
        for b in add or []:
            if b.roadmap_item_id is not None:
                await get_item(session, user, b.roadmap_item_id)  # must be the user's own item
            session.add(PlanItem(user_id=user.id, date_for=d, time_block=b.time_block, title=b.title,
                                 minutes=b.minutes, goal_id=b.goal_id if b.goal_id in goal_ids else None,
                                 roadmap_item_id=b.roadmap_item_id,
                                 details=b.details.model_dump() if b.details else {}))
        await session.flush()
        items = await analysis.plan_for(session, user.id, d)
        return {"date": d.isoformat(), "plan": plan_view(items), "total_minutes": sum(p.minutes for p in items)}


@mcp.tool()
async def get_history(days: int = 30) -> dict:
    """Daily scores and per-goal minutes for the last `days` days, for spotting trends and patterns."""
    async with owner_session() as (session, user):
        since = today_for(user) - timedelta(days=days - 1)
        rows = await session.execute(
            select(DailyEntry.date, DailyReview.total_score, DailyReview.per_goal, DailyReview.adherence,
                   DailyReview.drift_minutes, DailyReview.rest_day)
            .join(DailyReview).where(DailyEntry.user_id == user.id, DailyEntry.date >= since)
            .order_by(DailyEntry.date)
        )
        return {"days": [{
            "date": r.date.isoformat(), "score": None if r.rest_day else r.total_score, "rest_day": r.rest_day,
            "plan_adherence": r.adherence,
            "off_goal_minutes": r.drift_minutes,
            "minutes_per_goal": {v["title"]: v["minutes"] for k, v in r.per_goal.items() if not k.startswith("_")},
        } for r in rows]}


# ---------------------------------------------------------------- timeline & replans

@mcp.tool()
async def get_timeline() -> dict:
    """Schedule status for each active goal: planned vs done hours against the agreed plan, days behind/ahead
    (threshold scales with the plan's length), overdue items, a diagnosis of why it's off plan with a forecast at the
    user's actual recent pace and a suggested fix, remaining open items, and any pending replan proposal."""
    async with owner_session() as (session, user):
        today = today_for(user)
        out = []
        for g in await analysis.load_goals_with_items(session, user):
            if g.intake_status != "active":
                continue
            st = await timeline.goal_status(session, user, g, today)
            pending = await timeline.pending_replan(session, g.id)
            out.append({
                "goal_id": g.id, "title": g.title, "target_date": iso(g.target_date), **st.as_dict(),
                "diagnosis": await timeline.diagnose(session, user, g, today, st),
                "open_items": [item_view(i, False) for i in roadmap.ordered_items(g)
                               if i.status in roadmap.OPEN_STATUSES],
                "pending_replan_id": pending.id if pending else None,
            })
        return {"today": today.isoformat(), "goals": out}


@mcp.tool()
async def preview_replan(goal_id: int, strategy: Literal["shift", "reduce_scope", "increase_hours"], reason: str,
                         skip_item_ids: list[int] | None = None,
                         new_goal_hours_per_day: float | None = None) -> dict:
    """Compute a replan without applying it: shift dates, skip low-value items (reduce_scope + skip_item_ids), or
    raise this goal's hours/day (increase_hours + new_goal_hours_per_day). Show the changes to the user and apply
    with resolve_replan(accept=True) only if they agree. Replaces any earlier pending proposal for this goal.
    For a goal with an agreed routine, more time means new time blocks: agree them and call confirm_commitment."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        if strategy == "increase_hours" and goal.routine:
            raise ToolError("This goal has an agreed weekly routine. To add time, agree extra/longer time blocks "
                             "with the user and call confirm_commitment with the new routine.")
        if existing := await timeline.pending_replan(session, goal.id):
            existing.status = "rejected"
        today = today_for(user)
        status = await timeline.goal_status(session, user, goal, today)
        draft = ReplanDraft(strategy=strategy, reason=reason, skip_item_ids=skip_item_ids or [],
                            new_goal_hours_per_day=new_goal_hours_per_day)
        proposal = timeline.make_proposal(session, user, goal, status, draft, today)
        if proposal is None:
            raise ToolError("Nothing left to reschedule for this goal.")
        await session.flush()
        return {"proposal_id": proposal.id, "reason": proposal.reason, **proposal.diff}


@mcp.tool()
async def resolve_replan(proposal_id: int, accept: bool) -> dict:
    """Apply (accept=True) or discard a replan proposal."""
    async with owner_session() as (session, user):
        proposal = await session.scalar(
            select(ReplanProposal).join(Goal).where(ReplanProposal.id == proposal_id, Goal.user_id == user.id)
        )
        if proposal is None or proposal.status != "pending":
            raise ToolError(f"No pending replan proposal {proposal_id}.")
        if accept:
            goal = await get_goal(session, user, proposal.goal_id)
            await timeline.apply_replan(session, user, goal, proposal, today_for(user))
        else:
            proposal.status = "rejected"
        return {"proposal_id": proposal.id, "status": proposal.status}


# ---------------------------------------------------------------- what's new

@mcp.tool()
async def refresh_feeds() -> dict:
    """Fetch the latest items from the curated feeds (arXiv, Hacker News, Hugging Face blog, Simon Willison,
    new GitHub LLM/agent repos). Takes up to a minute."""
    async with owner_session() as (session, _user):
        added = await ingest_all(session)
        return {"added": added}


class WatchTopic(BaseModel):
    topic: str = Field(description="Something to keep an eye on for this goal, e.g. 'AI engineer job requirements'")
    terms: list[str] = Field(description="Phrases that would appear in a relevant headline, incl. synonyms")


class ItemTerms(BaseModel):
    roadmap_item_id: int
    terms: list[str] = Field(description="The plain short name plus specific synonyms/tool names for news on this "
                                         "item, e.g. for RAG: ['RAG', 'retrieval-augmented', 'reranker', "
                                         "'vector search']; for transformers: ['transformer', 'attention', "
                                         "'flash attention']")


@mcp.tool()
async def set_search_terms(goal_id: int, watch_topics: list[WatchTopic] | None = None,
                           item_terms: list[ItemTerms] | None = None) -> dict:
    """Set what 'what's new' looks for: the goal's watch topics (replaces them) and/or search terms for roadmap
    items. Good terms are specific phrases and synonyms that appear in headlines, not generic words."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        if watch_topics is not None:
            goal.watch_topics = [w.model_dump() for w in watch_topics]
        items = {i.id: i for i in roadmap.ordered_items(goal)}
        for it in item_terms or []:
            if it.roadmap_item_id not in items:
                raise ToolError(f"Item {it.roadmap_item_id} is not part of goal {goal_id}.")
            items[it.roadmap_item_id].search_terms = it.terms
        missing = [{"id": i.id, "title": i.title} for i in roadmap.ordered_items(goal)
                   if i.status in roadmap.OPEN_STATUSES and not i.search_terms]
        return {"watch_topics": goal.watch_topics, "items_without_terms": missing}


@mcp.tool()
async def get_trend_candidates(goal_id: int, days: int = 14, limit: int = 25) -> dict:
    """Recent feed items relevant to this goal, ranked by how well they match the search terms of the roadmap items
    the user is on now and the goal's watch topics (title hits > summary hits), source quality and recency. Items
    already suggested before are left out. Combine with your own web search, then suggest at most 3."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        today = today_for(user)
        focus = analysis.focus_items(goal, today, limit=4)
        newest = await session.scalar(select(func.max(TrendItem.published_at)))
        if newest is not None and newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        previous = list(await session.scalars(
            select(TrendSuggestion).where(TrendSuggestion.goal_id == goal.id)
            .order_by(TrendSuggestion.created_at.desc()).limit(30)))
        goal.trends_checked_at = datetime.now(timezone.utc)
        return {
            "current_items": [{"id": i.id, "title": i.title, "search_terms": i.search_terms} for i in focus],
            "items_missing_terms": [i.id for i in focus if not i.search_terms],
            "watch_topics": goal.watch_topics,
            "search_terms_used": [t for t, _ in search_terms(goal, today)],
            "feeds_last_updated": newest.isoformat() if newest else None,
            "feeds_stale": newest is None or datetime.now(timezone.utc) - newest > timedelta(days=1),
            "previously_suggested": [{"title": p.title, "status": p.status} for p in previous],
            "candidates": await rank_candidates(session, user, goal, today, days, limit),
        }


class SuggestionIn(BaseModel):
    title: str
    why_relevant: str = Field(description="Why it matters for this user's goal right now, 1-2 sentences")
    url: str
    est_hours: float = Field(default=2, gt=0, le=100)
    type: Literal["topic", "skill", "task", "milestone"] = "topic"


@mcp.tool()
async def record_trend_suggestions(goal_id: int, suggestions: list[SuggestionIn]) -> dict:
    """Save the (at most 3) things you're suggesting so they're never suggested twice. Returns each with an id and
    what adding it would do to the finish date, to show the user before they decide."""
    async with owner_session() as (session, user):
        goal = await get_goal(session, user, goal_id)
        today = today_for(user)
        capacity = roadmap.capacity_for(goal, await roadmap.goal_hours_per_day(session, user, goal))
        out = []
        for sg in suggestions[:3]:
            rec = TrendSuggestion(user_id=user.id, goal_id=goal.id, title=sg.title, why_relevant=sg.why_relevant,
                                  est_hours=sg.est_hours, links=[{"title": sg.title, "url": sg.url, "type": sg.type}])
            session.add(rec)
            await session.flush()
            before, after = roadmap.finish_with_extra(goal, today, capacity, sg.est_hours, sg.type)
            out.append({"suggestion_id": rec.id, "title": sg.title, "est_hours": sg.est_hours,
                        "finish_now": iso(before), "finish_if_added": iso(after), "target_date": iso(goal.target_date)})
        return {"suggestions": out}


@mcp.tool()
async def resolve_trend_suggestion(suggestion_id: int, action: Literal["add", "dismiss"],
                                   est_hours: float | None = None) -> dict:
    """The user's decision on a suggestion. add: put it in the roadmap right after their current item and re-date
    the rest (tell them the new finish date). dismiss: never suggest it again."""
    async with owner_session() as (session, user):
        sg = await session.get(TrendSuggestion, suggestion_id)
        if sg is None or sg.user_id != user.id:
            raise ToolError(f"No suggestion {suggestion_id}.")
        if action == "dismiss":
            sg.status = "dismissed"
            return {"suggestion_id": sg.id, "status": sg.status}
        goal = await get_goal(session, user, sg.goal_id)
        link = (sg.links or [{}])[0]
        item = RoadmapItem(type=link.get("type", "topic"), title=sg.title, description=sg.why_relevant,
                           est_hours=est_hours or sg.est_hours, resources=[{"title": sg.title, "url": link.get("url", "")}],
                           source="trend", search_terms=[])
        roadmap.insert_after_current(goal, item)
        await session.flush()
        feas = await roadmap.reschedule(session, user, goal, today_for(user))
        sg.status = "added_to_roadmap"
        return {"suggestion_id": sg.id, "status": sg.status, "item": item_view(item),
                "feasibility": feasibility_view(feas)}


class SourceIn(BaseModel):
    name: str
    url: str = Field(description="RSS/Atom feed URL, or for kind=github a search like 'topic:rag'")
    kind: Literal["rss", "github"] = "rss"


@mcp.tool()
async def manage_sources(action: Literal["list", "add", "remove", "enable", "disable"],
                         source: SourceIn | None = None, source_id: int | None = None) -> dict:
    """List the feeds 'what's new' reads, add the user's own (newsletter, company engineering blog, GitHub topic),
    remove their own, or enable/disable any source. Call refresh_feeds after adding one."""
    async with owner_session() as (session, user):
        await ensure_default_sources(session)
        if action == "add":
            if source is None:
                raise ToolError("Give the source to add.")
            session.add(TrendSource(user_id=user.id, name=source.name, kind=source.kind, url=source.url,
                                    weight=USER_SOURCE_WEIGHT))
        elif action in ("remove", "enable", "disable"):
            src = await session.get(TrendSource, source_id) if source_id else None
            if src is None or src.user_id not in (None, user.id):
                raise ToolError(f"No source {source_id}.")
            if action == "remove":
                if src.user_id is None:
                    raise ToolError("Built-in sources can't be removed; disable it instead.")
                await session.delete(src)
            else:
                src.enabled = action == "enable"
        await session.flush()
        rows = await session.scalars(select(TrendSource).where(
            or_(TrendSource.user_id.is_(None), TrendSource.user_id == user.id)).order_by(TrendSource.id))
        return {"sources": [{"id": s.id, "name": s.name, "kind": s.kind, "url": s.url, "enabled": s.enabled,
                             "built_in": s.user_id is None} for s in rows]}


# ---------------------------------------------------------------- weekly review

@mcp.tool()
async def get_weekly_stats(week_start: str | None = None) -> dict:
    """Stats for a week (Monday YYYY-MM-DD; default: current week): days scored, scores, plan blocks done, per goal
    hours vs the hours committed in the routine, completed items and timeline status; the previous week and a
    4-week trend for comparison; patterns over the last 4 weeks (plan done by weekday and time of day, score by
    weekday and by energy, wasted time by weekday); and last week's focus points to follow up on."""
    async with owner_session() as (session, user):
        start = weekly.week_start_of(parse_day(week_start, user))
        return await weekly.week_stats(session, user, start, today_for(user))


@mcp.tool()
async def save_weekly_review(summary: str, wins: list[str], gaps: list[str], recommendations: list[str],
                             week_start: str | None = None, focus: list[str] | None = None,
                             last_week_focus_kept: list[bool] | None = None) -> dict:
    """Save the weekly review you wrote (shown on the web dashboard). focus: 1-3 short, checkable focus points the
    user agreed to for the coming week (shown in every nightly review). last_week_focus_kept: for each of last
    week's focus points (same order), whether the user kept it."""
    async with owner_session() as (session, user):
        start = weekly.week_start_of(parse_day(week_start, user))
        if last_week_focus_kept is not None:
            previous = await session.scalar(select(WeeklyReview).where(
                WeeklyReview.user_id == user.id, WeeklyReview.week_start == start - timedelta(days=7)))
            if previous is not None:
                previous.focus = [{**f, "kept": kept} for f, kept in zip(previous.focus, last_week_focus_kept)] + \
                    previous.focus[len(last_week_focus_kept):]
        review = await session.scalar(
            select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.week_start == start)
        )
        if review is None:
            review = WeeklyReview(user_id=user.id, week_start=start)
            session.add(review)
        review.stats = await weekly.week_stats(session, user, start, today_for(user))
        review.summary, review.wins, review.gaps, review.recommendations = summary, wins, gaps, recommendations
        if focus is not None:
            review.focus = [{"text": f, "kept": None} for f in focus[:3]]
        return {"week_start": start.isoformat(), "saved": True, "focus": review.focus}


async def weekly_review_due(session: AsyncSession, user: User, today: date) -> str | None:
    """Monday of last week if it had logged days but no weekly review yet."""
    last_start = weekly.week_start_of(today) - timedelta(days=7)
    has_review = await session.scalar(select(WeeklyReview.id).where(
        WeeklyReview.user_id == user.id, WeeklyReview.week_start == last_start))
    logged = await session.scalar(select(func.count()).select_from(DailyEntry).join(DailyReview).where(
        DailyEntry.user_id == user.id, DailyEntry.date.between(last_start, last_start + timedelta(days=6))))
    return last_start.isoformat() if logged and not has_review else None


# ---------------------------------------------------------------- dashboard in chat

@mcp.tool()
async def get_dashboard(weeks: int = Field(default=8, ge=2, le=26)) -> dict:
    """Data for charts of the user's progress, to draw right in the chat when they ask to see their progress or a
    dashboard: daily scores (rest days marked), weekly score / plan-done / hours, each goal's weekly hours vs the
    hours their routine planned, and each goal's progress against the agreed plan (planned vs done hours)."""
    async with owner_session() as (session, user):
        today = today_for(user)
        first_week = weekly.week_start_of(today) - timedelta(days=7 * (weeks - 1))
        week_starts = [first_week + timedelta(days=7 * n) for n in range(weeks)]
        days = list(await session.execute(
            select(DailyEntry.date, DailyReview.total_score, DailyReview.rest_day).join(DailyReview)
            .where(DailyEntry.user_id == user.id, DailyEntry.date >= first_week).order_by(DailyEntry.date)))
        minutes_rows = await session.execute(
            select(DailyEntry.date, ActivityLink.goal_id, func.sum(Activity.minutes * ActivityLink.relevance))
            .select_from(ActivityLink).join(Activity, Activity.id == ActivityLink.activity_id)
            .join(DailyEntry, DailyEntry.id == Activity.entry_id)
            .where(DailyEntry.user_id == user.id, DailyEntry.date >= first_week)
            .group_by(DailyEntry.date, ActivityLink.goal_id))
        actual: dict[tuple[int, str], float] = {}
        for d, gid, mins in minutes_rows:
            key = (gid, weekly.week_start_of(d).isoformat())
            actual[key] = actual.get(key, 0) + float(mins or 0) / 60

        goals_out = []
        for g in await analysis.load_goals_with_items(session, user):
            if g.intake_status != "active":
                continue
            per_week = []
            for ws in week_starts:
                elapsed = [ws + timedelta(days=n) for n in range(7) if ws + timedelta(days=n) <= today]
                planned = sum([await roadmap.goal_target_minutes(session, user, g, d) for d in elapsed]) / 60
                per_week.append({"week": ws.isoformat(), "planned_hours": round(planned, 1),
                                 "actual_hours": round(actual.get((g.id, ws.isoformat()), 0), 1)})
            st = await timeline.goal_status(session, user, g, today)
            goals_out.append({
                "goal_id": g.id, "title": g.title, "target_date": iso(g.target_date),
                "progress": {"planned_hours_by_now": st.planned_hours, "done_hours": st.done_hours,
                             "state": st.state, "behind_days": st.behind_days},
                "weekly_hours": per_week,
            })
        return {
            "today": today.isoformat(),
            "daily_scores": [{"date": r.date.isoformat(), "score": None if r.rest_day else r.total_score,
                              "rest_day": r.rest_day} for r in days],
            "weeks": [await weekly.week_basics(session, user, ws, today) for ws in week_starts],
            "goals": goals_out,
            "streak_days": await analysis.streak_before(session, user.id, today),
            "weekly_focus": await weekly.current_focus(session, user, today),
        }


# ---------------------------------------------------------------- prompts (shortcuts in Claude's "+" menu)

@mcp.prompt(title="Log my day")
def log_my_day() -> str:
    return ("Let's do my nightly review. Get my day context, ask me how my day went (and which planned blocks I "
            "did), then analyse it, save it, and show my score, what went well/badly and tomorrow's plan.")


@mcp.prompt(title="New goal")
def new_goal(goal: str) -> str:
    return (f"I want to add a new goal: {goal}. Take me through the full intake: agree the exact goal with me, then the "
            "roadmap, then the timeline and what I'll do every day (a weekly routine). Confirm each step with me "
            "before saving it.")


@mcp.prompt(title="What's new for me")
def whats_new() -> str:
    return ("For each of my active goals, find what's new and relevant to what I'm currently studying (use the feed "
            "candidates and your own web search). Suggest at most 3 per goal and offer to add them to my roadmap.")


@mcp.prompt(title="Weekly review")
def weekly_review() -> str:
    return ("Do my weekly review: get this week's stats and timeline, write an honest review with wins, gaps and "
            "next-week recommendations, save it, and check whether any goal needs a replan.")


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
