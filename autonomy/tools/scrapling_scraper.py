"""Scrapling integration for enhanced lead enrichment.

Uses Scrapling's StealthyFetcher to scrape JS-rendered dental
practice websites that block basic urllib requests, bypassing Cloudflare.

Usage standalone:
    python3 -m autonomy.tools.scrapling_scraper --url https://example-dental.com

Usage as library:
    from autonomy.tools.scrapling_scraper import enrich_lead
    lead = enrich_lead({"website": "https://...", "name": "", "email": ""})
"""

from __future__ import annotations

import logging
import os
import re
import time
from urllib.parse import urljoin

import openai
from autonomy.utils import EMAIL_RE, EMAIL_SEARCH_RE
from dotenv import load_dotenv
from scrapling import StealthyFetcher

load_dotenv()

log = logging.getLogger(__name__)

CONTACT_PATHS = ("contact", "contact-us", "about", "about-us", "team", "our-team", "staff", "doctors")

def extract_emails_from_html(html: str) -> set[str]:
    """Extract email addresses from HTML content."""
    emails: set[str] = set()
    for m in EMAIL_SEARCH_RE.finditer(html):
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

_NAME_PATTERNS = [
    re.compile(r"\bDr\.?\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)", re.UNICODE),
    re.compile(r"[Mm]eet\s+(?:Dr\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)"),
    re.compile(
        r"(?:owner|manager|director|principal)\s*[:\-–]\s*([A-Z][a-z]+\s+[A-Z][a-z]+)",
        re.IGNORECASE,
    ),
]

def extract_contact_name_llm(html: str) -> str:
    """Extract the owner/dentist name from page HTML using OpenAI, with regex fallback."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        for pattern in _NAME_PATTERNS:
            match = pattern.search(html)
            if match:
                name = match.group(1).strip()
                if len(name) > 4 and " " in name:
                    return name
        return ""

    # Simple truncation to avoid huge token costs
    text_content = re.sub(r'<[^>]+>', ' ', html)
    text_content = ' '.join(text_content.split())[:10000]

    client = openai.OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Extract the full name of the primary doctor, owner, or principal dentist from the text of a dental/medical website. Respond ONLY with the person's name (e.g., 'Dr. John Smith', 'Jane Doe'), or 'None' if no such name is found."},
                {"role": "user", "content": f"Extract the name from this text:\n\n{text_content}"}
            ],
            temperature=0.0,
            max_tokens=20
        )
        name = response.choices[0].message.content.strip()
        if name and name.lower() != "none":
            return name
    except Exception as exc:
        log.debug("LLM extraction failed: %s", exc)
    return ""

def scrape_website(base_url: str) -> dict:
    """Scrape a website for emails and contact names using Scrapling.

    Returns {"emails": set[str], "name": str, "pages_scraped": int}.
    """
    emails: set[str] = set()
    name = ""
    pages_scraped = 0

    try:
        # Scrape homepage.
        fetcher = StealthyFetcher()
        page = fetcher.fetch(base_url)
        html = page.body.decode("utf-8", errors="ignore")
        pages_scraped += 1
        emails |= extract_emails_from_html(html)
        name = extract_contact_name_llm(html)

        # Scrape contact/about pages if we still need emails or name.
        if len(emails) < 2 or not name:
            for path in CONTACT_PATHS:
                if len(emails) >= 5:
                    break
                page_url = urljoin(base_url.rstrip("/") + "/", path)
                try:
                    page = fetcher.fetch(page_url)
                    page_html = page.body.decode("utf-8", errors="ignore")
                    pages_scraped += 1
                    emails |= extract_emails_from_html(page_html)
                    if not name:
                        name = extract_contact_name_llm(page_html)
                except Exception:
                    continue
                # Don't hammer the site.
                time.sleep(0.5)

    except Exception as exc:
        log.warning(
            "Failed to scrape website during enrichment (error_type=%s).",
            exc.__class__.__name__,
        )
        return {"emails": emails, "name": name, "pages_scraped": pages_scraped}

    return {"emails": emails, "name": name, "pages_scraped": pages_scraped}

def is_available() -> bool:
    """Check if Scrapling integration is configured."""
    return True  # Scrapling is locally installed, always available

def enrich_lead(lead: dict) -> dict:
    """Enrich a lead dict with browser-scraped email and contact name.

    Modifies the lead in-place and returns it.
    """
    website = (lead.get("website") or "").strip()
    if not website:
        return lead

    if not website.startswith("http"):
        website = "https://" + website

    try:
        log.info("Scrapling starting for lead enrichment.")
        result = scrape_website(website)

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
                notes = re.sub(r"email=\w+", "email=scrapling_scrape", notes)
                if "email=" not in notes:
                    notes += "; email=scrapling_scrape"
                lead["notes"] = notes

        # Fill in missing name.
        current_name = (lead.get("name") or "").strip()
        if not current_name and result["name"]:
            lead["name"] = result["name"]

        log.info(
            "Enriched lead: emails_found=%d, has_name=%s, pages=%d",
            len(result["emails"]),
            bool(result["name"]),
            result["pages_scraped"],
        )

    except Exception as exc:
        log.warning(
            "Scrapling enrichment failed (error_type=%s).",
            exc.__class__.__name__,
        )

    return lead

def enrich_leads_batch(leads: list[dict], max_per_session: int = 5) -> list[dict]:
    """Enrich a batch of leads using Scrapling."""
    for i, lead in enumerate(leads):
        enrich_lead(lead)
        if i < len(leads) - 1:
            time.sleep(1)  # Polite delay
    return leads

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape a website using Scrapling.")
    parser.add_argument("--url", help="Website URL to scrape.")
    parser.add_argument("--enrich-csv", help="Path to leads CSV to enrich in-place.")
    args = parser.parse_args()

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
        result = scrape_website(args.url)
        print(f"Emails found: {result['emails']}")
        print(f"Contact name: {result['name'] or '(none)'}")
        print(f"Pages scraped: {result['pages_scraped']}")
