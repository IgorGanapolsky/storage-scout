from __future__ import annotations

from pathlib import Path

from autonomy.tools.funnel_watchdog import _derive_urls, _extract_ctas_from_html, run_funnel_watchdog


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


def test_funnel_watchdog_flags_missing_stripe_cta(monkeypatch, tmp_path: Path) -> None:
    intake_html = '<a href="https://calendly.com/igorganapolsky/audit-call">Book</a>'

    def fake_http_get(url: str, *, timeout: int = 14, max_bytes: int = 320_000) -> tuple[int, str]:
        if url == "https://callcatcherops.com/callcatcherops/":
            return 200, "<html>callcatcher landing</html>"
        if url == "https://callcatcherops.com/callcatcherops/intake.html":
            return 200, intake_html
        if url == "https://callcatcherops.com/callcatcherops/thanks.html":
            return 200, "<html>callcatcher thanks</html>"
        if url == "https://callcatcherops.com/unsubscribe.html":
            return 200, "<html>callcatcher unsubscribe</html>"
        if url == "https://calendly.com/igorganapolsky/audit-call":
            return 200, "<html>schedule</html>"
        return 404, ""

    monkeypatch.setattr("autonomy.tools.funnel_watchdog._http_get", fake_http_get)
    monkeypatch.setattr("autonomy.tools.funnel_watchdog._agent_browser_get_text", lambda **_kwargs: "")

    result = run_funnel_watchdog(
        repo_root=tmp_path,
        intake_url="https://callcatcherops.com/callcatcherops/intake.html",
        unsubscribe_url_template="https://callcatcherops.com/unsubscribe.html?email={{email}}",
    )

    issue_names = {issue.name for issue in result.issues}
    assert "cta_stripe" in issue_names
