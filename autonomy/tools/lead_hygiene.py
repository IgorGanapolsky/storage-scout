"""Lead hygiene — validate and clean email addresses before outreach.

Checks:
1. Syntax — well-formed email (not a filename, not a URL fragment)
2. Domain exclusion — known non-business domains (wix, sentry, example.com, etc.)
3. MX record — domain has a working mail server
4. SMTP RCPT TO probe — mailbox exists (without sending)

Usage standalone:
    python3 -m autonomy.tools.lead_hygiene --db autonomy/state/autonomy_live.sqlite3

Usage as library:
    from autonomy.tools.lead_hygiene import validate_email, clean_leads_db
"""

from __future__ import annotations

import logging
import smtplib
import socket
import sqlite3
import subprocess
import hashlib
from pathlib import Path

from autonomy.utils import EMAIL_RE

log = logging.getLogger(__name__)

# Domains known to be non-deliverable or irrelevant.
EXCLUDED_DOMAINS: set[str] = {
    "example.com",
    "email.com",
    "domain.com",
    "yourdomain.com",
    "sentry.io",
    "sentry.wixpress.com",
    "sentry-next.wixpress.com",
    "wixpress.com",
    "squarespace.com",
    "weebly.com",
    "godaddy.com",
    "test.com",
    "placeholder.com",
}

# File extensions that get scraped as "emails" but aren't.
_JUNK_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css", ".js")

# MX lookup cache (domain -> bool).
_MX_CACHE: dict[str, bool] = {}

# SMTP probe cache (email -> bool).
_SMTP_CACHE: dict[str, bool] = {}


def _is_junk_address(email: str) -> bool:
    """Detect scraped artifacts masquerading as emails (e.g. asset-1@3x.png)."""
    local, _, domain = email.partition("@")
    if not domain:
        return True
    # Check if "domain" looks like a filename extension.
    if any(domain.endswith(ext) or f".{domain}".endswith(ext) for ext in _JUNK_EXTENSIONS):
        return True
    # Local part that's just numbers/hashes (e.g. 632hdc@gmail.com is fine, but 3x is suspicious).
    if "." not in domain:
        return True
    return False


def _check_mx(domain: str) -> bool:
    """Check if domain has MX records via dig. Returns True if mail server exists."""
    if domain in _MX_CACHE:
        return _MX_CACHE[domain]
    try:
        result = subprocess.run(
            ["dig", "+short", "MX", domain],
            capture_output=True,
            text=True,
            timeout=5,
        )
        has_mx = bool(result.stdout.strip())
        _MX_CACHE[domain] = has_mx
        return has_mx
    except Exception as exc:
        log.debug("MX lookup failed for %s: %s", domain, exc)
        # Fail open — don't reject if we can't verify.
        _MX_CACHE[domain] = True
        return True


