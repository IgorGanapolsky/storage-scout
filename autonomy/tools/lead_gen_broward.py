import argparse
import csv
import json
import os
import re
import time
from html import unescape
from pathlib import Path
from random import SystemRandom
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

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
STATE_DIR = Path(__file__).resolve().parents[1] / "state"
CITY_INDEX_FILE = STATE_DIR / "broward_city_index.json"
RNG = SystemRandom()

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
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


def get_api_key() -> str:
    for key_name in ("GOOGLE_PLACES_API_KEY", "GOOGLE_CLOUD_API_KEY", "GOOGLE_API_KEY"):
        value = os.getenv(key_name)
        if value:
            return value
    raise SystemExit("Missing Google Places API key. Set GOOGLE_PLACES_API_KEY.")


def load_cities(path: Optional[Path]) -> List[str]:
    if path and path.exists():
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [city.strip() for city in data if city.strip()]
    if DEFAULT_CITY_FILE.exists():
        with DEFAULT_CITY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return [city.strip() for city in data if city.strip()]
    raise SystemExit("No city list found.")


def load_existing(path: Path) -> Tuple[Set[str], Set[str], Set[str]]:
    emails: Set[str] = set()
    domains: Set[str] = set()
    phones: Set[str] = set()
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
        req = Request(url, headers={"User-Agent": "callcatcherops-leadgen/1.1"})
        with urlopen(req, timeout=WEB_TIMEOUT_SECS) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return ""
            raw = resp.read(MAX_HTML_BYTES)
            return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_emails(html_text: str) -> Set[str]:
    html_text = unescape(html_text or "")
    out: Set[str] = set()
    for m in EMAIL_RE.finditer(html_text):
        out.add(m.group(0).strip().lower())
    # Mailto links sometimes don't render as plain text.
    for m in re.finditer(r"mailto:([^?\"'>]+)", html_text, re.IGNORECASE):
        val = m.group(1).strip().lower()
        if EMAIL_RE.fullmatch(val):
            out.add(val)
    return out


def candidate_pages(base_url: str, html_text: str, domain: str) -> List[str]:
    base_url = normalize_url(base_url)
    if not base_url:
        return []

    candidates: List[str] = []
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
    seen: Set[str] = set()
    out: List[str] = []
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


def choose_best_email(candidates: Set[str], website_domain: str) -> str:
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


def discover_best_email(website: str, domain: str) -> Tuple[str, str]:
    website = normalize_url(website)
    domain = (domain or "").strip().lower()
    if not website or not domain:
        return guess_email(domain), "guess"

    html_home = fetch_html(website)
    emails: Set[str] = set()
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


def request_json(url: str) -> Dict:
    req = Request(url, headers={"User-Agent": "callcatcherops-leadgen/1.0"})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def text_search(query: str, api_key: str) -> List[Dict]:
    params = {"query": query, "key": api_key}
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)
    data = request_json(url)
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        message = data.get("error_message") or status
        raise SystemExit(f"Google Places text search error: {message}")
    return data.get("results", [])


def place_details(place_id: str, api_key: str) -> Dict:
    fields = "name,formatted_phone_number,website,formatted_address,place_id,business_status"
    params = {"place_id": place_id, "fields": fields, "key": api_key}
    url = "https://maps.googleapis.com/maps/api/place/details/json?" + urlencode(params)
    data = request_json(url)
    status = data.get("status")
    if status != "OK":
        message = data.get("error_message") or status
        raise SystemExit(f"Google Places details error: {message}")
    return data.get("result", {})


def load_city_index() -> int:
    if not CITY_INDEX_FILE.exists():
        return 0
    try:
        with CITY_INDEX_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("index", 0))
    except Exception:
        return 0


def save_city_index(index: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with CITY_INDEX_FILE.open("w", encoding="utf-8") as f:
        json.dump({"index": index}, f)


def iter_city_cycle(cities: List[str], start_index: int):
    if not cities:
        raise SystemExit("No cities provided.")
    for i in range(len(cities)):
        yield cities[(start_index + i) % len(cities)]


def iter_city_category_pairs(cities: List[str], categories: List[str], start_index: int):
    for city in iter_city_cycle(cities, start_index):
        shuffled_categories = categories[:]
        RNG.shuffle(shuffled_categories)
        for category in shuffled_categories:
            yield city, category


def build_lead_from_place(
    place: Dict,
    category: str,
    city: str,
    api_key: str,
    existing_emails: Set[str],
    existing_domains: Set[str],
    existing_phones: Set[str],
) -> Optional[Dict]:
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
        "city": city,
        "state": "FL",
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
    cities: List[str],
    categories: List[str],
    limit: int,
    api_key: str,
    existing_emails: Set[str],
    existing_domains: Set[str],
    existing_phones: Set[str],
) -> Tuple[List[Dict], int]:
    leads: List[Dict] = []
    start_index = load_city_index()

    cities_used = 0
    last_city = None
    for city, category in iter_city_category_pairs(cities, categories, start_index):
        if len(leads) >= limit:
            break
        if city != last_city:
            cities_used += 1
            last_city = city

        query = f"{category} in {city}, FL"
        results = text_search(query, api_key)
        for place in results:
            if len(leads) >= limit:
                break
            lead = build_lead_from_place(
                place=place,
                category=category,
                city=city,
                api_key=api_key,
                existing_emails=existing_emails,
                existing_domains=existing_domains,
                existing_phones=existing_phones,
            )
            if not lead:
                continue
            leads.append(lead)
            time.sleep(0.1)

    new_index = (start_index + cities_used) % len(cities) if cities else 0
    return leads, new_index


def write_leads(path: Path, leads: List[Dict], replace: bool) -> None:
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
    parser = argparse.ArgumentParser(description="Generate Broward County leads via Google Places.")
    parser.add_argument("--limit", type=int, default=30, help="Number of leads to generate.")
    # Default to autonomy/state to avoid accidentally committing real lead data.
    parser.add_argument("--output", type=Path, default=STATE_DIR / "leads_callcatcherops_real.csv")
    parser.add_argument("--replace", action="store_true", help="Replace output file instead of appending.")
    parser.add_argument(
        "--categories",
        type=str,
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated list of categories.",
    )
    parser.add_argument("--cities", type=Path, default=None, help="Path to cities JSON file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = get_api_key()

    categories = [c.strip() for c in args.categories.split(",") if c.strip()]
    if not categories:
        categories = DEFAULT_CATEGORIES

    cities = load_cities(args.cities)
    if not cities:
        raise SystemExit("City list is empty.")

    existing_emails, existing_domains, existing_phones = load_existing(args.output)

    leads, new_index = build_leads(
        cities=cities,
        categories=categories,
        limit=args.limit,
        api_key=api_key,
        existing_emails=existing_emails,
        existing_domains=existing_domains,
        existing_phones=existing_phones,
    )

    if not leads:
        raise SystemExit("No new leads generated. Try different categories or rerun later.")

    write_leads(args.output, leads, replace=args.replace)
    save_city_index(new_index)

    print(f"Generated {len(leads)} leads -> {args.output}")


if __name__ == "__main__":
    main()
