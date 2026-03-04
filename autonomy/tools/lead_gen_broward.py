import argparse
import csv
import json
import logging
import os
import re
import subprocess
import time
from hashlib import sha1
from html import unescape
from pathlib import Path
from random import SystemRandom
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from autonomy.utils import EMAIL_RE, EMAIL_SEARCH_RE
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency in local/CI environments
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

load_dotenv()

DEFAULT_CATEGORIES = [
    "med spa",
    "plumber",
    "dentist",
    "hvac",
    "roofing",
    "electrician",
    "chiropractor",
    "urgent care",
    "pest control",
]

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_CITY_FILE = DATA_DIR / "broward_cities.json"
DEFAULT_MARKET_FILE = DATA_DIR / "us_growth_markets.json"
STATE_DIR = Path(__file__).resolve().parents[1] / "state"
CITY_INDEX_FILE = STATE_DIR / "lead_gen_market_index.json"
RNG = SystemRandom()

HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

MAX_HTML_BYTES = 512_000
WEB_TIMEOUT_SECS = 12

CONTACT_HINTS = (
    "contact",
    "contact-us",
    "about",
    "team",
    "staff",
    "support",
    "appointments",
    "booking",
    "schedule",
    "location",
    "locations",
)

EXCLUDED_EMAIL_DOMAINS = {
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
}

# Cache verified domains to avoid repeated DNS lookups within a single run.
_MX_CACHE: dict[str, bool] = {}


def verify_email_mx(email: str) -> bool:
    """Check if the email domain has MX records (basic deliverability gate).

    Returns True if the domain has MX records or if verification fails open.
    Returns False only when we can confirm the domain has NO mail server.
    """
    if not email or "@" not in email:
        return False
    domain = email.split("@", 1)[1].strip().lower()
    if not domain:
        return False
    if domain in EXCLUDED_EMAIL_DOMAINS:
        return False

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
        # Fail open — if we can't check, don't block the lead.
        logging.getLogger(__name__).debug("MX lookup failed for %s: %s", domain, exc)
        _MX_CACHE[domain] = True
        return True


def get_api_key() -> str:
    for key_name in ("GOOGLE_PLACES_API_KEY", "GOOGLE_CLOUD_API_KEY", "GOOGLE_API_KEY"):
        value = os.getenv(key_name)
        if value:
            return value
    raise SystemExit("Missing Google Places API key. Set GOOGLE_PLACES_API_KEY.")


def load_markets(path: Path | None, default_state: str) -> list[dict[str, str]]:
    state = (default_state or "FL").strip().upper()
    source_path = path
    if source_path is None and DEFAULT_MARKET_FILE.exists():
        source_path = DEFAULT_MARKET_FILE
    if source_path is None:
        source_path = DEFAULT_CITY_FILE
    if source_path and source_path.exists():
        markets: list[dict[str, str]] = []
        with source_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            if isinstance(item, str):
                city = item.strip()
                if city:
                    markets.append({"city": city, "state": state})
                continue
            if isinstance(item, dict):
                city = (item.get("city") or "").strip()
                item_state = (item.get("state") or state).strip().upper()
                if city:
                    markets.append({"city": city, "state": item_state or state})
        return markets
    raise SystemExit("No market list found.")


def _cursor_key(raw_key: str) -> str:
    norm = (raw_key or "default").strip().lower()
    if len(norm) <= 72:
        return norm
    return sha1(norm.encode("utf-8")).hexdigest()


def load_city_index(index_key: str) -> int:
    key = _cursor_key(index_key)
    if not CITY_INDEX_FILE.exists():
        return 0
    try:
        with CITY_INDEX_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        cursors = data.get("cursors")
        if isinstance(cursors, dict):
            return int(cursors.get(key, 0))
        # Backward compatibility with old format {"index": N}
        return int(data.get("index", 0))
    except Exception:
        return 0


def save_city_index(index: int, index_key: str) -> None:
    key = _cursor_key(index_key)
    payload: dict[str, dict[str, int]] = {"cursors": {}}
    if CITY_INDEX_FILE.exists():
        try:
            with CITY_INDEX_FILE.open("r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing.get("cursors"), dict):
                payload["cursors"].update(
                    {str(k): int(v) for k, v in existing["cursors"].items()}
                )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logging.getLogger(__name__).debug(
                "Ignoring invalid city index cache (%s).",
                exc.__class__.__name__,
            )
    payload["cursors"][key] = int(index)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with CITY_INDEX_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f)


