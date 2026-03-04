import pytest


scrapling = pytest.importorskip("scrapling")
StealthyFetcher = scrapling.StealthyFetcher


@pytest.mark.integration
def test_scrapling_fetches_example_domain() -> None:
    with StealthyFetcher() as fetcher:
        page = fetcher.get("https://example.com")
    assert "Example Domain" in (page.text or "")
