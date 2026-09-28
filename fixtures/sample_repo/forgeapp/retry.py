"""Exponential backoff schedule for flaky deploy steps."""


def backoff_delays(base: float, factor: float, attempts: int, cap: float) -> list[float]:
    """Delays for each retry attempt, never exceeding cap."""
    delays = []
    for attempt in range(attempts):
        delays.append(min(cap, base * (factor ** attempt)))
    return delays
