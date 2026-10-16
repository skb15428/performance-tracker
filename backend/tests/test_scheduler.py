from datetime import date

from app.services.commitment import routine_capacity
from app.services.scheduler import SchedItem, even_pace, feasibility, goal_hours_per_day, simulate

MON = date(2026, 10, 12)  # a Monday
ROUTINE = [
    {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "07:00", "end": "08:00", "activity": "Study", "focus": "learn"},
    {"days": ["sat"], "start": "10:00", "end": "13:00", "activity": "Build", "focus": "build"},
]


def test_even_pace_back_to_back():
    items = [SchedItem(1, 0, "topic", 2), SchedItem(2, 0, "topic", 3), SchedItem(3, 0, "topic", 1)]
    slots, finish = simulate(items, date(2026, 1, 1), even_pace(2))
    assert [(slots[i].start.day, slots[i].due.day) for i in (1, 2, 3)] == [(1, 1), (2, 3), (3, 3)]
    assert finish == date(2026, 1, 3)


def test_rest_days_get_no_work():
    # 6h of study at 1h on weekdays: Mon-Fri = 5h, the 6th hour lands on the next Monday (not Sat/Sun)
    slots, finish = simulate([SchedItem(1, 0, "topic", 6)], MON, routine_capacity(ROUTINE[:1]))
    assert slots[1].start == MON and finish == date(2026, 10, 19)


def test_learning_and_building_run_in_parallel():
    items = [SchedItem(1, 0, "topic", 5), SchedItem(2, 0, "task", 3)]
    slots, _ = simulate(items, MON, routine_capacity(ROUTINE))
    assert slots[1].due == date(2026, 10, 16)  # weekdays study finishes Friday
    assert slots[2].start == slots[2].due == date(2026, 10, 17)  # Saturday build block does the task


def test_phases_run_in_order_and_blocks_fall_back():
    # Phase 0 has only learning; the Saturday build block helps with it instead of idling.
    items = [SchedItem(1, 0, "topic", 8), SchedItem(2, 1, "task", 2)]
    slots, _ = simulate(items, MON, routine_capacity(ROUTINE))
    assert slots[1].due == date(2026, 10, 17)  # 5h weekdays + 3h Saturday
    assert slots[2].start == date(2026, 10, 19)  # next phase starts after phase 0 is done


def test_no_capacity_means_no_finish():
    slots, finish = simulate([SchedItem(1, 0, "topic", 2)], MON, lambda _d: [])
    assert finish is None and slots == {}


def test_priority_split_and_feasibility():
    assert goal_hours_per_day(4, 3, [3, 1]) == 3
    assert feasibility(10, MON, date(2026, 10, 20), date(2026, 10, 25)).feasible
    late = feasibility(100, MON, date(2027, 1, 1), date(2026, 10, 21))
    assert not late.feasible and late.required_hours_per_day == 10
