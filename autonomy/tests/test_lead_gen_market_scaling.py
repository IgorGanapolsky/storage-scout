from __future__ import annotations

import json
from pathlib import Path

from autonomy.tools import lead_gen_broward as leadgen


def test_load_markets_supports_string_and_object_entries(tmp_path: Path) -> None:
    market_file = tmp_path / "markets.json"
    market_file.write_text(
        json.dumps([
            "Miami",
            {"city": "Austin", "state": "tx"},
            {"city": "", "state": "CA"},
            {"city": "Seattle"},
        ]),
        encoding="utf-8",
    )

    markets = leadgen.load_markets(market_file, default_state="FL")

    assert markets == [
        {"city": "Miami", "state": "FL"},
        {"city": "Austin", "state": "TX"},
        {"city": "Seattle", "state": "FL"},
    ]


def test_build_query_uses_market_city_and_state() -> None:
    query = leadgen.build_query("dentist", {"city": "Denver", "state": "co"})
    assert query == "dentist in Denver, CO"


def test_market_cursor_is_isolated_by_key(tmp_path: Path, monkeypatch) -> None:
    index_file = tmp_path / "market_index.json"
    monkeypatch.setattr(leadgen, "CITY_INDEX_FILE", index_file)

    leadgen.save_city_index(5, "market:us")
    leadgen.save_city_index(2, "market:fl")

    assert leadgen.load_city_index("market:us") == 5
    assert leadgen.load_city_index("market:fl") == 2
    assert leadgen.load_city_index("market:tx") == 0


def test_save_city_index_tolerates_invalid_existing_cache(tmp_path: Path, monkeypatch) -> None:
    index_file = tmp_path / "market_index.json"
    index_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(leadgen, "CITY_INDEX_FILE", index_file)

    leadgen.save_city_index(3, "market:us")

    payload = json.loads(index_file.read_text(encoding="utf-8"))
    assert payload == {"cursors": {"market:us": 3}}


def test_build_leads_rotates_markets_and_persists_index(monkeypatch) -> None:
    # No external calls; patch search/details with deterministic fake data.
    markets = [
        {"city": "Miami", "state": "FL"},
        {"city": "Austin", "state": "TX"},
        {"city": "Denver", "state": "CO"},
    ]

    def fake_text_search(query: str, api_key: str) -> list[dict]:
        city = query.split(" in ", 1)[1].split(",", 1)[0]
        return [{"place_id": f"pid-{city}"}]

    def fake_place_details(place_id: str, api_key: str) -> dict:
        city = place_id.split("pid-", 1)[1]
        domain = city.lower()
        return {
            "name": f"{city} Dental",
            "formatted_phone_number": f"+1-555-{len(city):04d}",
            "website": f"https://{domain}.example.org",
            "business_status": "OPERATIONAL",
        }

    monkeypatch.setattr(leadgen, "text_search", fake_text_search)
    monkeypatch.setattr(leadgen, "place_details", fake_place_details)
    monkeypatch.setattr(leadgen, "discover_best_email", lambda website, domain: (f"owner@{domain}", "scrape"))
    monkeypatch.setattr(leadgen, "verify_email_mx", lambda email: True)

    leads, new_index = leadgen.build_leads(
        markets=markets,
        categories=["dentist"],
        limit=2,
        start_index=0,
        api_key="fake",
        existing_emails=set(),
        existing_domains=set(),
        existing_phones=set(),
    )

    assert len(leads) == 2
    assert leads[0]["city"] == "Miami"
    assert leads[0]["state"] == "FL"
    assert leads[1]["city"] == "Austin"
    assert leads[1]["state"] == "TX"
    assert new_index == 2
