from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

def utcnow() -> datetime:
    """Return the current datetime in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)

def parse_iso(dt_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 string into a timezone-aware datetime."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None

def get_billing_period_start(days_ago: int = 30) -> datetime:
    """Return the start of the billing period relative to now."""
    return utcnow() - timedelta(days=days_ago)

def enforce_temporal_cap(since: Optional[datetime], max_days: int = 366) -> datetime:
    """
    ZENITH PILLAR 4: Enforce a hard temporal window cap.
    If 'since' is earlier than max_days ago, it is capped.
    """
    cap = utcnow() - timedelta(days=max_days)
    if not since or since < cap:
        return cap
    return since

def sanitize_for_csv(value: Any) -> str:
    """
    ZENITH PILLAR 2: Sanitize values for CSV export to prevent Formula Injection.
    Blocks leading =, +, -, @ by prefixing with a single quote.
    """
    s = str(value) if value is not None else ""
    if s and s[0] in ("=", "+", "-", "@"):
        return f"'{s}"
    return s

def get_calendar_billing_period():
    """Return the (start_date, end_date) for the current calendar month."""
    from datetime import date
    import calendar
    today = date.today()
    start = date(today.year, today.month, 1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    return start, date(today.year, today.month, last_day)
