from __future__ import annotations

from autonomy.tools.funnel_watchdog import _derive_urls, _extract_ctas_from_html


def test_funnel_watchdog_derive_urls_from_intake_and_unsubscribe_template() -> None:
    urls = _derive_urls(
        intake_url="https://callcatcherops.com/callcatcherops/intake.html",
        unsubscribe_url_template="https://callcatcherops.com/unsubscribe.html?email={{email}}",
    )
    assert urls["landing"] == "https://callcatcherops.com/callcatcherops/"
    assert urls["intake"] == "https://callcatcherops.com/callcatcherops/intake.html"
    assert urls["thanks"] == "https://callcatcherops.com/callcatcherops/thanks.html"
    assert urls["unsubscribe"] == "https://callcatcherops.com/unsubscribe.html"


def test_funnel_watchdog_extracts_calendly_and_stripe_links() -> None:
    html = """
    <a href="https://calendly.com/igorganapolsky/audit-call">Book</a>
    <a href="https://buy.stripe.com/4gMaEX0I4f5IdWh6i73sI01">Pay</a>
    """
    ctas = _extract_ctas_from_html(html)
    assert ctas["calendly"] == "https://calendly.com/igorganapolsky/audit-call"
    assert ctas["stripe"] == "https://buy.stripe.com/4gMaEX0I4f5IdWh6i73sI01"

