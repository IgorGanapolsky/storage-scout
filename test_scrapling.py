import pytest

scrapling = pytest.importorskip("scrapling")
StealthyFetcher = scrapling.StealthyFetcher


def test_scrapling_fetch_example_domain() -> None:
    with StealthyFetcher() as fetcher:
        page = fetcher.get("https://example.com")
    assert "Example Domain" in page.text
