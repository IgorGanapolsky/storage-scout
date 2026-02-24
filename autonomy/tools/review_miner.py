#!/usr/bin/env python3
"""Mine Google reviews for reachability complaints — warm lead generation.

Scans existing leads' businesses for reviews mentioning missed calls,
voicemail, unreachability. These businesses are warm prospects because
they have PUBLIC EVIDENCE of a problem CallCatcher Ops solves.

Usage:
    python3 -m autonomy.tools.review_miner --limit 30
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autonomy.tools.fastmail_inbox_sync import load_dotenv

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
log = logging.getLogger(__name__)

# Keywords that indicate reachability problems
REACHABILITY_KEYWORDS = [
    "never called back",
    "didn't call back",
    "didn't return my call",
    "couldn't reach",
    "couldn't get through",
    "can't reach",
    "can't get through",
    "no one answered",
    "nobody answered",
    "went to voicemail",
    "goes to voicemail",
    "impossible to reach",
    "impossible to get",
    "never answer",
    "don't answer",
    "doesn't answer",
    "never picks up",
    "never responded",
    "didn't respond",
    "no response",
    "hard to reach",
    "hard to contact",
    "left a message",
    "left message",
    "called multiple times",
    "called several times",
    "tried calling",
    "tried to call",
    "waiting for callback",
    "still waiting",
    "no callback",
    "unreachable",
    "unanswered",
]

REACHABILITY_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in REACHABILITY_KEYWORDS),
    re.IGNORECASE,
)


def _google_find_place(name: str, city: str, state: str, api_key: str) -> str | None:
    """Find a Google Place ID by business name and location."""
    query = f"{name} {city} {state}"
    params = urllib.parse.urlencode({
        "input": query,
        "inputtype": "textquery",
        "fields": "place_id,name",
        "key": api_key,
    })
    url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        candidates = data.get("candidates", [])
        if candidates:
            return str(candidates[0].get("place_id", ""))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        log.debug("Google Place lookup failed; continuing without a place_id.")
        return None
    return None


def _google_place_reviews(place_id: str, api_key: str) -> list[dict]:
    """Fetch reviews for a Google Place."""
    params = urllib.parse.urlencode({
        "place_id": place_id,
        "fields": "name,rating,reviews,user_ratings_total",
        "key": api_key,
    })
    url = f"https://maps.googleapis.com/maps/api/place/details/json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data.get("result", {})
        return result.get("reviews", [])
    except (urllib.error.URLError, json.JSONDecodeError, KeyError):
        return []


def scan_lead_reviews(
    lead: dict,
    api_key: str,
) -> dict | None:
    """Check a lead's Google reviews for reachability complaints."""
    company = lead.get("company", "")
    city = lead.get("city", "")
    state = lead.get("state", "FL")

    if not company:
        return None

    place_id = _google_find_place(company, city, state, api_key)
    if not place_id:
        return None

    reviews = _google_place_reviews(place_id, api_key)
    if not reviews:
        return None

    complaints = []
    for review in reviews:
        text = review.get("text", "")
        rating = review.get("rating", 5)
        author = review.get("author_name", "")
        time_desc = review.get("relative_time_description", "")

        matches = REACHABILITY_PATTERN.findall(text)
        if matches:
            complaints.append({
                "author": author,
                "rating": rating,
                "time": time_desc,
                "text": text[:300],
                "keywords": list(set(m.lower() for m in matches)),
            })

    if not complaints:
        return None

    return {
        "lead_id": lead.get("id", ""),
        "company": company,
        "city": city,
        "phone": lead.get("phone", ""),
        "email": lead.get("email", ""),
        "service": lead.get("service", ""),
        "place_id": place_id,
        "complaint_count": len(complaints),
        "complaints": complaints,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Mine Google reviews for reachability complaints.")
    parser.add_argument("--limit", type=int, default=30, help="Max leads to scan.")
    parser.add_argument("--db", default="autonomy/state/autonomy_live.sqlite3", help="SQLite path.")
    parser.add_argument("--dotenv", default=".env", help=".env path.")
    parser.add_argument("--output", default="autonomy/state/warm_leads.json", help="Output path.")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between API calls (seconds).")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    env = load_dotenv((repo_root / args.dotenv).resolve())

    api_key = (
        env.get("GOOGLE_PLACES_API_KEY")
        or env.get("GOOGLE_CLOUD_API_KEY")
        or env.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_PLACES_API_KEY", "")
    ).strip()
    if not api_key:
        raise SystemExit("Missing GOOGLE_PLACES_API_KEY in .env")

    db_path = (repo_root / args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Prioritize: contacted leads first (already in pipeline), then new leads with phones
    leads = conn.execute("""
        SELECT id, company, phone, email, service, city, state
        FROM leads
        WHERE status IN ('new', 'contacted')
          AND TRIM(COALESCE(company, '')) <> ''
          AND TRIM(COALESCE(phone, '')) <> ''
        ORDER BY
            CASE WHEN status = 'contacted' THEN 0 ELSE 1 END,
            score DESC
        LIMIT ?
    """, (args.limit,)).fetchall()

    conn.close()

    warm_leads = []
    scanned = 0

    for lead in leads:
        lead_dict = dict(lead)
        result = scan_lead_reviews(lead_dict, api_key)
        scanned += 1

        if result:
            warm_leads.append(result)
            print(
                f"  WARM: {result['company']} ({result['service']}) "
                f"— {result['complaint_count']} reachability complaint(s)",
                file=sys.stderr,
            )

        if scanned % 10 == 0:
            print(f"  Scanned {scanned}/{len(leads)} leads, found {len(warm_leads)} warm...", file=sys.stderr)

        time.sleep(args.delay)

    output_path = (repo_root / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(warm_leads, indent=2), encoding="utf-8")

    print(f"\nResults: scanned={scanned}, warm_leads={len(warm_leads)}", file=sys.stderr)
    print(f"Output: {output_path}", file=sys.stderr)

    if warm_leads:
        print("\n=== Warm Leads (reachability complaints in Google reviews) ===")
        for w in warm_leads:
            print(f"\n{w['company']} ({w['service']}, {w['city']})")
            print(f"  Phone: {w['phone']} | Email: {w['email']}")
            for c in w["complaints"][:2]:
                print(f"  Review ({c['rating']}★, {c['time']}): \"{c['text'][:120]}...\"")
                print(f"  Keywords: {', '.join(c['keywords'])}")


if __name__ == "__main__":
    main()