def build_query(category: str, market: dict[str, str]) -> str:
    city = (market.get("city") or "").strip()
    state = (market.get("state") or "FL").strip().upper()
    return f"{category} in {city}, {state}"


def load_cities(path: Path | None) -> list[str]:
    if path and path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [city.strip() for city in data if city.strip()]
    if DEFAULT_CITY_FILE.exists():
        with DEFAULT_CITY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [city.strip() for city in data if city.strip()]
    raise SystemExit("No city list found.")


def load_existing(path: Path) -> tuple[set[str], set[str], set[str]]:
    emails: set[str] = set()
    domains: set[str] = set()
    phones: set[str] = set()
    if not path.exists():
        return emails, domains, phones
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = (row.get("email") or "").strip().lower()
            if email:
                emails.add(email)
            website = (row.get("website") or "").strip()
            domain = domain_from_url(website)
            if domain:
                domains.add(domain.lower())
            phone = (row.get("phone") or "").strip()
            if phone:
                phones.add(phone)
    return emails, domains, phones


def domain_from_url(url: str) -> str:
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        netloc = urlparse(url).netloc
    except Exception:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def guess_email(domain: str) -> str:
    """Fallback when no email is found on the website."""
    if not domain:
        return ""
    return f"info@{domain}"


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not url.startswith("http"):
        return "https://" + url
    return url


def fetch_html(url: str) -> str:
    url = normalize_url(url)
    if not url:
        return ""
    try:
        req = Request(url, headers={"User-Agent": "ai-seo-autopilot-leadgen/1.1"})
        with urlopen(req, timeout=WEB_TIMEOUT_SECS) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return ""
            raw = resp.read(MAX_HTML_BYTES)
            return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_emails(html_text: str) -> set[str]:
    html_text = unescape(html_text or "")
    out: set[str] = set()
    for m in EMAIL_SEARCH_RE.finditer(html_text):
        out.add(m.group(0).strip().lower())
    # Mailto links sometimes don't render as plain text.
    for m in re.finditer(r"mailto:([^?\"'>]+)", html_text, re.IGNORECASE):
        val = m.group(1).strip().lower()
        if EMAIL_RE.fullmatch(val):
            out.add(val)
    return out


def candidate_pages(base_url: str, html_text: str, domain: str) -> list[str]:
    base_url = normalize_url(base_url)
    if not base_url:
        return []

    candidates: list[str] = []
    # Common contact-like paths as a fast fallback.
    for hint in CONTACT_HINTS:
        candidates.append(urljoin(base_url, f"/{hint}"))

    html_text = html_text or ""
    for m in HREF_RE.finditer(html_text):
        href = (m.group(1) or "").strip()
        if not href:
            continue
        href_l = href.lower()
        if href_l.startswith("mailto:"):
            continue
        if any(h in href_l for h in CONTACT_HINTS):
            full = urljoin(base_url, href)
            candidates.append(full)

    # Keep only same-site URLs and de-dupe.
    seen: set[str] = set()
    out: list[str] = []
    for url in candidates:
        url = normalize_url(url)
        if not url:
            continue
        netloc = domain_from_url(url)
        if domain and netloc and domain.lower() != netloc.lower():
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def choose_best_email(candidates: set[str], website_domain: str) -> str:
    website_domain = (website_domain or "").lower()

    def score(email: str) -> int:
        email = (email or "").strip().lower()
        if not email or "@" not in email:
            return -10_000
        local, _, domain = email.partition("@")
        if not local or not domain:
            return -10_000
        if "%" in local or " " in local:
            return -10_000
        if domain in EXCLUDED_EMAIL_DOMAINS:
            return -10_000
        if local in {"noreply", "no-reply", "donotreply", "do-not-reply"}:
            return -500

        s = 0
        # Prefer same-domain emails
        if website_domain and domain == website_domain:
            s += 100
        # Deprioritize generic inboxes — these go unread
        generic = {"info", "contact", "hello", "office", "support", "appointments", "booking", "admin", "service"}
        if local in generic:
            s -= 30
        # Prefer personal-looking emails (contain a name)
        if local not in generic and not local.isdigit() and len(local) > 2:
            s += 50
        if domain.endswith(".gov") or domain.endswith(".edu"):
            s -= 10
        return s

    filtered = [e for e in candidates if e]
    if not filtered:
        return guess_email(website_domain)

    filtered.sort(key=score, reverse=True)
    best = filtered[0].strip().lower()
    if score(best) < -1000:
        return guess_email(website_domain)
    return best


