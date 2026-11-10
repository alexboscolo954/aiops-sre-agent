"""Scheduled Checks (slice 8.1): when a Check is next due.

A Check's schedule is a 5-field cron expression in its own time zone (DST included),
at most once every MIN_GAP seconds: each Run costs tokens.
"""

from datetime import UTC, datetime
from itertools import islice, pairwise
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cronsim import CronSim, CronSimError

MIN_GAP = 15 * 60
SAMPLE = 200  # fire times checked for the gap; cron patterns repeat well within it


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown time zone {name!r}") from e


def next_due(schedule: str, timezone: str, after: float) -> float:
    """The first fire time strictly after `after` (epoch seconds)."""
    start = datetime.fromtimestamp(after, UTC).astimezone(zone(timezone))
    return next(CronSim(schedule, start)).timestamp()


def validate(schedule: str, timezone: str) -> None:
    """Raises ValueError for a bad expression or zone, or a schedule faster than
    MIN_GAP anywhere in its first SAMPLE fire times."""
    try:
        start = datetime(2026, 1, 1, tzinfo=zone(timezone))
        times = [t.timestamp() for t in islice(CronSim(schedule, start), SAMPLE)]
    except CronSimError as e:
        raise ValueError(f"bad cron schedule {schedule!r}: {e}") from e
    gaps = [b - a for a, b in pairwise(times)]
    if gaps and min(gaps) < MIN_GAP:
        raise ValueError(
            f"schedule {schedule!r} runs {int(min(gaps) // 60)} minutes apart: at most once "
            f"every {MIN_GAP // 60} minutes"
        )
