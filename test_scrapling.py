from scrapling import StealthyFetcher

def test():
    with StealthyFetcher() as fetcher:
        page = fetcher.get("https://example.com")
        print("Success:", "Example Domain" in page.text)

if __name__ == "__main__":
    test()