def discover_best_email(website: str, domain: str) -> tuple[str, str]:
    website = normalize_url(website)
    domain = (domain or "").strip().lower()
    if not website or not domain:
        return guess_email(domain), "guess"

    html_home = fetch_html(website)
    emails: set[str] = set()
    emails |= extract_emails(html_home)

    # Crawl a few likely contact pages. Keep it bounded.
    for url in candidate_pages(website, html_home, domain)[:6]:
        if len(emails) >= 5:
            break
        html_page = fetch_html(url)
        if not html_page:
            continue
        emails |= extract_emails(html_page)

    best = choose_best_email(emails, domain)
    if best and best in emails:
        return best, "scrape"
    return best, "guess"


def request_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "ai-seo-autopilot-leadgen/1.0"})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def text_search(query: str, api_key: str) -> list[dict]:
    params = {"query": query, "key": api_key}
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)
    data = request_json(url)
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        message = data.get("error_message") or status
        raise SystemExit(f"Google Places text search error: {message}")
    return data.get("results", [])


def place_details(place_id: str, api_key: str) -> dict:
    fields = "name,formatted_phone_number,website,formatted_address,place_id,business_status"
    params = {"place_id": place_id, "fields": fields, "key": api_key}
    url = "https://maps.googleapis.com/maps/api/place/details/json?" + urlencode(params)
    data = request_json(url)
    status = data.get("status")
    if status != "OK":
        message = data.get("error_message") or status
        raise SystemExit(f"Google Places details error: {message}")
    return data.get("result", {})


def iter_city_cycle(cities: list[str], start_index: int):
    if not cities:
        raise SystemExit("No cities provided.")
    for i in range(len(cities)):
        yield cities[(start_index + i) % len(cities)]


def iter_city_category_pairs(cities: list[str], categories: list[str], start_index: int):
    for city in iter_city_cycle(cities, start_index):
        shuffled_categories = categories[:]
        RNG.shuffle(shuffled_categories)
        for category in shuffled_categories:
            yield city, category


def iter_market_cycle(markets: list[dict[str, str]], start_index: int):
    if not markets:
        raise SystemExit("No markets provided.")
    for i in range(len(markets)):
        yield markets[(start_index + i) % len(markets)]


def iter_market_category_pairs(markets: list[dict[str, str]], categories: list[str], start_index: int):
    for market in iter_market_cycle(markets, start_index):
        shuffled_categories = categories[:]
        RNG.shuffle(shuffled_categories)
        for category in shuffled_categories:
            yield market, category


def build_lead_from_place(
    place: dict,
    category: str,
    market: dict[str, str],
    api_key: str,
    existing_emails: set[str],
    existing_domains: set[str],
    existing_phones: set[str],
) -> dict | None:
    place_id = place.get("place_id")
    if not place_id:
        return None

    details = place_details(place_id, api_key)
    if not details:
        return None
    if details.get("business_status") == "CLOSED_PERMANENTLY":
        return None

    company = details.get("name") or place.get("name") or ""
    phone = details.get("formatted_phone_number") or ""
    website = details.get("website") or ""
    domain = domain_from_url(website)
    email, email_method = discover_best_email(website, domain)

    if not email:
        return None

    if "%" in email or " " in email or "@sentry" in email:
        return None

    # Verify the email domain has MX records before adding to pipeline.
    if not verify_email_mx(email):
        return None

    email_key = email.lower()
    if email_key in existing_emails:
        return None

    domain_key = domain.lower() if domain else ""
    if domain_key and domain_key in existing_domains:
        return None

    if phone and phone in existing_phones:
        return None

    lead = {
        "company": company,
        "name": "",
        "email": email,
        "phone": phone,
        "service": category.title(),
        "city": market.get("city", ""),
        "state": (market.get("state") or "FL").upper(),
        "website": website,
        "notes": f"source=google_places; category={category}; place_id={place_id}; email={email_method}",
    }

    existing_emails.add(email_key)
    if domain_key:
        existing_domains.add(domain_key)
    if phone:
        existing_phones.add(phone)

    return lead


