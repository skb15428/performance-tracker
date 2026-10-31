"""Scoring. Pure functions so they are easy to test and reason about.

The score the user sees is weekly (score_week): hours against the week's target, however they were spread over the
days, scaled by how good the work was. score_day rates a single day for patterns and doesn't reach the user as a score.

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
# Toward the week's hours everything linked to a goal counts in full, such as a gym session logged as "other", except
# admin and kinds that aren't work on a goal.
COUNTED_WEIGHTS = {"admin": 0.5, "job": 0.0, "leisure": 0.0, "waste": 0.0}
NEUTRAL_KINDS = {"leisure", "job"}  # rest and the day job are neither drift nor waste
ADHERENCE_WEIGHT = 0.2  # rules-only days, when no judgement of the time is available
TIME_VALUE_WEIGHT = 0.3
MAX_WASTE_PENALTY = 15.0
WASTE_PENALTY_PER_HOUR = 3.0
WEEK_WASTE_PENALTY_PER_HOUR = 1.0  # a week has far more hours to lose than a day
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
    counted_minutes: float = 0.0  # what counts toward the week's hours: relevant work, with low-value kinds discounted


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
    time_value: float | None = None,
) -> DayScore:
    llm_impacts = llm_impacts or {}
    goal_ids = {g.id for g in goals}
    weighted: dict[int, float] = {g.id: 0.0 for g in goals}
    minutes: dict[int, float] = {g.id: 0.0 for g in goals}
    counted_minutes: dict[int, float] = {g.id: 0.0 for g in goals}
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
            counted_minutes[link.goal_id] += share * COUNTED_WEIGHTS.get(a.kind, 1.0) * min(max(link.relevance, 0), 1)

    per_goal: dict[int, GoalScore] = {}
    counted = []  # goals that count toward today's total
    for g in goals:
        if g.target_minutes > 0:
            rule = 10 * min(weighted[g.id] / g.target_minutes, 1.0)
            counted.append(g)
        else:
            rule = 0.0  # nothing planned today: extra work earns hours, and never moves the score either way
        llm = llm_impacts.get(g.id)
        if llm is not None:
            llm = min(max(llm, 0.0), 10.0)
            score = llm_weight * llm + (1 - llm_weight) * rule
        else:
            score = rule
        per_goal[g.id] = GoalScore(round(minutes[g.id]), round(rule, 2), llm, round(score, 2),
                                   round(counted_minutes[g.id], 1))

    # No goal had time planned (or the user took the day off): a rest day has no rating of its own. Work done anyway
    # is a bonus: its hours and quality still go into the week.
    if day_off or not counted:
        extra = round(sum(minutes.values()))
        explanation = f"Rest day - {extra} min of extra work credited" if extra else "Rest day"
        return DayScore(0.0, per_goal, drift, waste, adherence, rest_day=True,
                        breakdown={"rest_day": True, "bonus_minutes": extra, "explanation": explanation,
                                   "time_value": time_value, "waste_minutes": waste})

    prio_sum = sum(g.priority for g in counted)
    goals_score = sum(per_goal[g.id].score * g.priority for g in counted) / prio_sum * 10 if prio_sum else 0.0
    if time_value is not None:  # judged on the value of the time, so off-plan work isn't penalised
        side_label, side_pct, side_weight = "time use", min(max(time_value, 0), 10) * 10, TIME_VALUE_WEIGHT
    elif adherence is not None:
        side_label, side_pct, side_weight = "plan", adherence * 100, ADHERENCE_WEIGHT
    else:
        side_label, side_pct, side_weight = "", 0.0, 0.0
    goals_weight = 1 - side_weight
    base = goals_weight * goals_score + side_weight * side_pct
    penalty = min(waste / 60 * WASTE_PENALTY_PER_HOUR, MAX_WASTE_PENALTY)
    bonus = min(streak * 0.5, MAX_STREAK_BONUS)
    total = round(min(max(base - penalty + bonus, 0.0), 100.0), 1)

    parts = [f"goals {goals_score:.0f}" + (f" × {goals_weight:.0%}" if side_weight else "")]
    if side_weight:
        parts.append(f"{side_label} {side_pct:.0f}% × {side_weight:.0%}")
    explanation = " + ".join(parts)
    if penalty:
        explanation += f" − {penalty:.1f} wasted time"
    if bonus:
        explanation += f" + {bonus:.1f} streak"
    explanation += f" = {total}"
    breakdown = {
        "goals_score": round(goals_score, 1), "goals_weight": goals_weight,
        "plan_adherence": round(adherence, 2) if adherence is not None else None,
        "time_value": time_value, "waste_minutes": waste,
        "waste_penalty": round(-penalty, 1), "streak_bonus": round(bonus, 1),
        "goals_counted": [g.id for g in counted], "explanation": explanation,
    }
    return DayScore(total, per_goal, drift, waste, adherence, breakdown=breakdown)


@dataclass
class WeekGoal:
    id: int
    priority: int
    target_minutes: float  # what's expected this week (so far, while the week is running)
    counted_minutes: float
    quality: float | None = None  # Claude's 0-10 rating of the work, averaged over the week's time


@dataclass
class WeekScore:
    total: float
    hours_pct: float
    quality: float | None
    explanation: str


def score_week(goals: list[WeekGoal], time_value: float | None = None, waste_minutes: int = 0,
               llm_weight: float = 0.5) -> WeekScore | None:
    """The week's score (0-100), None until some time is expected.

    Hours set the ceiling: only the week's total counts, so any split across days is fine, and extra hours can't earn
    more than 100%. Quality decides how much of that ceiling is kept, down to 1 - llm_weight for the poorest work. It
    scales the hours rather than adding to them, so great work in one hour of a twelve-hour week still scores low."""
    counted = [g for g in goals if g.target_minutes > 0]
    if not counted:
        return None
    side = min(max(time_value, 0), 10) if time_value is not None else None

    def blended(impact: float | None) -> float | None:
        if impact is None or side is None:
            return impact if impact is not None else side
        return (1 - TIME_VALUE_WEIGHT) * min(max(impact, 0), 10) + TIME_VALUE_WEIGHT * side

    prio_sum = sum(g.priority for g in counted)
    hours = goals_score = quality_sum = quality_prio = 0.0
    for g in counted:
        fraction = min(g.counted_minutes / g.target_minutes, 1.0)
        hours += g.priority * fraction
        quality = blended(g.quality) if g.counted_minutes else None
        keeps = 1 if quality is None else 1 - llm_weight + llm_weight * quality / 10
        goals_score += g.priority * fraction * keeps
        if quality is not None:
            quality_sum += g.priority * quality
            quality_prio += g.priority
    hours_pct = hours / prio_sum * 100
    average_quality = round(quality_sum / quality_prio, 1) if quality_prio else None
    penalty = min(waste_minutes / 60 * WEEK_WASTE_PENALTY_PER_HOUR, MAX_WASTE_PENALTY)
    total = round(min(max(goals_score / prio_sum * 100 - penalty, 0.0), 100.0), 1)

    parts = [f"hours {hours_pct:.0f}%"]
    if average_quality is not None:
        parts.append(f"work quality {average_quality}/10")
    explanation = " · ".join(parts)
    if penalty:
        explanation += f" − {penalty:.1f} wasted time"
    return WeekScore(total, round(hours_pct, 1), average_quality, f"{explanation} = {total}")


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
