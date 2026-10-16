"""The daily commitment agreed for a goal: hours per working day, days per week, and a weekly routine.

Pace (used for dates and timeline): hours_per_day * days_per_week / 7 per calendar day.
Daily target (used for scoring and tomorrow's plan): the routine's minutes on that weekday.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def block_minutes(start: str, end: str) -> int:
    try:
        sh, sm = map(int, start.split(":"))
        eh, em = map(int, end.split(":"))
    except (ValueError, AttributeError):
        return 0
    mins = (eh * 60 + em) - (sh * 60 + sm)
    return mins + 24 * 60 if mins < 0 else mins


def routine_blocks_on(routine: list[dict], day: date) -> list[dict]:
    wd = WEEKDAYS[day.weekday()]
    return sorted((b for b in routine or [] if wd in b.get("days", [])), key=lambda b: b.get("start", ""))


def routine_minutes_on(routine: list[dict], day: date) -> int:
    return sum(block_minutes(b.get("start", ""), b.get("end", "")) for b in routine_blocks_on(routine, day))


def routine_capacity(routine: list[dict]):
    """Scheduler capacity: each routine block on that weekday as (focus, minutes). focus: learn/build/any."""
    def capacity(day: date) -> list[tuple[str, int]]:
        return [(b.get("focus") or "any", block_minutes(b.get("start", ""), b.get("end", "")))
                for b in routine_blocks_on(routine, day)]
    return capacity


def routine_weekly_minutes(routine: list[dict]) -> int:
    return sum(block_minutes(b.get("start", ""), b.get("end", "")) * len(set(b.get("days", [])))
               for b in routine or [])


def weekly_hours(hours_per_day: float, days_per_week: int) -> float:
    return hours_per_day * days_per_week


def finish_date(remaining_hours: float, start: date, hours_per_day: float, days_per_week: int) -> date:
    pace = weekly_hours(hours_per_day, days_per_week) / 7
    days = max(math.ceil(remaining_hours / pace - 1e-9), 1)
    return start + timedelta(days=days - 1)


def required_hours_per_day(remaining_hours: float, start: date, target: date, days_per_week: int) -> float | None:
    days = (target - start).days + 1
    if days <= 0:
        return None
    working_days = days * days_per_week / 7
    return round(remaining_hours / working_days, 2)


@dataclass
class Option:
    hours_per_day: float
    days_per_week: int
    weekly_hours: float
    finish: date
    meets_target: bool | None


def options(remaining_hours: float, start: date, target: date | None,
            days_per_week_choices: tuple[int, ...] = (5, 6),
            hours_choices: tuple[float, ...] = (1, 1.5, 2, 3)) -> list[Option]:
    """A small menu of paces so the user can see the trade-off between time per day and finish date."""
    out = []
    for dpw in days_per_week_choices:
        for hpd in hours_choices:
            fin = finish_date(remaining_hours, start, hpd, dpw)
            out.append(Option(hpd, dpw, weekly_hours(hpd, dpw), fin, fin <= target if target else None))
    return out
