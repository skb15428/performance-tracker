from datetime import date
from types import SimpleNamespace

from app.services.topics import choose, topic_minutes

DAY = date(2026, 11, 2)


def t(id, status="new", est=30, concepts=4, weak=0, planned_for=None, next_review_on=None):
    return SimpleNamespace(understood=[], id=id, status=status, est_minutes=est, concepts=[{}] * concepts,
                           weak_concepts=["x"] * weak, planned_for=planned_for, next_review_on=next_review_on)


def test_order_is_retests_then_carryover_then_new_and_fits_the_time():
    rows = [t(1), t(2), t(3), t(4), t(5, "passed", next_review_on=DAY), t(6, "learning", weak=2)]
    picked = choose(rows, DAY, 60)
    assert [(p.topic.id, p.mode) for p in picked] == [(5, "retest"), (6, "carryover"), (1, "new"), (2, "new")]


def test_retests_are_capped_so_new_learning_still_happens():
    rows = [t(i, "passed", next_review_on=DAY) for i in range(1, 7)] + [t(9)]
    picked = choose(rows, DAY, 60)
    assert sum(p.mode == "retest" for p in picked) == 1
    assert picked[-1].topic.id == 9


def test_failed_topic_costs_only_its_weak_part():
    assert topic_minutes(t(1, "learning", est=40, weak=1)) == 15
    assert topic_minutes(t(1, "learning", est=80, weak=2)) == 40


def test_next_topic_is_offered_even_when_it_overruns_and_planned_topics_are_kept():
    assert [p.topic.id for p in choose([t(1, est=200)], DAY, 60)] == [1]
    assert choose([t(1), t(2, planned_for=DAY)], DAY, 30)[0].topic.id == 2  # chosen for today goes first
