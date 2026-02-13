import argparse
import csv
import json
import os
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

DEFAULT_CATEGORIES = [
    "med spa",
    "dentist",
    "chiropractor",
    "urgent care",
    "plumber",
    "electrician",
    "hvac",
    "roofing",
    "pest control",
    "locksmith",
]

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_CITY_FILE = DATA_DIR / "broward_cities.json"
STATE_DIR = Path(__file__).resolve().parents[1] / "state"
CITY_INDEX_FILE = STATE_DIR / "broward_city_index.json"


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
    if not domain:
        return ""
    return f"info@{domain}"


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
    city_cycle = [cities[(start_index + i) % len(cities)] for i in range(len(cities))]

    cities_used = 0
    for city in city_cycle:
        if len(leads) >= limit:
            break
        cities_used += 1
        shuffled_categories = categories[:]
        random.shuffle(shuffled_categories)
        for category in shuffled_categories:
            if len(leads) >= limit:
                break
            query = f"{category} in {city}, FL"
            results = text_search(query, api_key)
            for place in results:
                if len(leads) >= limit:
                    break
                place_id = place.get("place_id")
                if not place_id:
                    continue
                details = place_details(place_id, api_key)
                if not details:
                    continue
                if details.get("business_status") == "CLOSED_PERMANENTLY":
                    continue
                company = details.get("name") or place.get("name") or ""
                phone = details.get("formatted_phone_number") or ""
                website = details.get("website") or ""
                domain = domain_from_url(website)
                email = guess_email(domain)

                if not email:
                    continue
                if email.lower() in existing_emails:
                    continue
                if domain and domain.lower() in existing_domains:
                    continue
                if phone and phone in existing_phones:
                    continue

                leads.append(
                    {
                        "company": company,
                        "name": "",
                        "email": email,
                        "phone": phone,
                        "service": category.title(),
                        "city": city,
                        "state": "FL",
                        "website": website,
                        "notes": f"source=google_places; category={category}; place_id={place_id}",
                    }
                )
                existing_emails.add(email.lower())
                if domain:
                    existing_domains.add(domain.lower())
                if phone:
                    existing_phones.add(phone)

                time.sleep(0.1)

    new_index = (start_index + cities_used) % len(cities)
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
    parser.add_argument("--output", type=Path, default=DATA_DIR / "leads_callcatcherops.csv")
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
