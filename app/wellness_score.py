from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class DailyMetrics:
    steps: int
    active_minutes: int
    resting_hr: int | None = None
    sleep_hours: float | None = None
    workout_count: int = 0


@dataclass
class ScoreBreakdown:
    score: int
    activity: int
    cardio: int
    recovery: int
    consistency: int


GOALS = {"steps": 8000, "active_minutes": 30, "sleep_hours": 7, "resting_hr_good": 65}


def clamp(n: float, minimum: int = 0, maximum: int = 100) -> int:
    return round(max(minimum, min(maximum, n)))


def score_activity(metrics: DailyMetrics) -> int:
    steps_score = (metrics.steps / GOALS["steps"]) * 100
    active_score = (metrics.active_minutes / GOALS["active_minutes"]) * 100
    return clamp(steps_score * 0.6 + active_score * 0.4)


def score_cardio(metrics: DailyMetrics) -> int:
    if not metrics.resting_hr:
        return 50
    if metrics.resting_hr <= GOALS["resting_hr_good"]:
        return 100
    if metrics.resting_hr >= 90:
        return 20
    return clamp(100 - ((metrics.resting_hr - GOALS["resting_hr_good"]) / 25) * 80)


def score_recovery(metrics: DailyMetrics) -> int:
    if not metrics.sleep_hours:
        return 50
    if GOALS["sleep_hours"] <= metrics.sleep_hours <= 9:
        return 100
    if metrics.sleep_hours < 5:
        return 20
    if metrics.sleep_hours > 9:
        return 70
    return clamp((metrics.sleep_hours / GOALS["sleep_hours"]) * 100)


def score_consistency(active_days_in_window: int, window_days: int) -> int:
    return clamp((active_days_in_window / window_days) * 100)


def calculate_daily_score(
    metrics: DailyMetrics,
    active_days_in_window: int,
    window_days: int = 30,
) -> ScoreBreakdown:
    activity = score_activity(metrics)
    cardio = score_cardio(metrics)
    recovery = score_recovery(metrics)
    consistency = score_consistency(active_days_in_window, window_days)
    score = clamp(activity * 0.3 + cardio * 0.2 + recovery * 0.25 + consistency * 0.25)
    return ScoreBreakdown(score, activity, cardio, recovery, consistency)


def average_score(scores: list[int]) -> int:
    if not scores:
        return 0
    return round(sum(scores) / len(scores))


def count_active_days(snapshots: list[DailyMetrics], min_steps: int = 5000) -> int:
    return sum(1 for s in snapshots if s.steps >= min_steps or s.active_minutes >= 20)


def start_of_day(date: datetime) -> datetime:
    return date.replace(hour=0, minute=0, second=0, microsecond=0)


def days_ago(n: int) -> datetime:
    return start_of_day(datetime.utcnow() - timedelta(days=n))
