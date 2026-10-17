"""Nightly day analysis: draft (LLM or rules) -> user edits -> confirm (persist + score + tomorrow's plan)."""

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import (
    Activity,
    ActivityLink,
    DailyEntry,
    DailyReview,
    Goal,
    PlanItem,
    RoadmapItem,
    RoadmapPhase,
    User,
)
from app.services import commitment, prompts, roadmap, scheduler, scoring, timeline
from app.services.llm import LLMError, get_llm
from app.services.llm.outputs import (
    ActivityDraft,
    DayAnalysis,
    ItemProgress,
    LinkDraft,
    PlanDetails,
    PlanDraft,
    Resource,
)

PLAN_BLOCK_MAX_MIN = 90
KIND_KEYWORDS = [  # first match wins; used only when the AI is unavailable and the user didn't pick a kind
    ("waste", r"scroll|youtube|netflix|instagram|twitter|reddit|tiktok|procrastinat|binge"),
    ("job", r"day job|office|standup|stand-up|work meeting|client work|commute|\bjob\b"),
    ("apply", r"\bappl(y|ied|ication)|resume|\bcv\b|cover letter|recruiter"),
    ("ship", r"deploy|ship|launch|publish|release"),
    ("network", r"\bcall|meet|interview|network|coffee|linkedin|mentor"),
    ("build", r"\bbuil|cod(e|ing)|implement|develop|prototype|debug"),
    ("learn", r"read|stud(y|ied)|course|paper|learn|tutorial|lecture|book|practic"),
    ("leisure", r"gym|run|walk|lunch|dinner|breakfast|sleep|nap|family|friend|workout|yoga|rest|relax"),
    ("admin", r"email|errand|chores|admin|bank|groceries"),
]


def guess_kind(text: str) -> str:
    low = text.lower()
    return next((kind for kind, pattern in KIND_KEYWORDS if re.search(pattern, low)), "other")


# ---------- helpers ----------

