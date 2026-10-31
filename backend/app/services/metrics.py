"""Measurable targets for goals such as fitness: is the number on course for the target date?"""

from datetime import date

# How far off the straight line from start to target still counts as on track (share of the total change).
TOLERANCE = 0.1


def metric_status(start_value: float, target_value: float, start_date: date, target_date: date | None,
                  latest_value: float | None, today: date) -> dict:
    """Compare the latest value with where a straight line from start to target says it should be today."""
    change = target_value - start_value
    done = (latest_value - start_value) / change if latest_value is not None and change else 0.0
    progress_pct = round(min(max(done, 0), 1) * 100, 1)
    if latest_value is None:
        return {"state": "no_data", "progress_pct": 0.0, "expected_value": None}
    if not target_date or target_date <= start_date:
        return {"state": "no_target_date", "progress_pct": progress_pct, "expected_value": None}
    elapsed = min(max((today - start_date).days / (target_date - start_date).days, 0), 1)
    state = "behind" if done < elapsed - TOLERANCE else "ahead" if done > elapsed + TOLERANCE else "on_track"
    return {"state": state, "progress_pct": progress_pct, "expected_value": round(start_value + change * elapsed, 2)}
