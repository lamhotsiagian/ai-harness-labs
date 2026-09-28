"""Business-day helpers for release scheduling."""
from datetime import date, timedelta


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def business_days_between(start: date, end: date) -> int:
    """Count business days in [start, end)."""
    days = 0
    current = start
    while current < end:
        if not is_weekend(current):
            days += 1
        current += timedelta(days=1)
    return days
