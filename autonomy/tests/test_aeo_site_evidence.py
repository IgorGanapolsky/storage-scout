from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
AEO = DOCS / "ai-seo"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_jsonld(html: str) -> list[dict]:
    blocks = re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, flags=re.S)
    parsed: list[dict] = []
    for raw in blocks:
        parsed.append(json.loads(raw))
    return parsed


def test_index_includes_service_and_faq_schema() -> None:
    html = _read(AEO / "index.html")
    jsonld = _extract_jsonld(html)
    schema_types = {block.get("@type") for block in jsonld}

    assert "ProfessionalService" in schema_types
    assert "FAQPage" in schema_types

    faq_block = next(block for block in jsonld if block.get("@type") == "FAQPage")
    assert isinstance(faq_block.get("mainEntity"), list)
    assert len(faq_block["mainEntity"]) >= 5


def test_intake_includes_consent_and_sms_disclosure() -> None:
    html = _read(AEO / "intake.html")

    assert 'name="consent_contact"' in html
    assert 'name="consent_publish"' in html
    assert "Reply STOP to opt out of SMS updates; reply HELP for help." in html


def test_funnel_pages_have_analytics_and_cta_tracking() -> None:
    expected_event_categories = {
        "index.html": "landing_aeo",
        "intake.html": "intake_aeo",
        "thanks.html": "thanks_aeo",
        "workflow-subscription.html": "workflow_subscription_aeo",
        "service.html": "service_aeo",
    }

    for file_name, event_category in expected_event_categories.items():
        html = _read(AEO / file_name)
        assert "G-W8E0EKB7W4" in html
        assert "cta_click" in html
        assert event_category in html

    thanks_html = _read(AEO / "thanks.html")
    assert "intake_submit" in thanks_html
    assert "aeo_intake" in thanks_html


def test_machine_readable_assets_cover_aeo_core_pages() -> None:
    llms = _read(DOCS / "llms.txt")
    sitemap = _read(DOCS / "sitemap.xml")
    robots = _read(DOCS / "robots.txt")

    required_urls = [
        "https://aiseoautopilot.com/ai-seo/",
        "https://aiseoautopilot.com/ai-seo/intake.html",
        "https://aiseoautopilot.com/ai-seo/workflow-subscription.html",
        "https://aiseoautopilot.com/ai-seo/service.html",
        "https://aiseoautopilot.com/ai-seo/aeo-faq.html",
    ]

    for url in required_urls:
        assert url in llms
        assert url in sitemap

    assert "Sitemap: https://aiseoautopilot.com/sitemap.xml" in robots


def test_offer_pages_explicitly_reject_guarantee_language() -> None:
    index_html = _read(AEO / "index.html")
    plan_html = _read(AEO / "workflow-subscription.html")
    service_html = _read(AEO / "service.html")

    assert "No. We do not guarantee" in index_html
    assert "No ranking or revenue guarantees" in plan_html
    assert "No ranking or revenue guarantees" in service_html


def test_service_page_has_structured_offer_catalog_and_sla_terms() -> None:
    html = _read(AEO / "service.html")
    jsonld = _extract_jsonld(html)
    schema_types = {block.get("@type") for block in jsonld}

    assert "Service" in schema_types
    service_block = next(block for block in jsonld if block.get("@type") == "Service")
    offers = service_block.get("offers", {})

    assert offers.get("@type") == "OfferCatalog"
    assert "itemListElement" in offers
    assert "Kickoff timeline: 5 to 7 business days post-intake" in html
