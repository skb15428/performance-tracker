from datetime import date

from app.services.timeline import ItemProgressView, compute_status, planned_fraction


def test_planned_fraction():
    assert planned_fraction(date(2026, 1, 1), date(2026, 1, 4), date(2026, 1, 2)) == 0.5
    assert planned_fraction(date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 2)) == 0


def test_behind_and_on_track():
    items = [ItemProgressView(10, 0, "todo", date(2026, 1, 1), date(2026, 1, 5)),
             ItemProgressView(10, 0, "todo", date(2026, 1, 6), date(2026, 1, 10))]
    st = compute_status(items, date(2026, 1, 8), hours_per_day=2)
    assert st.state == "behind" and st.overdue_items == 1 and st.behind_days == 7
    items[0] = ItemProgressView(10, 10, "done", date(2026, 1, 1), date(2026, 1, 5))
    items[1] = ItemProgressView(10, 6, "in_progress", date(2026, 1, 6), date(2026, 1, 10))
    assert compute_status(items, date(2026, 1, 8), hours_per_day=2).state == "on_track"


def test_not_started():
    items = [ItemProgressView(5, 0, "todo", date(2026, 2, 1), date(2026, 2, 3))]
    assert compute_status(items, date(2026, 1, 8), 2).state == "not_started"


def test_baseline_lookup_and_status():
    from app.services.roadmap import baseline_length_days, baseline_planned, make_baseline
    start = date(2026, 1, 5)  # Monday
    # 90 min Mon-Fri, nothing at the weekend, 2h already done when the plan was agreed
    daily = {date(2026, 1, d): 90 for d in (5, 6, 7, 8, 9, 12)}
    bl = make_baseline(start, daily, done_at_start=2)
    assert baseline_planned(bl, date(2026, 1, 4)) == 2  # before the plan started
    assert baseline_planned(bl, date(2026, 1, 9)) == 2 + 7.5
    assert baseline_planned(bl, date(2026, 1, 11)) == 2 + 7.5  # weekend: nothing more was planned
    assert baseline_length_days(bl) == 8

    items = [ItemProgressView(20, 2 + 3, "in_progress", start, date(2026, 1, 20))]
    st = compute_status(items, date(2026, 1, 12), hours_per_day=7.5 / 7, baseline=bl)
    # owed by Sunday night: 9.5h, done 5h -> 4.5h behind = ~4.2 days at this pace; threshold for an 8-day plan is 2
    assert st.planned_hours == 9.5 and st.state == "behind" and st.threshold_days == 2


def test_threshold_scales_with_plan_length():
    from app.services.timeline import threshold_days
    assert threshold_days(20) == 2 and threshold_days(100) == 5 and threshold_days(365) == 7