def _smtp_probe(email: str) -> bool:
    """Probe SMTP server with RCPT TO to check if mailbox exists.

    Returns True if the mailbox likely exists. Returns True on timeout
    or connection errors (fail open).
    """
    if email in _SMTP_CACHE:
        return _SMTP_CACHE[email]

    domain = email.split("@", 1)[1]

    # Get MX host.
    try:
        result = subprocess.run(
            ["dig", "+short", "MX", domain],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        if not lines:
            _SMTP_CACHE[email] = True  # No MX = fail open
            return True
        # MX records are "priority host." — take lowest priority.
        mx_host = lines[0].split()[-1].rstrip(".")
    except Exception:
        _SMTP_CACHE[email] = True
        return True

    try:
        smtp = smtplib.SMTP(timeout=8)
        smtp.connect(mx_host, 25)
        smtp.helo("callcatcherops.com")
        smtp.mail("verify@callcatcherops.com")
        code, _ = smtp.rcpt(email)
        smtp.quit()
        # 250 = OK, 251 = forwarding. Anything 4xx/5xx means reject.
        exists = code in (250, 251)
        _SMTP_CACHE[email] = exists
        return exists
    except (smtplib.SMTPException, socket.error, OSError) as exc:
        log.debug("SMTP probe failed for %s: %s", email, exc)
        # Fail open on connection issues.
        _SMTP_CACHE[email] = True
        return True


def _email_hash(email: str) -> str:
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()


def _email_domain(email: str) -> str:
    return (email or "").strip().lower().split("@", 1)[1] if "@" in (email or "") else ""


def validate_email(email: str, *, smtp: bool = False, check_mx: bool = True) -> tuple[bool, str]:
    """Validate a single email address.

    Args:
        email: Email to validate.
        smtp: If True, also probe SMTP RCPT TO (slow, ~8s/email).

    Returns (is_valid, reason).
    """
    email = (email or "").strip().lower()
    if not email:
        return False, "empty"

    if not EMAIL_RE.match(email):
        return False, "bad_syntax"

    if _is_junk_address(email):
        return False, "junk_artifact"

    domain = email.split("@", 1)[1]

    if domain in EXCLUDED_DOMAINS:
        return False, "excluded_domain"

    if check_mx and not _check_mx(domain):
        return False, "no_mx_records"

    if smtp and not _smtp_probe(email):
        return False, "smtp_rejected"

    return True, "ok"


def clean_leads_db(
    db_path: str,
    *,
    dry_run: bool = False,
    smtp: bool = False,
    check_mx: bool = True,
    sample_limit: int = 25,
) -> dict[str, object]:
    """Validate all lead emails in the SQLite DB.

    Marks invalid leads as 'bad_email' status so the deliverability gate
    excludes them from bounce rate calculations and outreach.

    Returns counts and sanitized invalid samples:
    {total, valid, invalid, already_bad, skipped, invalid_reasons, invalid_samples}.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT id, email, status FROM leads WHERE status NOT IN ('opted_out', 'bad_email')"
    ).fetchall()

    counts: dict[str, object] = {
        "total": len(rows),
        "valid": 0,
        "invalid": 0,
        "already_bad": 0,
        "skipped": 0,
        "invalid_reasons": {},
        "invalid_samples": [],
    }
    max_samples = max(0, int(sample_limit))

    for row in rows:
        lead_id = row["id"]
        email = (row["email"] or "").strip()

        if not email:
            counts["skipped"] += 1
            continue

        is_valid, reason = validate_email(email, smtp=smtp, check_mx=check_mx)

        if is_valid:
            counts["valid"] = int(counts["valid"]) + 1
        else:
            counts["invalid"] = int(counts["invalid"]) + 1
            reasons = dict(counts.get("invalid_reasons") or {})
            reasons[reason] = int(reasons.get(reason, 0)) + 1
            counts["invalid_reasons"] = reasons

            samples = list(counts.get("invalid_samples") or [])
            if len(samples) < max_samples:
                samples.append(
                    {
                        "lead_id_sha256": hashlib.sha256(str(lead_id).encode("utf-8")).hexdigest(),
                        "email_domain": _email_domain(email),
                        "email_sha256": _email_hash(email),
                        "reason": reason,
                        "prior_status": str(row["status"] or ""),
                    }
                )
                counts["invalid_samples"] = samples

            log.info("Invalid email: %s (reason: %s, lead: %s)", email, reason, lead_id)
            if not dry_run:
                cur.execute(
                    "UPDATE leads SET status='bad_email', updated_at=datetime('now') WHERE id=?",
                    (lead_id,),
                )

    if not dry_run:
        conn.commit()
    conn.close()

    return counts


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Validate and clean lead emails.")
    parser.add_argument(
        "--db",
        default="autonomy/state/autonomy_live.sqlite3",
        help="Path to leads SQLite database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report results without modifying the database.",
    )
    parser.add_argument(
        "--smtp",
        action="store_true",
        help="Also probe SMTP RCPT TO (slow, ~8s/email).",
    )
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"Database not found: {db}")
        raise SystemExit(1)

    print(f"Scanning {db}...")
    result = clean_leads_db(str(db), dry_run=args.dry_run, smtp=args.smtp)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n[{mode}] Results:")
    print(f"  Total leads scanned: {result['total']}")
    print(f"  Valid emails:        {result['valid']}")
    print(f"  Invalid emails:      {result['invalid']}")
    print(f"  Skipped (no email):  {result['skipped']}")

    if result["total"]:
        pct = result["valid"] / result["total"] * 100
        print(f"  Clean rate:          {pct:.1f}%")