def block_minutes(start: str, end: str) -> int:
    try:
        s = datetime.strptime(start, "%H:%M")
        e = datetime.strptime(end, "%H:%M")
    except (ValueError, TypeError):
        return 0
    mins = int((e - s).total_seconds() // 60)
    return mins + 24 * 60 if mins < 0 else mins


async def load_goals_with_items(session: AsyncSession, user: User) -> list[Goal]:
    rows = await session.scalars(
        select(Goal)
        .where(Goal.user_id == user.id, Goal.status == "active")
        .options(selectinload(Goal.phases).selectinload(RoadmapPhase.items))
        .order_by(Goal.priority.desc(), Goal.id)
    )
    return list(rows)


async def tracked_goals(session: AsyncSession, user: User) -> list[Goal]:
    """Goals whose setup is finished: only these are scored and planned (a half-set-up goal has no plan yet)."""
    return [g for g in await load_goals_with_items(session, user) if g.intake_status == "active"]


def focus_items(goal: Goal, today: date, limit: int = 4) -> list[RoadmapItem]:
    """In-progress and overdue items first, then the next scheduled ones."""
    open_items = [i for i in roadmap.ordered_items(goal) if i.status in roadmap.OPEN_STATUSES]
    open_items.sort(key=lambda i: (i.status != "in_progress", i.planned_start or date.max))
    return open_items[:limit]


async def plan_for(session: AsyncSession, user_id, day: date) -> list[PlanItem]:
    rows = await session.scalars(
        select(PlanItem).where(PlanItem.user_id == user_id, PlanItem.date_for == day)
        .order_by(PlanItem.time_block, PlanItem.id)  # chronological; "HH:MM-HH:MM" sorts as text
    )
    return list(rows)


def rest_weekdays(goals: list[Goal]) -> set[int]:
    """Weekdays (0=Mon) on which no active goal has anything planned. Empty if any goal has no routine."""
    active = [g for g in goals if g.status == "active" and g.intake_status == "active"]
    if not active or any(not g.routine for g in active):
        return set()
    return {wd for wd in range(7)
            if all(commitment.routine_minutes_on(g.routine, date(2026, 1, 5) + timedelta(days=wd)) == 0
                   for g in active)}  # 2026-01-05 is a Monday


async def streak_before(session: AsyncSession, user_id, day: date) -> int:
    """Consecutive scored days before `day`. Rest days (logged as rest, or unlogged on a planned rest weekday)
    neither break nor extend the streak."""
    rows = await session.execute(
        select(DailyEntry.date, DailyReview.rest_day)
        .join(DailyReview, DailyReview.entry_id == DailyEntry.id)
        .where(DailyEntry.user_id == user_id, DailyEntry.date < day, DailyEntry.date >= day - timedelta(days=90))
    )
    logged = {d: rest for d, rest in rows}
    goals = list(await session.scalars(select(Goal).where(Goal.user_id == user_id, Goal.status == "active")))
    rest_wd = rest_weekdays(goals)
    streak, cur = 0, day - timedelta(days=1)
    for _ in range(90):
        if cur in logged:
            if not logged[cur]:
                streak += 1
        elif cur.weekday() not in rest_wd:
            break
        cur -= timedelta(days=1)
    return streak


def sanitize(analysis: DayAnalysis, goals: list[Goal]) -> DayAnalysis:
    """Drop any goal/item ids the model invented or that belong to someone else."""
    goal_ids = {g.id for g in goals}
    item_goal = {i.id: g.id for g in goals for i in roadmap.ordered_items(g)}

    for act in analysis.activities:
        act.links = [link for link in act.links if link.goal_id in goal_ids]
        for link in act.links:
            if link.roadmap_item_id is not None and item_goal.get(link.roadmap_item_id) != link.goal_id:
                link.roadmap_item_id = None
    analysis.goal_impacts = [g for g in analysis.goal_impacts if g.goal_id in goal_ids]
    analysis.item_progress = [p for p in analysis.item_progress if p.roadmap_item_id in item_goal]
    for p in analysis.tomorrow:
        if p.goal_id not in goal_ids:
            p.goal_id = None
        if p.roadmap_item_id not in item_goal:
            p.roadmap_item_id = None
        elif p.goal_id is None:
            p.goal_id = item_goal[p.roadmap_item_id]
    return analysis


# ---------- rule-based fallback ----------

def item_details(item: RoadmapItem | None) -> PlanDetails | None:
    if item is None:
        return None
    return PlanDetails(why=item.description or f"Next step on your roadmap: {item.title}.",
                       resources=[Resource(title=r.get("title") or r.get("url", ""), url=r.get("url", ""))
                                  for r in item.resources or [] if r.get("url") or r.get("title")])


def pick_for_block(items: list[RoadmapItem], focus: str, used: set[int]) -> RoadmapItem | None:
    """Next roadmap item for a routine block: matching its focus (learn/build) if possible, unused first."""
    def matches(i: RoadmapItem) -> bool:
        return focus == "any" or scheduler.track_of(i.type) == focus
    for pool in ([i for i in items if i.id not in used and matches(i)], [i for i in items if matches(i)],
                 [i for i in items if i.id not in used], items):
        if pool:
            used.add(pool[0].id)
            return pool[0]
    return None


def rule_tomorrow(goals: list[Goal], budgets: dict[int, int], tomorrow: date) -> list[PlanDraft]:
    """Tomorrow's plan: the goal's routine blocks for that weekday (filled with the next roadmap items), or else
    the next items up to the day's minute budget."""
    plan: list[PlanDraft] = []
    for g in goals:
        items = focus_items(g, tomorrow, limit=6)
        blocks = commitment.routine_blocks_on(g.routine, tomorrow) if g.routine else []
        if blocks:
            used: set[int] = set()
            for b in blocks:
                item = pick_for_block(items, b.get("focus") or "any", used)
                plan.append(PlanDraft(
                    details=item_details(item),
                    time_block=f"{b.get('start', '')}-{b.get('end', '')}",
                    title=f"{b.get('activity') or 'Focus'}: {item.title}" if item else (b.get("activity") or "Focus"),
                    minutes=max(commitment.block_minutes(b.get("start", ""), b.get("end", "")), 5),
                    goal_id=g.id, roadmap_item_id=item.id if item else None))
            continue
        budget = budgets.get(g.id, 60)
        for item in items:
            if budget <= 0:
                break
            mins = int(min(budget, PLAN_BLOCK_MAX_MIN, max(roadmap.remaining_hours(item) * 60, 15)))
            plan.append(PlanDraft(title=f"{item.title}", minutes=mins, goal_id=g.id, roadmap_item_id=item.id))
            budget -= mins
    return plan


def rule_feedback(activities: list[ActivityDraft], goals: list[Goal], targets: dict[int, int],
                  plan: list[PlanItem]) -> tuple[list[str], list[str]]:
    well, bad = [], []
    per_goal = {g.id: 0 for g in goals}
    for a in activities:
        for link in a.links:
            per_goal[link.goal_id] = per_goal.get(link.goal_id, 0) + a.minutes
    focused = sum(per_goal.values())
    if focused:
        hours, mins = divmod(focused, 60)
        well.append(f"{f'{hours}h ' if hours else ''}{f'{mins}m' if mins else ''}".strip() + " of work toward your goals")
    for g in goals:
        target = targets.get(g.id, 0)
        if per_goal.get(g.id, 0) >= target > 0:
            well.append(f"Hit your daily target for '{g.title}'")
        elif per_goal.get(g.id, 0) == 0 and target > 0:
            bad.append(f"No time on '{g.title}' today")
    waste = sum(a.minutes for a in activities if a.kind == "waste")
    if waste >= 30:
        bad.append(f"{waste} min marked as wasted time")
    if plan:
        done = sum(1 for p in plan if p.status == "done")
        (well if done / len(plan) >= 0.7 else bad).append(f"Completed {done}/{len(plan)} planned blocks")
    return well, bad


def rule_draft(entry: DailyEntry, goals: list[Goal], targets: dict[int, int], tomorrow_budgets: dict[int, int],
               plan: list[PlanItem] | None = None) -> DayAnalysis:
    activities: list[ActivityDraft] = []
    progress: dict[int, float] = {}
    goal_ids = {g.id for g in goals}
    for block in entry.schedule or []:
        mins = block_minutes(block.get("start", ""), block.get("end", "")) or int(block.get("minutes") or 0)
        links = []
        gid = block.get("goal_id")
        if gid in goal_ids:
            links.append(LinkDraft(goal_id=gid, roadmap_item_id=block.get("roadmap_item_id"), relevance=1.0,
                                   reason="Tagged by you"))
            if block.get("roadmap_item_id"):
                progress[block["roadmap_item_id"]] = progress.get(block["roadmap_item_id"], 0) + mins / 60
        description = block.get("activity") or "Untitled"
        activities.append(ActivityDraft(description=description, minutes=mins,
                                        kind=block.get("kind") or guess_kind(description), links=links))
    well, bad = rule_feedback(activities, goals, targets, plan or [])
    return DayAnalysis(
        activities=activities,
        went_well=well,
        went_badly=bad,
        item_progress=[ItemProgress(roadmap_item_id=k, hours=round(v, 2)) for k, v in progress.items()],
        tomorrow=rule_tomorrow(goals, tomorrow_budgets, entry.date + timedelta(days=1)),
        tip="AI coach unavailable - this review uses your own tags. Tag schedule blocks with goals for better scores.",
    )


async def get_or_create_entry(session: AsyncSession, user: User, day: date) -> DailyEntry:
    entry = await session.scalar(select(DailyEntry).where(DailyEntry.user_id == user.id, DailyEntry.date == day))
    if entry is None:
        entry = DailyEntry(user_id=user.id, date=day, schedule=[], free_text="", activities=[], review=None)
        session.add(entry)
        await session.flush()
    return entry


async def save_plan(session: AsyncSession, user: User, day: date, blocks: list[PlanDraft]) -> list[PlanItem]:
    """Replace the day's unfinished plan blocks with `blocks` (blocks already marked done/partial/skipped stay)."""
    await session.execute(
        delete(PlanItem).where(PlanItem.user_id == user.id, PlanItem.date_for == day, PlanItem.status == "open")
    )
    for b in blocks:
        session.add(PlanItem(user_id=user.id, date_for=day, time_block=b.time_block, title=b.title,
                             minutes=b.minutes, goal_id=b.goal_id, roadmap_item_id=b.roadmap_item_id,
                             details=b.details.model_dump() if b.details else {}))
    await session.flush()
    return await plan_for(session, user.id, day)


async def rule_plan(session: AsyncSession, user: User, day: date) -> list[PlanDraft]:
    """A plan for `day` from the routines (or daily budgets) and the next roadmap items, without AI."""
    goals = await tracked_goals(session, user)
    return rule_tomorrow(goals, await daily_targets(session, user, goals, day), day)


async def daily_targets(session: AsyncSession, user: User, goals: list[Goal], day: date) -> dict[int, int]:
    return {g.id: await roadmap.goal_target_minutes(session, user, g, day) for g in goals}


# ---------- draft ----------

async def build_draft(session: AsyncSession, user: User, entry: DailyEntry) -> tuple[DayAnalysis, bool]:
    """Returns (draft, used_llm)."""
    goals = await tracked_goals(session, user)
    targets = await daily_targets(session, user, goals, entry.date)
    tomorrow_budgets = await daily_targets(session, user, goals, entry.date + timedelta(days=1))

    plan = await plan_for(session, user.id, entry.date)
    llm = get_llm(user)
    if llm is None:
        return rule_draft(entry, goals, targets, tomorrow_budgets, plan), False

    goal_lines, item_lines = [], []
    for g in goals:
        st = await timeline.goal_status(session, user, g, entry.date)
        goal_lines.append(f"- {g.id} | {g.title} | priority {g.priority} | {st.state}, behind {st.behind_days}d"
                          f" | planned today {targets[g.id]} min, tomorrow {tomorrow_budgets[g.id]} min")
        for i in focus_items(g, entry.date):
            item_lines.append(f"- {i.id} | goal {g.id} | {i.title} | {i.est_hours}h | {i.hours_logged:.1f}h logged"
                              f" | due {i.planned_due or '-'} | {i.status}")
    sched = "\n".join(
        f"- {b.get('start', '?')}-{b.get('end', '?')}: {b.get('activity', '')}"
        + (f" ({b['notes']})" if b.get("notes") else "")
        + (f" [user tagged goal {b['goal_id']}]" if b.get("goal_id") else "")
        for b in entry.schedule or []
    )
    ctx = {
        "date": entry.date.isoformat(),
        "weekday": entry.date.strftime("%A"),
        "daily_hours": user.daily_available_hours,
        "goals": "\n".join(goal_lines) or "(no active goals)",
        "items": "\n".join(item_lines) or "(no roadmap items)",
        "plan": "\n".join(f"- [{p.status}] {p.time_block} {p.title}" for p in plan),
        "schedule": sched,
        "free_text": entry.free_text,
        "energy": entry.energy,
    }
    try:
        analysis = await llm.complete_json(prompts.ANALYSIS_SYSTEM, prompts.analysis_prompt(ctx), DayAnalysis)
    except LLMError:
        return rule_draft(entry, goals, targets, tomorrow_budgets, plan), False
    return sanitize(analysis, goals), True


# ---------- confirm ----------

async def _revert_progress(session: AsyncSession, review: DailyReview | None) -> None:
    for p in (review.per_goal or {}).get("_item_progress", []) if review else []:
        item = await session.get(RoadmapItem, p["roadmap_item_id"])
        if item is None:
            continue
        item.hours_logged = max(item.hours_logged - p["hours"], 0)
        if p.get("completed") and item.status == "done":
            item.status = "in_progress"
            item.completed_at = None


async def confirm(
    session: AsyncSession, user: User, entry: DailyEntry, analysis: DayAnalysis, used_llm: bool,
    day_off: bool = False,
) -> DailyReview:
    goals = await tracked_goals(session, user)
    analysis = sanitize(analysis, goals)
    targets = await daily_targets(session, user, goals, entry.date)

    # Re-confirming replaces the previous result, so undo previously credited hours first.
    old_review = await session.scalar(select(DailyReview).where(DailyReview.entry_id == entry.id))
    await _revert_progress(session, old_review)
    entry.activities.clear()  # delete-orphan removes old activities and their links
    if old_review:
        await session.delete(old_review)
        entry.review = None
    await session.flush()

    for a in analysis.activities:
        act = Activity(description=a.description, minutes=a.minutes, kind=a.kind,
                       source="ai" if used_llm else "manual")
        act.links = [ActivityLink(goal_id=link.goal_id, roadmap_item_id=link.roadmap_item_id,
                                  relevance=link.relevance, reason=link.reason) for link in a.links]
        entry.activities.append(act)

    items = {i.id: i for g in goals for i in roadmap.ordered_items(g)}
    applied = []
    for p in analysis.item_progress:
        item = items[p.roadmap_item_id]
        item.hours_logged += p.hours
        completed_now = p.completed and item.status != "done"
        if completed_now:
            item.status, item.completed_at = "done", entry.date
        elif item.status == "todo" and p.hours > 0:
            item.status = "in_progress"
        applied.append({"roadmap_item_id": p.roadmap_item_id, "hours": p.hours, "completed": completed_now})

    today_plan = await plan_for(session, user.id, entry.date)
    adherence = scoring.plan_adherence(
        [scoring.PlanBlock(p.status, p.minutes, p.done_minutes) for p in today_plan])
    streak = await streak_before(session, user.id, entry.date)
    day = scoring.score_day(
        [scoring.ActivityInput(a.minutes, a.kind, [scoring.Link(link.goal_id, link.relevance) for link in a.links])
         for a in analysis.activities],
        [scoring.GoalInput(g.id, g.priority, targets[g.id]) for g in goals],
        llm_impacts={gi.goal_id: gi.impact for gi in analysis.goal_impacts},
        adherence=adherence,
        streak=streak,
        llm_weight=get_settings().llm_weight,
        day_off=day_off,
    )

    per_goal: dict = {}
    for g in goals:
        gs = day.per_goal[g.id]
        st = await timeline.goal_status(session, user, g, entry.date)
        note = next((gi.note for gi in analysis.goal_impacts if gi.goal_id == g.id), "")
        per_goal[str(g.id)] = {"title": g.title, "minutes": gs.minutes, "rule": gs.rule, "llm": gs.llm,
                               "score": gs.score, "note": note, "timeline": st.state,
                               "behind_days": st.behind_days}
    per_goal["_item_progress"] = applied

    review = DailyReview(
        total_score=day.total,
        per_goal=per_goal,
        went_well=analysis.went_well,
        went_badly=analysis.went_badly,
        tip=analysis.tip,
        drift_minutes=day.drift_minutes + day.waste_minutes,
        adherence=adherence,
        used_llm=used_llm,
        rest_day=day.rest_day,
        breakdown=day.breakdown,
    )
    entry.review = review

    await save_plan(session, user, entry.date + timedelta(days=1), analysis.tomorrow)

    entry.draft = None
    entry.analyzed_at = datetime.now(timezone.utc)
    await session.flush()
    return review