def build_leads(
    markets: list[dict[str, str]],
    categories: list[str],
    limit: int,
    start_index: int,
    api_key: str,
    existing_emails: set[str],
    existing_domains: set[str],
    existing_phones: set[str],
) -> tuple[list[dict], int]:
    leads: list[dict] = []

    markets_used = 0
    last_market = None
    for market, category in iter_market_category_pairs(markets, categories, start_index):
        if len(leads) >= limit:
            break
        market_key = f"{market.get('city','')}|{market.get('state','')}"
        if market_key != last_market:
            markets_used += 1
            last_market = market_key

        query = build_query(category, market)
        results = text_search(query, api_key)
        for place in results:
            if len(leads) >= limit:
                break
            lead = build_lead_from_place(
                place=place,
                category=category,
                market=market,
                api_key=api_key,
                existing_emails=existing_emails,
                existing_domains=existing_domains,
                existing_phones=existing_phones,
            )
            if not lead:
                continue
            leads.append(lead)
            time.sleep(0.1)

    new_index = (start_index + markets_used) % len(markets) if markets else 0
    return leads, new_index


def write_leads(path: Path, leads: list[dict], replace: bool) -> None:
    fieldnames = [
        "company",
        "name",
        "email",
        "phone",
        "service",
        "city",
        "state",
        "website",
        "notes",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    mode = "w" if replace or not file_exists else "a"
    with path.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":
            writer.writeheader()
        for lead in leads:
            writer.writerow(lead)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local business leads via Google Places.")
    parser.add_argument("--limit", type=int, default=30, help="Number of leads to generate.")
    # Default to autonomy/state to avoid accidentally committing real lead data.
    parser.add_argument("--output", type=Path, default=STATE_DIR / "leads_ai_seo_real.csv")
    parser.add_argument("--replace", action="store_true", help="Replace output file instead of appending.")
    parser.add_argument(
        "--categories",
        type=str,
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated list of categories.",
    )
    parser.add_argument("--markets", type=Path, default=None, help="Path to market JSON file.")
    parser.add_argument("--cities", type=Path, default=None, help="Deprecated alias for --markets.")
    parser.add_argument("--state", type=str, default="FL", help="Fallback state for plain city lists.")
    parser.add_argument("--cursor-key", type=str, default="", help="Stable key for rotation cursor persistence.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = get_api_key()

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    if not categories:
        categories = DEFAULT_CATEGORIES

    market_file = args.markets or args.cities
    markets = load_markets(market_file, default_state=args.state)
    if not markets:
        raise SystemExit("Market list is empty.")

    cursor_source = str(market_file) if market_file else f"default:{args.state.upper()}"
    cursor_key = args.cursor_key.strip() if args.cursor_key.strip() else cursor_source
    start_index = load_city_index(cursor_key)

    existing_emails, existing_domains, existing_phones = load_existing(args.output)

    leads, new_index = build_leads(
        markets=markets,
        categories=categories,
        limit=args.limit,
        start_index=start_index,
        api_key=api_key,
        existing_emails=existing_emails,
        existing_domains=existing_domains,
        existing_phones=existing_phones,
    )

    if not leads:
        raise SystemExit("No new leads generated. Try different categories or rerun later.")

    # Enrich leads with Scrapling (fills missing names + upgrades guessed emails).
    try:
        from autonomy.tools.scrapling_scraper import enrich_leads_batch, is_available

        if is_available():
            needs_enrichment = [
                row for row in leads
                if not (row.get("name") or "").strip()
                or "email=guess" in (row.get("notes") or "")
            ]
            if needs_enrichment:
                print(f"Enriching {len(needs_enrichment)} leads via Scrapling...")
                enrich_leads_batch(needs_enrichment)
                enriched = sum(1 for row in needs_enrichment if (row.get("name") or "").strip())
                print(f"Scrapling: {enriched}/{len(needs_enrichment)} leads enriched with names")
    except ImportError:
        # Scrapling enrichment is optional; skip when dependency is unavailable.
        pass

    write_leads(args.output, leads, replace=args.replace)
    save_city_index(new_index, cursor_key)

    print(f"Generated {len(leads)} leads -> {args.output}")


if __name__ == "__main__":
    main()
