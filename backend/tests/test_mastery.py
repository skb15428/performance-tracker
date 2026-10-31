from datetime import date
from types import SimpleNamespace

from app.services.mastery import apply_result, evaluate, next_review
from app.services.metrics import metric_status
from app.services.scoring import ActivityInput, GoalInput, Link, score_day

CONCEPTS = [{"name": "BFS", "core": True}, {"name": "DFS", "core": True}, {"name": "A*", "core": False}]
DAY = date(2026, 11, 2)


def q(concept, score, follow_up=False):
    return {"concept": concept, "score": score, "is_follow_up": follow_up}


def topic(**kw):
    base = dict(attempts=0, last_pct=None, best_pct=None, concept_scores={}, status="new", weak_concepts=[],
                planned_for=None, passed_on=None, review_stage=0, next_review_on=None)
    return SimpleNamespace(**{**base, **kw})


def test_pass_needs_85_percent_all_core_and_follow_ups():
    good = evaluate([q("BFS", 5), q("DFS", 4.5, True)], CONCEPTS)
    assert good.passed and good.overall_pct == 95 and good.weak_concepts == []

    assert not evaluate([q("BFS", 4), q("DFS", 4, True)], CONCEPTS).passed  # 80% overall
    core_weak = evaluate([q("BFS", 5), q("BFS", 5, True), q("BFS", 5), q("DFS", 3.5)], CONCEPTS)
    assert core_weak.overall_pct >= 85 and not core_weak.passed and core_weak.weak_concepts == ["DFS"]
    no_follow = evaluate([q("BFS", 5), q("DFS", 5)], CONCEPTS)
    assert not no_follow.passed and "follow-up" in no_follow.reason


def test_untested_core_concept_blocks_a_first_pass_but_not_a_retest():
    first = evaluate([q("BFS", 5), q("BFS", 5, True)], CONCEPTS)
    assert not first.passed and first.untested == ["DFS"] and "DFS" in first.weak_concepts
    assert evaluate([q("BFS", 5)], CONCEPTS, retest=True).passed


def test_a_weak_extra_concept_is_listed_but_does_not_block():
    r = evaluate([q("BFS", 5), q("DFS", 5, True), q("BFS", 5), q("DFS", 5), q("A*", 2.5)], CONCEPTS)
    assert r.passed and r.weak_concepts == ["A*"]


def test_review_schedule_and_failed_retest():
    assert next_review(0, DAY) == date(2026, 11, 5) and next_review(2, DAY) == date(2026, 11, 23)
    assert next_review(3, DAY) is None

    t = topic()
    apply_result(t, evaluate([q("BFS", 5), q("DFS", 5, True)], CONCEPTS), False, DAY)
    assert t.status == "passed" and t.next_review_on == date(2026, 11, 5)
    apply_result(t, evaluate([q("BFS", 5)], CONCEPTS, retest=True), True, date(2026, 11, 5))
    assert t.review_stage == 1 and t.next_review_on == date(2026, 11, 12)

    apply_result(t, evaluate([q("BFS", 2)], CONCEPTS, retest=True), True, date(2026, 11, 12))
    assert t.status == "learning" and t.weak_concepts == ["BFS"] and t.review_stage == 0
    assert t.next_review_on is None and t.planned_for == date(2026, 11, 13) and t.passed_on is None


def test_day_is_scored_on_value_of_time_not_following_the_plan():
    goals = [GoalInput(1, 3, target_minutes=120)]
    acts = [ActivityInput(120, "learn", [Link(1)])]
    # Skipped everything planned, but the off-plan work was worth it
    valuable = score_day(acts, goals, adherence=0.0, time_value=9)
    assert valuable.total == 97 and "time use 90%" in valuable.breakdown["explanation"]
    assert score_day(acts, goals, adherence=0.0, time_value=2).total < valuable.total
    assert score_day(acts, goals, adherence=0.0).total == 80  # rules-only days still use the plan


def test_metric_on_course():
    start, target = date(2026, 11, 1), date(2026, 12, 31)
    mid = date(2026, 12, 1)
    assert metric_status(82, 76, start, target, 79, mid)["state"] == "on_track"
    behind = metric_status(82, 76, start, target, 81.5, mid)
    assert behind["state"] == "behind" and behind["expected_value"] == 79.0
    assert metric_status(82, 76, start, target, 77, mid)["state"] == "ahead"
    assert metric_status(82, 76, start, target, None, mid)["state"] == "no_data"
