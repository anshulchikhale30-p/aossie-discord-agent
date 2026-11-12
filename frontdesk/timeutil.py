"""Time and timezone helpers.

All timestamps stored in the database are ISO-8601 UTC strings. Local times are
converted with the provider organization's IANA timezone.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(utc_now())


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@lru_cache(maxsize=64)
def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def format_dt(value: datetime | str | None, timezone_name: str, include_zone: bool = True) -> str:
    parsed = parse_iso(value) if isinstance(value, str) else value
    if parsed is None:
        return "unknown time"
    local = parsed.astimezone(zone(timezone_name))
    label = local.strftime("%a %d %b %Y, %I:%M %p")
    label = label.replace(" 0", " ")
    if include_zone:
        label = f"{label} {local.tzname() or timezone_name}"
    return label


def format_date(value: datetime | str | None, timezone_name: str) -> str:
    parsed = parse_iso(value) if isinstance(value, str) else value
    if parsed is None:
        return "unknown date"
    return parsed.astimezone(zone(timezone_name)).strftime("%a %d %b %Y")


def local_to_utc(date_text: str, time_text: str, timezone_name: str) -> datetime:
    try:
        local_date = date.fromisoformat(date_text.strip())
    except ValueError as exc:
        raise ValueError("Date must use YYYY-MM-DD.") from exc
    try:
        local_time = time.fromisoformat(time_text.strip())
    except ValueError as exc:
        raise ValueError("Time must use HH:MM (24-hour).") from exc
    local = datetime.combine(local_date, local_time).replace(tzinfo=zone(timezone_name))
    return local.astimezone(UTC)


def weekday_index(value: date | datetime) -> int:
    return value.weekday()


def humanize_delta(value: datetime) -> str:
    seconds = int((value - utc_now()).total_seconds())
    future = seconds >= 0
    seconds = abs(seconds)
    if seconds < 60:
        amount, unit = seconds, "second"
    elif seconds < 3600:
        amount, unit = seconds // 60, "minute"
    elif seconds < 86400:
        amount, unit = seconds // 3600, "hour"
    else:
        amount, unit = seconds // 86400, "day"
    suffix = "" if amount == 1 else "s"
    return f"in {amount} {unit}{suffix}" if future else f"{amount} {unit}{suffix} ago"


def parse_duration(value: str) -> timedelta | None:
    match = re.fullmatch(r"\s*(\d+)\s*([smhdwy])\s*", value.casefold())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    multipliers = {
        "s": timedelta(seconds=1),
        "m": timedelta(minutes=1),
        "h": timedelta(hours=1),
        "d": timedelta(days=1),
        "w": timedelta(weeks=1),
        "y": timedelta(days=365),
    }
    return multipliers[unit] * amount


def parse_expiry(value: str | None, timezone_name: str) -> str | None:
    """Parse a date, duration, or ISO timestamp into a UTC expiry string.

    A date-only value expires at the end of that local day. A duration such as
    ``7d`` expires that far from now.
    """
    if not value or not value.strip():
        return None
    text = value.strip()
    duration = parse_duration(text)
    if duration is not None:
        return iso(utc_now() + duration)
    try:
        local_date = date.fromisoformat(text)
    except ValueError:
        pass
    else:
        end_of_day = datetime.combine(local_date, time(23, 59, 59)).replace(tzinfo=zone(timezone_name))
        return iso(end_of_day)
    parsed = parse_iso(text)
    if parsed is None:
        raise ValueError("Expiry must be YYYY-MM-DD, a duration like 7d, or an ISO timestamp.")
    return iso(parsed)


def parse_effective(value: str | None, timezone_name: str) -> str | None:
    """Parse an effective date, duration, or ISO timestamp into UTC."""
    if not value or not value.strip():
        return None
    text = value.strip()
    duration = parse_duration(text)
    if duration is not None:
        return iso(utc_now() + duration)
    try:
        local_date = date.fromisoformat(text)
    except ValueError:
        pass
    else:
        start_of_day = datetime.combine(local_date, time(0, 0, 0)).replace(tzinfo=zone(timezone_name))
        return iso(start_of_day)
    parsed = parse_iso(text)
    if parsed is None:
        raise ValueError("Effective date must be YYYY-MM-DD, a duration like 7d, or an ISO timestamp.")
    return iso(parsed)


def slot_start(date_text: str, time_text: str, timezone_name: str) -> datetime:
    return local_to_utc(date_text, time_text, timezone_name)
