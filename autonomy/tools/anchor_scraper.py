"""Anchor Browser integration for enhanced lead enrichment.

Uses Anchor Browser's cloud Chromium instances to scrape JS-rendered dental
practice websites that block basic urllib requests.  Falls back gracefully
when ANCHOR_API_KEY is not set.

Usage standalone:
    python3 -m autonomy.tools.anchor_scraper --url https://example-dental.com

Usage as library:
    from autonomy.tools.anchor_scraper import enrich_lead
    lead = enrich_lead({"website": "https://...", "name": "", "email": ""})
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
from urllib.parse import urljoin
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

ANCHOR_API_BASE = "https://api.anchorbrowser.io/v1"
SESSION_IDLE_TIMEOUT = 2  # minutes
SESSION_MAX_DURATION = 5  # minutes

# Patterns for extracting contact names from dental practice pages.
_NAME_PATTERNS = [
    # "Dr. John Smith" or "Dr. Jane Smith, DDS"
    re.compile(r"\bDr\.?\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)", re.UNICODE),
    # "Meet Dr. Smith" style headers
    re.compile(r"[Mm]eet\s+(?:Dr\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)"),
    # "Owner: Name" or "Office Manager: Name"
    re.compile(
        r"(?:owner|manager|director|principal)\s*[:\-–]\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
        re.IGNORECASE,
    ),
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

CONTACT_PATHS = ("contact", "contact-us", "about", "about-us", "team", "our-team", "staff", "doctors")

# SSL context that works with most sites.
_SSL_CTX = ssl.create_default_context()


def _get_api_key() -> str:
    return os.getenv("ANCHOR_API_KEY", "")


def _api_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make a request to the Anchor Browser REST API."""
    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("ANCHOR_API_KEY not set")

    url = f"{ANCHOR_API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {
        "anchor-api-key": api_key,
        "Content-Type": "application/json",
    }
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def create_session() -> dict:
    """Create a headless Anchor Browser session. Returns session dict with id and cdp_url."""
    body = {
        "browser": {
            "headless": {"active": True},
            "viewport": {"width": 1440, "height": 900},
            "adblock": {"active": True},
            "popup_blocker": {"active": True},
        },
        "session": {
            "idle_timeout": SESSION_IDLE_TIMEOUT,
            "max_duration": SESSION_MAX_DURATION,
        },
    }
    resp = _api_request("POST", "/sessions", body)
    # API wraps response under "data" key.
    return resp.get("data", resp)


def terminate_session(session_id: str) -> None:
    """Terminate an Anchor Browser session."""
    try:
        _api_request("DELETE", f"/sessions/{session_id}")
    except Exception as exc:
        log.debug("Failed to terminate session %s: %s", session_id, exc)


