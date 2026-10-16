from datetime import date

from app.services.commitment import (
    finish_date,
    options,
    required_hours_per_day,
    routine_minutes_on,
    routine_weekly_minutes,
)
from app.services.scoring import ActivityInput, GoalInput, Link, score_day

ROUTINE = [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:00", "end": "08:30", "activity": "Study"},
           {"days": ["sat"], "start": "10:00", "end": "13:00", "activity": "Build"}]
MON, SAT, SUN = date(2026, 10, 12), date(2026, 10, 17), date(2026, 10, 18)


def test_routine_minutes():
    assert routine_minutes_on(ROUTINE, MON) == 90
    assert routine_minutes_on(ROUTINE, SAT) == 180
    assert routine_minutes_on(ROUTINE, SUN) == 0
    assert routine_weekly_minutes(ROUTINE) == 5 * 90 + 180


def test_pace_and_target_tradeoff():
    # 42h at 1h/day, 6 days/week = 6h/week -> 7 weeks
    assert finish_date(42, MON, 1, 6) == date(2026, 11, 29)
    assert required_hours_per_day(42, MON, date(2026, 11, 29), 6) == 1.0
    menu = options(42, MON, date(2026, 11, 1))
    assert any(o.meets_target for o in menu) and not all(o.meets_target for o in menu)


def test_rest_day_goal_does_not_drag_score():
    goals = [GoalInput(1, 4, target_minutes=90), GoalInput(2, 2, target_minutes=0)]  # goal 2 rests today
    day = score_day([ActivityInput(90, "learn", [Link(1)])], goals)
    assert day.total == 100
    bonus = score_day([ActivityInput(90, "learn", [Link(1)]), ActivityInput(30, "build", [Link(2)])], goals)
    assert bonus.per_goal[2].score == 10


def test_rest_weekdays_from_routines():
    from types import SimpleNamespace

    from app.services.analysis import rest_weekdays
    g = SimpleNamespace(status="active", intake_status="active", routine=ROUTINE)
    assert rest_weekdays([g]) == {6}  # only Sunday has nothing planned
    no_routine = SimpleNamespace(status="active", intake_status="active", routine=[])
    assert rest_weekdays([g, no_routine]) == set()  # a goal without a routine works every day
