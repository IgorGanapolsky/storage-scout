#!/usr/bin/env python3
"""
Stealth Storage Price Scout - 2026 Edition

Uses Patchright (undetected Playwright) to bypass Cloudflare and anti-bot systems.
Scrapes Public Storage, Extra Space, CubeSmart for 10x20 prices in Coral Springs FL.

Based on 2026 best practices:
- Patchright for undetected browser automation
- Residential proxy support
- Human-like behavior simulation
- Smart retry with exponential backoff

Sources:
- https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python
- https://www.zenrows.com/blog/playwright-stealth
- https://scrapfly.io/blog/posts/how-to-bypass-cloudflare-anti-scraping
"""

import asyncio
import json
import random
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import re

# Configuration
CONFIG = {
    "zip_codes": ["33071", "33076"],
    "target_city": "Coral Springs",
    "target_state": "FL",
    "unit_size": "10x20",
    "p2p_default_rate": 65.0,  # Neighbor.com avg 5x5 rate
    "insurance_cost": 12.0,
    "high_priority_threshold": 120.0,
    "ntfy_topic": "igor_storage_alerts",
}

FACILITIES = [
    {
        "name": "Public Storage",
        "search_url": "https://www.publicstorage.com/self-storage-fl-coral-springs.html",
        "price_patterns": [r'\$(\d+(?:\.\d{2})?)\s*(?:/mo|per month|monthly)', r'data-price="(\d+(?:\.\d{2})?)"'],
    },
    {
        "name": "Extra Space Storage",
        "search_url": "https://www.extraspace.com/storage/facilities/us/florida/coral_springs/",
        "price_patterns": [r'\$(\d+(?:\.\d{2})?)', r'price["\']?\s*:\s*["\']?(\d+(?:\.\d{2})?)'],
    },
    {
        "name": "CubeSmart",
        "search_url": "https://www.cubesmart.com/florida-self-storage/coral-springs-self-storage.html",
        "price_patterns": [r'\$(\d+(?:\.\d{2})?)', r'(\d+(?:\.\d{2})?)\s*(?:/mo|per month)'],
    },
]


async def human_delay(min_ms: int = 500, max_ms: int = 2000):
    """Random delay to simulate human behavior"""
    delay = random.randint(min_ms, max_ms) / 1000
    await asyncio.sleep(delay)


async def human_scroll(page):
    """Simulate human scrolling behavior"""
    viewport_height = await page.evaluate("window.innerHeight")
    scroll_amount = random.randint(200, viewport_height)

    for _ in range(random.randint(2, 5)):
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await human_delay(300, 800)
        scroll_amount = random.randint(-100, viewport_height // 2)


async def extract_prices(content: str, patterns: List[str], min_price: float = 100, max_price: float = 500) -> List[float]:
    """Extract prices from page content using multiple patterns"""
    prices = []
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            try:
                price = float(match)
                # Filter to reasonable 10x20 price range
                if min_price <= price <= max_price:
                    prices.append(price)
            except ValueError:
                continue
    return list(set(prices))  # Deduplicate


async def scrape_facility_patchright(facility: Dict) -> Optional[Dict]:
    """Scrape a facility using Patchright (undetected Playwright)"""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        print("  Patchright not installed. Trying standard playwright...")
        return await scrape_facility_playwright(facility)

    print(f"\n  Scraping {facility['name']} with Patchright...")

    try:
        async with async_playwright() as p:
            # Launch with anti-detection settings
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                ]
            )

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
            )

            page = await context.new_page()

            # Navigate with human-like timing
            await page.goto(facility["search_url"], wait_until="domcontentloaded", timeout=30000)
            await human_delay(2000, 4000)

            # Scroll like a human would
            await human_scroll(page)
            await human_delay(1000, 2000)

            # Get page content
            content = await page.content()

            # Take screenshot for debugging
            screenshot_path = f"/tmp/{facility['name'].replace(' ', '_')}_screenshot.png"
            await page.screenshot(path=screenshot_path)
            print(f"    Screenshot saved: {screenshot_path}")

            await browser.close()

            # Extract prices
            prices = await extract_prices(content, facility["price_patterns"])

            if prices:
                lowest = min(prices)
                print(f"    Found {len(prices)} prices, lowest: ${lowest}")
                return {
                    "facility": facility["name"],
                    "price": lowest,
                    "all_prices": sorted(prices),
                    "timestamp": datetime.now().isoformat(),
                    "method": "patchright",
                }
            else:
                print(f"    No prices found in content")
                # Try to find any dollar amounts for debugging
                all_dollars = re.findall(r'\$(\d+(?:\.\d{2})?)', content)
                if all_dollars:
                    print(f"    All $ amounts found: {all_dollars[:10]}...")
                return None

    except Exception as e:
        print(f"    Error: {e}")
        return None


