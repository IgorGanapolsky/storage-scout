#!/usr/bin/env python3
"""
Demand Detector v2 - Only actionable leads, zero noise.

Monitors Craigslist "wanted" section for people actively looking to rent tools.
Skips Google Search entirely (too much competitor noise).

Usage:
    python demand_detector.py              # One-time scan
    python demand_detector.py --watch      # Continuous monitoring (every 15 min)
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path

try:
    from apify_client import ApifyClient
except ImportError:
    print("Install: pip install apify-client")
    sys.exit(1)

# Config
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "storage-scout")
STORAGE_ROOT = Path(__file__).parent.parent
DATA_DIR = STORAGE_ROOT / "data" / "leads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_leads.json"

# Strict rental intent phrases (must appear as-is, not substrings)
RENTAL_INTENT = [
    "want to rent",
    "looking to rent",
    "need to rent",
    "anyone renting",
    "can i rent",
    "can i borrow",
    "need to borrow",
    "looking to borrow",
    "who has a",
    "anyone have a",
    "need for a day",
    "need for the weekend",
    "need for a week",
    "short term rental",
]

# Tools we offer (exact matches)
OUR_TOOLS = [
    "pressure washer", "power washer",
    "circular saw", "miter saw", "table saw", "tile saw",
    "drill", "hammer drill", "impact driver",
    "sander", "orbital sander",
    "generator",
    "air compressor", "nail gun", "nailer",
    "carpet cleaner",
    "concrete saw", "demolition hammer",
]

# Domains that indicate COMPETITOR (never alert)
COMPETITOR_DOMAINS = [
    "homedepot.com", "lowes.com", "unitedrentals.com", "sunbeltrentals.com",
    "generalrental.com", "acmetools.com", "northerntool.com", "grainger.com",
    "toolrental.com", "rentallcenter.com", "coastalhire.com",
]

# Contact patterns that indicate a REAL person looking for help
CONTACT_PATTERNS = [
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # Phone number
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
    r"\b(call|text|dm|message|contact)\s*(me|us)\b",
    r"\b(reach out|get in touch|hit me up)\b",
]

if not APIFY_TOKEN:
    print("Error: APIFY_TOKEN not set in environment")
    sys.exit(1)

client = ApifyClient(APIFY_TOKEN)


def load_seen() -> set:
    """Load previously seen lead IDs."""
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    """Save seen lead IDs."""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def send_alert(title: str, message: str, url: str = None, score: int = 0):
    """Send push notification via ntfy.sh."""
    priority = "urgent" if score >= 80 else "high" if score >= 50 else "default"

    headers = {
        "Title": title[:60].encode("ascii", "ignore").decode("ascii"),
        "Priority": priority,
        "Tags": "wrench,moneybag" if score >= 50 else "wrench",
    }
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Open Post, {url}"

    try:
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10
        )
        status = "sent" if resp.status_code == 200 else f"failed ({resp.status_code})"
        print(f"  Alert {status}: {title[:40]}...")
    except Exception as e:
        print(f"  Alert error: {e}")


def score_lead(text: str, url: str) -> int:
    """
    Score a lead from 0-100. Only alert if score >= 30.

    Scoring:
    - Has rental intent phrase: +30
    - Mentions our tool: +20
    - Has contact info: +30
    - From Craigslist wanted: +20
    - From Facebook group: +10
    - Competitor domain: -100
    """
    text_lower = text.lower()
    url_lower = url.lower() if url else ""
    score = 0

    # Competitor = instant disqualify
    for domain in COMPETITOR_DOMAINS:
        if domain in url_lower:
            return -100

    # Rental intent (+30)
    for phrase in RENTAL_INTENT:
        if phrase in text_lower:
            score += 30
            break

    # Tool match (+20)
    for tool in OUR_TOOLS:
        if tool in text_lower:
            score += 20
            break

    # Contact info (+30)
    for pattern in CONTACT_PATTERNS:
        if re.search(pattern, text_lower):
            score += 30
            break

    # Source bonus
    if "craigslist" in url_lower and "/wan/" in url_lower:
        score += 20  # Craigslist wanted section
    elif "craigslist" in url_lower:
        score += 10
    elif "facebook.com/groups" in url_lower:
        score += 10
    elif "nextdoor.com" in url_lower:
        score += 10

    return min(score, 100)


def scrape_craigslist_wanted() -> list:
    """Scrape Craigslist 'wanted' section only - highest quality leads."""
    print("Scanning Craigslist wanted section...")

    leads = []
    locations = ["miami", "fortlauderdale", "palm beach"]
    search_terms = ["pressure washer", "power tools", "saw", "drill", "generator"]

    for location in locations:
        for term in search_terms:
            try:
                run_input = {
                    "searchQuery": term,
                    "location": location,
                    "category": "wanted",
                    "maxItems": 5,
                    "proxyConfiguration": {"useApifyProxy": True},
                }

                run = client.actor("curious_coder/craigslist-scraper").call(
                    run_input=run_input,
                    timeout_secs=60
                )
                items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

                for item in items:
                    title = item.get("title", "")
                    body = item.get("description", "") or item.get("body", "")
                    url = item.get("url", "")
                    text = f"{title} {body}"

                    score = score_lead(text, url)

                    if score >= 30:
                        leads.append({
                            "source": "craigslist-wanted",
                            "id": item.get("id") or url[-20:],
                            "title": title,
                            "url": url,
                            "score": score,
                            "posted": item.get("datetime"),
                            "found_at": datetime.now().isoformat()
                        })

            except Exception as e:
                print(f"  Error ({location}/{term}): {e}")

    return leads


def run_scan() -> list:
    """Run demand scan and alert on qualified leads only."""
    print(f"\n{'='*50}")
    print(f"Demand Detector v2 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    seen = load_seen()
    new_leads = []

    # Only scan Craigslist wanted - highest quality source
    all_leads = scrape_craigslist_wanted()

    # Filter to new leads only
    for lead in all_leads:
        lead_id = lead.get("id", "")
        if lead_id and lead_id not in seen:
            new_leads.append(lead)
            seen.add(lead_id)

    save_seen(seen)

    if new_leads:
        print(f"\nFound {len(new_leads)} qualified leads:\n")

        # Save leads
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        leads_file = DATA_DIR / f"leads_{timestamp}.json"
        with open(leads_file, "w") as f:
            json.dump(new_leads, f, indent=2)

        # Alert on each (sorted by score, highest first)
        for lead in sorted(new_leads, key=lambda x: x["score"], reverse=True):
            score = lead["score"]
            title = f"Lead (score {score}): {lead['title'][:40]}"
            message = f"{lead['title']}\n\nSource: {lead['source']}\nScore: {score}/100"

            send_alert(title, message, lead.get("url"), score)

            print(f"  [{score:3d}] {lead['title'][:50]}")
            print(f"        {lead['url']}")
    else:
        print("\nNo new qualified leads.")

    print(f"\n{'='*50}")
    print(f"Total leads tracked: {len(seen)}")
    print(f"{'='*50}\n")

    return new_leads


def watch_mode(interval_minutes: int = 15):
    """Continuously monitor for new leads."""
    print(f"Watch mode: scanning every {interval_minutes} minutes")
    print("Press Ctrl+C to stop\n")

    while True:
        try:
            run_scan()
            print(f"Sleeping {interval_minutes} minutes...")
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\nWatch mode stopped")
            break


if __name__ == "__main__":
    if "--watch" in sys.argv:
        interval = 15
        for arg in sys.argv:
            if arg.startswith("--interval="):
                interval = int(arg.split("=")[1])
        watch_mode(interval)
    else:
        run_scan()
