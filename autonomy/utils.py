"""Shared utilities for the autonomy package.

Consolidates duplicated helpers that were previously copy-pasted across
tools/twilio_autocall.py, tools/twilio_sms.py, tools/live_job.py,
tools/log_call.py, tools/call_list.py, tools/funnel_watchdog.py, and
providers.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

UTC = timezone.utc

US_PHONE_RE = re.compile(r"\D+")

# US state -> IANA timezone (best-effort for multi-TZ states).
STATE_TZ: dict[str, str] = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DC": "America/New_York", "DE": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}


def now_utc_iso() -> str:
    """UTC timestamp without microseconds, for audit logs and reports."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def truthy(val: str | None, *, default: bool = False) -> bool:
    """Parse a string as a boolean flag (positive-list: 1/true/yes/on)."""
    if val is None:
        return default
    cleaned = str(val).strip().lower()
    if not cleaned:
        return default
    return cleaned in {"1", "true", "yes", "on"}


def state_tz(state: str) -> str:
    """Look up IANA timezone for a US state abbreviation."""
    return STATE_TZ.get((state or "").strip().upper(), "America/New_York")


def normalize_us_phone(raw: str) -> str:
    """Normalize a US phone number to E.164 (+1XXXXXXXXXX). Returns '' on failure."""
    digits = US_PHONE_RE.sub("", raw or "")
    if digits.startswith("1") and len(digits) == 11:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return ""


def is_business_hours(state: str, start_hour: int = 9, end_hour: int = 17) -> bool:
    """Check if it's currently business hours in a given US state."""
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
    return start_hour <= now_local.hour < end_hour
