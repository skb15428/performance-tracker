"""Decides whether a topic is learned from interview marks. Pure functions: Claude marks answers, these rules decide."""

from dataclasses import dataclass
from datetime import date, timedelta

PASS_PCT = 85.0
CORE_MIN = 4.0  # average mark (0-5) every core concept needs
EXTRA_MIN = 3.0  # below this a non-core concept is listed as weak, but doesn't block a pass
REVIEW_DAYS = (3, 7, 21)


@dataclass
class Evaluation:
    overall_pct: float
    passed: bool
    concept_scores: dict[str, float]
    weak_concepts: list[str]
    untested: list[str]  # core concepts with no marked question
    reason: str


def evaluate(questions: list[dict], concepts: list[dict], retest: bool = False) -> Evaluation:
    """Pass needs >= 85% overall and every core concept averaging >= 4/5. A first interview must cover every core
    concept and include follow-up questions; a short re-test only has to hold up on what it asked."""
    if not questions:
        return Evaluation(0.0, False, {}, [c["name"] for c in concepts], [], "No marked answers.")
    marks: dict[str, list[float]] = {}
    for q in questions:
        marks.setdefault(q["concept"].strip().lower(), []).append(float(q["score"]))
    scores = {name: round(sum(v) / len(v), 2) for name, v in marks.items()}
    overall = round(sum(float(q["score"]) for q in questions) / len(questions) / 5 * 100, 1)

    canonical = {c["name"].strip().lower(): c for c in concepts}
    named = {canonical[k]["name"] if k in canonical else k: v for k, v in scores.items()}
    core = [c["name"] for c in concepts if c.get("core", True)]
    asked = {k for k in scores}
    untested = [] if retest else [n for n in core if n.strip().lower() not in asked]

    weak = [n for n in core if n.strip().lower() in scores and scores[n.strip().lower()] < CORE_MIN]
    weak += [c["name"] for c in concepts
             if not c.get("core", True) and scores.get(c["name"].strip().lower(), 5) < EXTRA_MIN]
    weak += untested

    reasons = []
    if overall < PASS_PCT:
        reasons.append(f"overall {overall:.0f}% is below {PASS_PCT:.0f}%")
    if any(n in weak for n in core):
        reasons.append("some core subtopics are below 4/5 or weren't tested")
    no_follow_ups = not retest and not any(q.get("is_follow_up") for q in questions)
    if no_follow_ups:
        reasons.append("no follow-up questions were asked")
    passed = not reasons
    return Evaluation(overall, passed, named, weak, untested, "Passed." if passed else "Not yet: " + "; ".join(reasons) + ".")


def next_review(review_stage: int, day: date) -> date | None:
    """Re-test date after `review_stage` re-tests have been passed; None once all are done."""
    if review_stage >= len(REVIEW_DAYS):
        return None
    return day + timedelta(days=REVIEW_DAYS[review_stage])


def apply_result(topic, result: Evaluation, retest: bool, day: date) -> None:
    """Update a topic after an interview. Failing carries only the weak subtopics to the next day."""
    topic.attempts += 1
    topic.last_pct = result.overall_pct
    topic.best_pct = max(topic.best_pct or 0, result.overall_pct)
    topic.concept_scores = {**(topic.concept_scores or {}), **result.concept_scores}
    if result.passed:
        topic.status = "passed"
        topic.weak_concepts = []
        topic.planned_for = None
        topic.passed_on = topic.passed_on or day
        topic.review_stage = topic.review_stage + 1 if retest else 0
        topic.next_review_on = next_review(topic.review_stage, day)
    else:
        topic.status = "learning"
        topic.weak_concepts = result.weak_concepts
        topic.planned_for = day + timedelta(days=1)
        topic.passed_on = None
        topic.review_stage = 0
        topic.next_review_on = None
