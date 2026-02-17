"""Shared utilities used across autonomy runtime tools.

This module centralizes repeated helpers (time, env parsing, phone normalize,
and business-hours checks) to keep behavior consistent across the live job.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

UTC = timezone.utc

_US_PHONE_RE = re.compile(r"\D+")

# Best-effort US state -> IANA timezone mapping.
STATE_TZ: dict[str, str] = {
    "AL": "America/Chicago",
    "AK": "America/Anchorage",
    "AZ": "America/Phoenix",
    "AR": "America/Chicago",
    "CA": "America/Los_Angeles",
    "CO": "America/Denver",
    "CT": "America/New_York",
    "DC": "America/New_York",
    "DE": "America/New_York",
    "FL": "America/New_York",
    "GA": "America/New_York",
    "HI": "Pacific/Honolulu",
    "IA": "America/Chicago",
    "ID": "America/Denver",
    "IL": "America/Chicago",
    "IN": "America/Indiana/Indianapolis",
    "KS": "America/Chicago",
    "KY": "America/New_York",
    "LA": "America/Chicago",
    "MA": "America/New_York",
    "MD": "America/New_York",
    "ME": "America/New_York",
    "MI": "America/New_York",
    "MN": "America/Chicago",
    "MO": "America/Chicago",
    "MS": "America/Chicago",
    "MT": "America/Denver",
    "NC": "America/New_York",
    "ND": "America/Chicago",
    "NE": "America/Chicago",
    "NH": "America/New_York",
    "NJ": "America/New_York",
    "NM": "America/Denver",
    "NV": "America/Los_Angeles",
    "NY": "America/New_York",
    "OH": "America/New_York",
    "OK": "America/Chicago",
    "OR": "America/Los_Angeles",
    "PA": "America/New_York",
    "RI": "America/New_York",
    "SC": "America/New_York",
    "SD": "America/Chicago",
    "TN": "America/Chicago",
    "TX": "America/Chicago",
    "UT": "America/Denver",
    "VA": "America/New_York",
    "VT": "America/New_York",
    "WA": "America/Los_Angeles",
    "WI": "America/Chicago",
    "WV": "America/New_York",
    "WY": "America/Denver",
}


def now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def truthy(val: str | None, *, default: bool = False) -> bool:
    if val is None:
        return default
    cleaned = str(val).strip().lower()
    if not cleaned:
        return default
    return cleaned in {"1", "true", "yes", "on"}


def state_tz(state: str) -> str:
    return STATE_TZ.get((state or "").strip().upper(), "America/New_York")


def normalize_us_phone(raw: str) -> str:
    """Normalize common US phone formats to E.164. Returns empty string if invalid."""
    digits = _US_PHONE_RE.sub("", (raw or "").strip())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    return f"+1{digits}"


def is_business_hours(state: str, start_hour: int = 9, end_hour: int = 17) -> bool:
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        return True

    tz_name = state_tz(state)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")

    now_local = datetime.now(tz)
    if now_local.weekday() >= 5:
        return False
    return int(start_hour) <= int(now_local.hour) < int(end_hour)
