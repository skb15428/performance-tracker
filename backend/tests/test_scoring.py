import pytest

from app.services.scoring import ActivityInput, GoalInput, Link, PlanBlock, plan_adherence, score_day

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
    assert not score_day([], rest, adherence=0.0).rest_day  # there was a plan for the day
    assert score_day([ActivityInput(60, "learn", [Link(1)])], GOALS, day_off=True).rest_day


def test_breakdown_explains_total():
    acts = [ActivityInput(60, "learn", [Link(1)]), ActivityInput(60, "waste")]
    day = score_day(acts, GOALS, adherence=0.5, streak=2)
    b = day.breakdown
    assert b["plan_adherence"] == 0.5 and b["waste_penalty"] == -3.0 and b["streak_bonus"] == 1.0
    assert b["explanation"].endswith(f"= {day.total}") and "plan 50% × 20%" in b["explanation"]
