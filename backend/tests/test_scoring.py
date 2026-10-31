import pytest

from app.services.scoring import (
    ActivityInput,
    GoalInput,
    Link,
    PlanBlock,
    WeekGoal,
    plan_adherence,
    score_day,
    score_week,
)

GOALS = [GoalInput(1, priority=4, target_minutes=120), GoalInput(2, priority=2, target_minutes=60)]


def test_full_target_hit_scores_high():
    acts = [ActivityInput(120, "learn", [Link(1)]), ActivityInput(60, "learn", [Link(2)])]
    day = score_day(acts, GOALS)
    assert day.per_goal[1].score == 10 and day.per_goal[2].score == 10
    assert day.total == 100


def test_no_goal_work_is_drift_and_scores_zero():
    day = score_day([ActivityInput(90, "other"), ActivityInput(60, "leisure")], GOALS)
    assert day.total == 0
    assert day.drift_minutes == 90  # leisure is neutral, not drift


def test_llm_impact_blends_with_rules():
    acts = [ActivityInput(60, "learn", [Link(1)])]  # half the target -> rule 5
    rule_only = score_day(acts, GOALS)
    blended = score_day(acts, GOALS, llm_impacts={1: 9}, llm_weight=0.5)
    assert rule_only.per_goal[1].score == 5
    assert blended.per_goal[1].score == 7
    assert blended.per_goal[1].llm == 9


def test_waste_penalty_and_streak_bonus():
    acts = [ActivityInput(60, "learn", [Link(1)]), ActivityInput(120, "waste")]
    base = score_day(acts[:1], GOALS)
    penalised = score_day(acts, GOALS)
    assert penalised.total == pytest.approx(base.total - 6, abs=0.1)
    assert score_day(acts[:1], GOALS, streak=4).total == pytest.approx(base.total + 2, abs=0.1)


def test_unknown_goal_links_ignored_and_split_by_relevance():
    acts = [ActivityInput(60, "build", [Link(1, 0.5), Link(2, 0.5), Link(99, 1)])]
    day = score_day(acts, GOALS)
    assert day.per_goal[1].minutes == 30 and day.per_goal[2].minutes == 30


def test_adherence_blend():
    assert plan_adherence([]) is None
    assert plan_adherence([PlanBlock("done", 60), PlanBlock("skipped", 60), PlanBlock("partial", 60, 30), PlanBlock("open", 60)]) == 0.375
    day = score_day([], GOALS, adherence=1.0)
    assert day.total == 20


def test_rest_day_is_not_scored():
    rest = [GoalInput(1, 3, target_minutes=0)]
    assert score_day([], rest).rest_day  # nothing planned, nothing done, no plan
    assert score_day([], rest, adherence=0.0).rest_day  # a session the user added and then skipped costs nothing
    assert score_day([ActivityInput(60, "learn", [Link(1)])], GOALS, day_off=True).rest_day


def test_rest_day_work_is_a_bonus_not_a_score():
    rest = [GoalInput(1, 3, target_minutes=0)]
    day = score_day([ActivityInput(15, "learn", [Link(1)])], rest, llm_impacts={1: 8}, adherence=1.0, time_value=9,
                    streak=4)
    assert day.rest_day and day.total == 0
    assert day.breakdown["bonus_minutes"] == 15 and "15 min" in day.breakdown["explanation"]
    assert day.per_goal[1].minutes == 15


def test_breakdown_explains_total():
    acts = [ActivityInput(60, "learn", [Link(1)]), ActivityInput(60, "waste")]
    day = score_day(acts, GOALS, adherence=0.5, streak=2)
    b = day.breakdown
    assert b["plan_adherence"] == 0.5 and b["waste_penalty"] == -3.0 and b["streak_bonus"] == 1.0
    assert b["explanation"].endswith(f"= {day.total}") and "plan 50% × 20%" in b["explanation"]


def week(done, target=720, quality=None, priority=3, id=1):
    return WeekGoal(id, priority, target_minutes=target, counted_minutes=done, quality=quality)


def test_week_score_is_hours_scaled_by_quality():
    assert score_week([week(720)]).total == 100  # no rating: hours alone
    assert score_week([week(360)]).total == 50
    assert score_week([week(720, quality=10)]).total == 100
    assert score_week([week(720, quality=0)]).total == 50  # poor work keeps half of what the hours earned
    assert score_week([week(720, quality=6)], time_value=8).total == 83  # quality 6.6


def test_great_work_cant_make_up_for_missing_hours():
    assert score_week([week(60, quality=10)], time_value=10).total < 10  # one hour of a twelve-hour week


def test_extra_hours_stop_at_the_target_and_nothing_expected_is_no_score():
    assert score_week([week(900)]).total == 100
    assert score_week([week(60, target=0)]) is None


def test_week_score_weighs_goals_by_priority_and_takes_off_wasted_time():
    assert score_week([week(720, priority=3), week(0, priority=1, id=2)]).total == 75
    assert score_week([week(720)], waste_minutes=300).total == 95
    assert score_week([week(720)], waste_minutes=6000).total == 85  # capped


def test_a_day_records_what_counts_toward_the_week():
    goals = [GoalInput(1, 3, target_minutes=120)]
    day = score_day([ActivityInput(60, "build", [Link(1)]), ActivityInput(60, "admin", [Link(1)]),
                     ActivityInput(60, "learn", [Link(1, relevance=0.5)])], goals)
    assert day.per_goal[1].minutes == 180 and day.per_goal[1].counted_minutes == 120  # 60 + 30 + 30
