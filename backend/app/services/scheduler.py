"""Rule-based timeline scheduling: turns ordered roadmap items into calendar dates.

The scheduler walks the calendar day by day and spends each day's time blocks on roadmap items:
- Phases run in order: an item of the next phase starts only when the current phase is finished.
- Within a phase, "learn" time goes to topics/skills and "build" time to tasks/milestones, so studying and
  project work progress in parallel. If a block's kind of work is used up in the phase, it takes the other kind
  rather than sit idle. "any" time takes the next item in roadmap order.
- Days with no time (rest days in the routine) get nothing.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

MAX_DAYS = 365 * 5
LEARN_TYPES = {"topic", "skill"}

Block = tuple[str, int]  # (focus: learn/build/any, minutes)
CapacityFn = Callable[[date], list[Block]]


@dataclass
class ScheduledSlot:
    start: date
    due: date


@dataclass
class SchedItem:
    id: int
    phase: int  # position of its phase in the roadmap
    type: str  # topic/skill/task/milestone
    hours: float  # remaining hours


@dataclass
class Feasibility:
    feasible: bool
    realistic_date: date
    required_hours_per_day: float | None


def goal_hours_per_day(daily_available_hours: float, priority: int, all_priorities: list[int]) -> float:
    """Split the user's daily hours across active goals in proportion to priority."""
    total = sum(all_priorities) or priority or 1
    return max(daily_available_hours * priority / total, 0.25)


def track_of(item_type: str) -> str:
    return "learn" if item_type in LEARN_TYPES else "build"


def even_pace(hours_per_day: float) -> CapacityFn:
    """The same amount of 'any' time every day (used until a weekly routine is agreed)."""
    minutes = max(round(hours_per_day * 60), 1)
    return lambda _day: [("any", minutes)]


def simulate(items: list[SchedItem], start: date, capacity: CapacityFn,
             daily: dict[date, int] | None = None) -> tuple[dict[int, ScheduledSlot], date | None]:
    """Spend each day's blocks on the items. Returns {item_id: slot} and the finish date (None if never).
    If `daily` is given, it's filled with the minutes of work planned on each day."""
    remaining = {i.id: max(round(i.hours * 60), 1) for i in items}
    first: dict[int, date] = {}
    last: dict[int, date] = {}
    phases = sorted({i.phase for i in items})
    by_phase = {p: [i for i in items if i.phase == p] for p in phases}
    phase_idx = 0

    def pick(focus: str) -> SchedItem | None:
        nonlocal phase_idx
        while phase_idx < len(phases):
            open_items = [i for i in by_phase[phases[phase_idx]] if remaining[i.id] > 0]
            if not open_items:
                phase_idx += 1
                continue
            if focus != "any":
                for i in open_items:
                    if track_of(i.type) == focus:
                        return i
            return open_items[0]
        return None

    day = start
    for _ in range(MAX_DAYS):
        if phase_idx >= len(phases):
            break
        for focus, minutes in capacity(day):
            while minutes > 0:
                item = pick(focus)
                if item is None:
                    break
                spend = min(minutes, remaining[item.id])
                remaining[item.id] -= spend
                minutes -= spend
                if daily is not None:
                    daily[day] = daily.get(day, 0) + spend
                first.setdefault(item.id, day)
                last[item.id] = day
        if all(v <= 0 for v in remaining.values()):
            break
        day += timedelta(days=1)

    if any(v > 0 for v in remaining.values()):
        return {i: ScheduledSlot(first[i], last[i]) for i in first if remaining[i] <= 0}, None
    slots = {i.id: ScheduledSlot(first[i.id], last[i.id]) for i in items}
    return slots, max(s.due for s in slots.values()) if slots else None


def feasibility(total_hours: float, start: date, finish: date | None, target: date | None) -> Feasibility:
    realistic = finish or start + timedelta(days=MAX_DAYS)
    if target is None:
        return Feasibility(finish is not None, realistic, None)
    days = (target - start).days + 1
    required = round(total_hours / days, 2) if days > 0 else None
    return Feasibility(finish is not None and realistic <= target, realistic, required)