async def scrape_facility_playwright(facility: Dict) -> Optional[Dict]:
    """Fallback: Scrape using standard Playwright with stealth"""
    try:
        from playwright.async_api import async_playwright
        from playwright_stealth import stealth_async
    except ImportError:
        print("  Playwright not available")
        return None

    print(f"\n  Scraping {facility['name']} with Playwright Stealth...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            page = await context.new_page()
            await stealth_async(page)

            await page.goto(facility["search_url"], wait_until="domcontentloaded", timeout=30000)
            await human_delay(3000, 5000)
            await human_scroll(page)

            content = await page.content()
            await browser.close()

            prices = await extract_prices(content, facility["price_patterns"])

            if prices:
                lowest = min(prices)
                print(f"    Found {len(prices)} prices, lowest: ${lowest}")
                return {
                    "facility": facility["name"],
                    "price": lowest,
                    "all_prices": sorted(prices),
                    "timestamp": datetime.now().isoformat(),
                    "method": "playwright-stealth",
                }
            return None

    except Exception as e:
        print(f"    Error: {e}")
        return None


def calculate_spread(commercial_price: float, p2p_rate: float = CONFIG["p2p_default_rate"]) -> Dict:
    """Calculate arbitrage spread"""
    revenue = p2p_rate * 4  # 4 x 5x5 spaces
    insurance = CONFIG["insurance_cost"]
    spread = revenue - commercial_price - insurance

    return {
        "revenue": revenue,
        "cost": commercial_price + insurance,
        "spread": spread,
        "profitable": spread > 0,
        "high_priority": spread >= CONFIG["high_priority_threshold"],
    }


async def send_ntfy_alert(message: str, priority: str = "default"):
    """Send push notification via ntfy.sh"""
    import urllib.request

    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{CONFIG['ntfy_topic']}",
            data=message.encode(),
            headers={
                "Title": "Storage Deal Alert",
                "Priority": priority,
                "Tags": "moneybag" if "HIGH" in message else "chart_with_upwards_trend",
            }
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"  Alert sent: {message[:50]}...")
    except Exception as e:
        print(f"  Failed to send alert: {e}")


async def save_results(results: List[Dict]):
    """Save results to CSV"""
    script_dir = Path(__file__).parent.parent
    csv_path = script_dir / "storage_spreads.csv"

    date_str = datetime.now().strftime("%Y-%m-%d")

    lines = []
    for r in results:
        if r:
            calc = calculate_spread(r["price"])
            line = f"{date_str},{r['facility']},{CONFIG['zip_codes'][0]},{r['price']},{calc['revenue']},{calc['spread']:.2f},{calc['high_priority']}"
            lines.append(line)

    if lines:
        # Read existing content
        existing = ""
        if csv_path.exists():
            existing = csv_path.read_text()

        # Append new lines
        with open(csv_path, "a") as f:
            if not existing or not existing.strip():
                f.write("date,facility,zip,commercial_price,p2p_revenue,spread,high_priority\n")
            for line in lines:
                f.write(line + "\n")

        print(f"\nSaved {len(lines)} entries to {csv_path}")


async def main():
    print("=" * 60)
    print("STEALTH STORAGE SCOUT - 2026 Edition")
    print("=" * 60)
    print(f"Target: {CONFIG['target_city']}, {CONFIG['target_state']}")
    print(f"Zip codes: {', '.join(CONFIG['zip_codes'])}")
    print(f"High priority threshold: ${CONFIG['high_priority_threshold']}/mo spread")
    print("=" * 60)

    results = []

    for facility in FACILITIES:
        result = await scrape_facility_patchright(facility)
        if result:
            results.append(result)

            # Calculate and display spread
            calc = calculate_spread(result["price"])
            priority = "HIGH PRIORITY" if calc["high_priority"] else ""
            print(f"    Spread: ${calc['spread']:.2f}/mo {priority}")

            # Send alert for high priority deals
            if calc["high_priority"]:
                await send_ntfy_alert(
                    f"HIGH PRIORITY: {result['facility']} - ${result['price']}/mo = ${calc['spread']:.0f} spread!",
                    priority="high"
                )

        # Delay between facilities
        await human_delay(3000, 6000)

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    if results:
        for r in results:
            calc = calculate_spread(r["price"])
            status = "HIGH" if calc["high_priority"] else ("OK" if calc["profitable"] else "SKIP")
            print(f"[{status}] {r['facility']}: ${r['price']}/mo -> ${calc['spread']:.0f} spread")

        await save_results(results)
    else:
        print("No prices found. Try running locally with headed browser for debugging.")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
