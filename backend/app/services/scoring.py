"""Hybrid daily scoring. Pure functions so they are easy to test and reason about.

Per goal (0-10):  rule = 10 * min(weighted_minutes / target_minutes, 1)
                  score = w * llm_impact + (1 - w) * rule   (rule only if the LLM gave nothing)
Daily total (0-100): priority-weighted mean of goal scores * 10, blended with plan adherence,
minus a waste penalty, plus a small streak bonus.
"""

from dataclasses import dataclass, field

KIND_WEIGHTS = {
    "ship": 1.3,
    "build": 1.2,
    "apply": 1.1,
    "learn": 1.0,
    "network": 1.0,
    "other": 0.7,
    "admin": 0.5,
    "job": 0.0,
    "leisure": 0.0,
    "waste": 0.0,
}
NEUTRAL_KINDS = {"leisure", "job"}  # rest and the day job are neither drift nor waste
ADHERENCE_WEIGHT = 0.2
MAX_WASTE_PENALTY = 15.0
WASTE_PENALTY_PER_HOUR = 3.0
MAX_STREAK_BONUS = 5.0


@dataclass
class Link:
    goal_id: int
    relevance: float = 1.0


@dataclass
class ActivityInput:
    minutes: int
    kind: str
    links: list[Link] = field(default_factory=list)


@dataclass
class GoalInput:
    id: int
    priority: int
    target_minutes: float  # minutes planned for this goal today (0 = rest day for this goal)


@dataclass
class GoalScore:
    minutes: int
    rule: float
    llm: float | None
    score: float


@dataclass
class DayScore:
    total: float
    per_goal: dict[int, GoalScore]
    drift_minutes: int
    waste_minutes: int
    adherence: float | None
    rest_day: bool = False
    breakdown: dict = field(default_factory=dict)


def score_day(
    activities: list[ActivityInput],
    goals: list[GoalInput],
    llm_impacts: dict[int, float] | None = None,
    adherence: float | None = None,
    streak: int = 0,
    llm_weight: float = 0.5,
    day_off: bool = False,
) -> DayScore:
    llm_impacts = llm_impacts or {}
    goal_ids = {g.id for g in goals}
    weighted: dict[int, float] = {g.id: 0.0 for g in goals}
    minutes: dict[int, float] = {g.id: 0.0 for g in goals}
    drift = waste = 0

    for a in activities:
        valid_links = [link for link in a.links if link.goal_id in goal_ids]
        if a.kind == "waste":
            waste += a.minutes
            continue
        if not valid_links:
            if a.kind not in NEUTRAL_KINDS:
                drift += a.minutes
            continue
        # Split an activity's time across the goals it serves, weighted by relevance.
        rel_sum = sum(max(link.relevance, 0) for link in valid_links) or 1.0
        for link in valid_links:
            share = a.minutes * max(link.relevance, 0) / rel_sum
            minutes[link.goal_id] += share
            weighted[link.goal_id] += share * KIND_WEIGHTS.get(a.kind, 0.7) * min(max(link.relevance, 0), 1)

    per_goal: dict[int, GoalScore] = {}
    counted = []  # goals that count toward today's total
    for g in goals:
        if g.target_minutes > 0:
            rule = 10 * min(weighted[g.id] / g.target_minutes, 1.0)
            counted.append(g)
        elif minutes[g.id] > 0:
            rule = 10.0  # extra work on a planned rest day
            counted.append(g)
        else:
            rule = 0.0  # rest day, nothing planned, nothing done: doesn't pull the score down
        llm = llm_impacts.get(g.id)
        if llm is not None:
            llm = min(max(llm, 0.0), 10.0)
            score = llm_weight * llm + (1 - llm_weight) * rule
        else:
            score = rule
        per_goal[g.id] = GoalScore(round(minutes[g.id]), round(rule, 2), llm, round(score, 2))

    # Nothing was planned and nothing done (or the user took the day off): a rest day, not a zero.
    if day_off or (not counted and adherence is None):
        return DayScore(0.0, per_goal, drift, waste, adherence, rest_day=True,
                        breakdown={"rest_day": True, "explanation": "Rest day - not scored"})

    prio_sum = sum(g.priority for g in counted)
    goals_score = sum(per_goal[g.id].score * g.priority for g in counted) / prio_sum * 10 if prio_sum else 0.0
    goals_weight = 1 - ADHERENCE_WEIGHT if adherence is not None else 1.0
    base = goals_weight * goals_score + (ADHERENCE_WEIGHT * adherence * 100 if adherence is not None else 0)
    penalty = min(waste / 60 * WASTE_PENALTY_PER_HOUR, MAX_WASTE_PENALTY)
    bonus = min(streak * 0.5, MAX_STREAK_BONUS)
    total = round(min(max(base - penalty + bonus, 0.0), 100.0), 1)

    parts = [f"goals {goals_score:.0f}" + (f" × {goals_weight:.0%}" if adherence is not None else "")]
    if adherence is not None:
        parts.append(f"plan {adherence:.0%} × {ADHERENCE_WEIGHT:.0%}")
    explanation = " + ".join(parts)
    if penalty:
        explanation += f" − {penalty:.1f} wasted time"
    if bonus:
        explanation += f" + {bonus:.1f} streak"
    explanation += f" = {total}"
    breakdown = {
        "goals_score": round(goals_score, 1), "goals_weight": goals_weight,
        "plan_adherence": round(adherence, 2) if adherence is not None else None,
        "plan_weight": ADHERENCE_WEIGHT if adherence is not None else 0,
        "waste_penalty": round(-penalty, 1), "streak_bonus": round(bonus, 1),
        "goals_counted": [g.id for g in counted], "explanation": explanation,
    }
    return DayScore(total, per_goal, drift, waste, adherence, breakdown=breakdown)


@dataclass
class PlanBlock:
    status: str  # open/done/partial/skipped
    minutes: int
    done_minutes: int | None = None


def plan_adherence(blocks: list[PlanBlock]) -> float | None:
    """Share of the day's planned minutes actually done (partial blocks count their done minutes).
    None if there was no plan."""
    planned = sum(max(b.minutes, 0) for b in blocks)
    if not blocks or planned <= 0:
        return None
    done = 0
    for b in blocks:
        if b.status == "done":
            done += b.minutes
        elif b.status == "partial":
            done += min(max(b.done_minutes or 0, 0), b.minutes)
    return done / planned
