from __future__ import annotations

import re
from typing import Iterable, List


# Default "role inboxes" that almost never convert in cold outreach.
# Keep this list short and obvious; override via config if needed.
DEFAULT_BLOCKED_LOCAL_PARTS = {
    "info",
    "contact",
    "hello",
    "office",
    "support",
    "sales",
    "service",
    "team",
    "admin",
    "appointments",
    "booking",
    "inquiries",
}

# Default email provenance allowed for sending.
# - direct: person-like email (usually first@ / first.last@) or explicitly tagged
# - scrape: discovered on-site (still filtered by blocked locals above)
DEFAULT_ALLOWED_EMAIL_METHODS = ["direct", "scrape"]

_HEX_LOCAL_RE = re.compile(r"[0-9a-f]{24,}", re.IGNORECASE)


def normalize_str_list(raw: object) -> list[str]:
    if raw is None:
        return []
    parts: Iterable[object]
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = raw
    else:
        parts = [raw]
    out: list[str] = []
    for p in parts:
        s = str(p or "").strip().lower()
        if s:
            out.append(s)
    return out


def email_local_part(email: str) -> str:
    return (email or "").strip().lower().split("@", 1)[0]


def is_sane_outreach_email(email: str) -> bool:
    """Heuristics to avoid obvious bad scraped addresses (tracking tokens, URL-encoded locals, etc)."""
    local = email_local_part(email)
    if not local:
        return False
    if "%20" in local or " " in local:
        return False
    if _HEX_LOCAL_RE.fullmatch(local):
        return False
    return True


def infer_email_method(*, email: str, raw_method: str, notes: str) -> str:
    """Return a stable email_method tag for a lead row.

    Priority:
    1) explicit email_method column
    2) `notes` tag `email=scrape|guess`
    3) infer direct for person-like locals (non-role) that look sane
    """
    raw = (raw_method or "").strip().lower()
    if raw:
        return raw

    notes_l = (notes or "").strip().lower()
    if "email=scrape" in notes_l:
        return "scrape"
    if "email=guess" in notes_l:
        return "guess"

    local = email_local_part(email)
    if local and local not in DEFAULT_BLOCKED_LOCAL_PARTS and is_sane_outreach_email(email):
        return "direct"

    return "unknown"


def service_matches(lead_service: str, targets: set[str]) -> bool:
    if not targets:
        return True
    raw = (lead_service or "").strip().lower()
    if not raw:
        return False
    return raw in targets