def fetch_with_browser(url: str, session_cdp_url: str) -> str:
    """Navigate to a URL using Playwright over CDP and return rendered HTML."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(session_cdp_url)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            # Wait for JS rendering.
            page.wait_for_timeout(2000)
            html = page.content()
            page.close()
            return html
        finally:
            browser.close()


def extract_emails_from_html(html: str) -> set[str]:
    """Extract email addresses from HTML content."""
    emails: set[str] = set()
    for m in EMAIL_RE.finditer(html):
        email = m.group(0).strip().lower()
        # Skip common false positives.
        if any(x in email for x in ("@sentry", "@wix", "example.com", "domain.com")):
            continue
        emails.add(email)
    # Mailto links.
    for m in re.finditer(r"mailto:([^?\"'>]+)", html, re.IGNORECASE):
        val = m.group(1).strip().lower()
        if EMAIL_RE.fullmatch(val):
            emails.add(val)
    return emails


def extract_contact_name(html: str) -> str:
    """Extract the most likely owner/dentist name from page HTML."""
    for pattern in _NAME_PATTERNS:
        match = pattern.search(html)
        if match:
            name = match.group(1).strip()
            # Sanity check: skip if it looks like a generic word.
            if len(name) > 4 and " " in name:
                return name
    return ""


def scrape_website(base_url: str, session_cdp_url: str) -> dict:
    """Scrape a website for emails and contact names using Anchor Browser.

    Returns {"emails": set[str], "name": str, "pages_scraped": int}.
    """
    emails: set[str] = set()
    name = ""
    pages_scraped = 0

    # Scrape homepage.
    try:
        html = fetch_with_browser(base_url, session_cdp_url)
        pages_scraped += 1
        emails |= extract_emails_from_html(html)
        name = extract_contact_name(html)
    except Exception as exc:
        log.warning("Failed to scrape %s: %s", base_url, exc)
        return {"emails": emails, "name": name, "pages_scraped": pages_scraped}

    # Scrape contact/about pages if we still need emails or name.
    if len(emails) < 2 or not name:
        for path in CONTACT_PATHS:
            if len(emails) >= 5:
                break
            page_url = urljoin(base_url.rstrip("/") + "/", path)
            try:
                html = fetch_with_browser(page_url, session_cdp_url)
                pages_scraped += 1
                emails |= extract_emails_from_html(html)
                if not name:
                    name = extract_contact_name(html)
            except Exception:
                continue
            # Don't hammer the site.
            time.sleep(0.5)

    return {"emails": emails, "name": name, "pages_scraped": pages_scraped}


def is_available() -> bool:
    """Check if Anchor Browser integration is configured."""
    return bool(_get_api_key())


def enrich_lead(lead: dict) -> dict:
    """Enrich a lead dict with browser-scraped email and contact name.

    Modifies the lead in-place and returns it.  Falls back gracefully if
    Anchor Browser is not configured or scraping fails.
    """
    if not is_available():
        return lead

    website = (lead.get("website") or "").strip()
    if not website:
        return lead

    if not website.startswith("http"):
        website = "https://" + website

    session = None
    try:
        session = create_session()
        session_id = session["id"]
        cdp_url = session["cdp_url"]
        log.info("Anchor session %s created for %s", session_id, website)

        result = scrape_website(website, cdp_url)

        # Fill in missing email.
        current_email = (lead.get("email") or "").strip()
        if not current_email or "info@" in current_email:
            scraped_emails = result["emails"]
            if scraped_emails:
                # Prefer non-generic emails.
                best = None
                for e in scraped_emails:
                    local = e.split("@")[0]
                    if local not in ("info", "contact", "hello", "office", "support", "admin"):
                        best = e
                        break
                if not best:
                    best = next(iter(scraped_emails))
                lead["email"] = best
                # Update notes to reflect scrape source.
                notes = lead.get("notes", "")
                notes = re.sub(r"email=\w+", "email=anchor_scrape", notes)
                lead["notes"] = notes

        # Fill in missing name.
        current_name = (lead.get("name") or "").strip()
        if not current_name and result["name"]:
            lead["name"] = result["name"]

        log.info(
            "Enriched: emails=%d, name=%s, pages=%d",
            len(result["emails"]),
            result["name"] or "(none)",
            result["pages_scraped"],
        )

    except Exception as exc:
        log.warning("Anchor Browser enrichment failed for %s: %s", website, exc)
    finally:
        if session:
            terminate_session(session["id"])

    return lead


def enrich_leads_batch(leads: list[dict], max_per_session: int = 5) -> list[dict]:
    """Enrich a batch of leads, reusing sessions where possible.

    Creates one Anchor Browser session per batch of max_per_session leads
    to minimize session creation overhead.
    """
    if not is_available():
        log.info("ANCHOR_API_KEY not set — skipping browser enrichment")
        return leads

    for i in range(0, len(leads), max_per_session):
        batch = leads[i : i + max_per_session]
        session = None
        try:
            session = create_session()
            cdp_url = session["cdp_url"]
            log.info("Anchor session %s for batch %d-%d", session["id"], i, i + len(batch))

            for lead in batch:
                website = (lead.get("website") or "").strip()
                if not website:
                    continue
                if not website.startswith("http"):
                    website = "https://" + website

                try:
                    result = scrape_website(website, cdp_url)

                    # Fill email.
                    current_email = (lead.get("email") or "").strip()
                    if not current_email or "info@" in current_email:
                        scraped_emails = result["emails"]
                        if scraped_emails:
                            best = None
                            for e in scraped_emails:
                                local = e.split("@")[0]
                                if local not in (
                                    "info", "contact", "hello", "office",
                                    "support", "admin",
                                ):
                                    best = e
                                    break
                            lead["email"] = best or next(iter(scraped_emails))
                            notes = lead.get("notes", "")
                            notes = re.sub(r"email=\w+", "email=anchor_scrape", notes)
                            lead["notes"] = notes

                    # Fill name.
                    if not (lead.get("name") or "").strip() and result["name"]:
                        lead["name"] = result["name"]

                except Exception as exc:
                    log.warning("Failed to enrich %s: %s", website, exc)

                time.sleep(1)  # Polite delay between sites.

        except Exception as exc:
            log.warning("Session creation failed for batch %d: %s", i, exc)
        finally:
            if session:
                terminate_session(session["id"])

    return leads


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape a website using Anchor Browser.")
    parser.add_argument("--url", required=True, help="Website URL to scrape.")
    parser.add_argument("--enrich-csv", help="Path to leads CSV to enrich in-place.")
    args = parser.parse_args()

    if not is_available():
        print("ANCHOR_API_KEY not set. Get one at https://signin.anchorbrowser.io")
        sys.exit(1)

    if args.enrich_csv:
        import csv
        from pathlib import Path

        csv_path = Path(args.enrich_csv)
        if not csv_path.exists():
            print(f"CSV not found: {csv_path}")
            sys.exit(1)

        leads: list[dict] = []
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            leads = list(reader)

        print(f"Enriching {len(leads)} leads from {csv_path}...")
        enrich_leads_batch(leads)

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(leads)

        enriched = sum(1 for row in leads if (row.get("name") or "").strip())
        print(f"Done. {enriched}/{len(leads)} leads now have contact names.")
    else:
        session = create_session()
        try:
            result = scrape_website(args.url, session["cdp_url"])
            print(f"Emails found: {result['emails']}")
            print(f"Contact name: {result['name'] or '(none)'}")
            print(f"Pages scraped: {result['pages_scraped']}")
        finally:
            terminate_session(session["id"])
