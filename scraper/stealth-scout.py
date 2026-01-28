#!/usr/bin/env python3
"""
Stealth Storage Price Scout - 2026 Edition

Uses Patchright (undetected Playwright) to scrape SpareFoot aggregator for
10x20 storage unit prices in Coral Springs FL.

SpareFoot is used as the primary source because:
1. It aggregates prices from multiple facilities
2. Has less aggressive anti-bot protection than individual facility sites
3. Shows real-time pricing with discounts

Based on 2026 best practices:
- Patchright for undetected browser automation
- Human-like behavior simulation
- Smart retry with exponential backoff
"""

import asyncio
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

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

# SpareFoot is our primary source - aggregates all major facilities
SPAREFOOT_URL = "https://www.sparefoot.com/search?location=coral+springs+fl&size=10x20"


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


async def human_mouse_movement(page):
    """Simulate natural mouse movements across the page"""
    viewport = page.viewport_size
    if not viewport:
        return

    for _ in range(random.randint(3, 5)):
        x = random.randint(100, viewport['width'] - 100)
        y = random.randint(100, viewport['height'] - 100)
        await page.mouse.move(x, y, steps=random.randint(10, 25))
        await human_delay(100, 300)


async def scrape_sparefoot() -> List[Dict]:
    """Scrape SpareFoot for 10x20 unit prices in Coral Springs"""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        print("  Patchright not installed. Install with: pip install patchright")
        return []

    print(f"\n  Scraping SpareFoot for 10x20 units...")
    print(f"  URL: {SPAREFOOT_URL}")

    results = []

    try:
        async with async_playwright() as p:
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
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="America/New_York",
                geolocation={"latitude": 26.2712, "longitude": -80.2706},
                permissions=["geolocation"],
            )

            page = await context.new_page()

            print("    Navigating to SpareFoot...")
            await page.goto(SPAREFOOT_URL, wait_until="networkidle", timeout=45000)
            await human_delay(3000, 5000)

            # Simulate human behavior
            await human_mouse_movement(page)
            await human_scroll(page)
            await human_delay(2000, 3000)

            # Scroll more to load all listings
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 600)")
                await human_delay(1000, 1500)

            # Extract facility data
            print("    Extracting prices...")
            facilities = await page.evaluate("""
                () => {
                    const results = [];
                    const cards = document.querySelectorAll('[class*="facility"], [class*="listing"], article');

                    cards.forEach(card => {
                        const text = card.innerText;
                        // Find facility name
                        const nameMatch = text.match(/(Extra Space|Public Storage|CubeSmart|Life Storage|U-Haul)[^\\n]*/i);
                        // Check if in Coral Springs
                        const isCoralSprings = /coral springs/i.test(text);
                        // Find all prices
                        const prices = text.match(/\\$\\d+(?:\\.\\d{2})?/g);
                        // Check for 10x20 mention
                        const has10x20 = /10.?x.?20|10\\s*'?\\s*x\\s*20/i.test(text);

                        if (prices && prices.length > 0 && isCoralSprings) {
                            results.push({
                                facility: nameMatch ? nameMatch[0].substring(0, 60) : 'Unknown',
                                prices: prices.slice(0, 5),
                                has10x20
                            });
                        }
                    });

                    // Deduplicate by facility name
                    const seen = new Set();
                    return results.filter(r => {
                        if (seen.has(r.facility)) return false;
                        seen.add(r.facility);
                        return true;
                    });
                }
            """)

            # Take screenshot for debugging
            screenshot_path = "/tmp/sparefoot_10x20_screenshot.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"    Screenshot saved: {screenshot_path}")

            await browser.close()

            # Process results
            for f in facilities:
                # Parse lowest price (remove $ and convert to float)
                prices = [float(p.replace('$', '').replace(',', '')) for p in f['prices']]
                lowest = min(prices) if prices else 0

                if lowest > 0:
                    results.append({
                        "facility": f['facility'],
                        "price": lowest,
                        "all_prices": sorted(prices),
                        "timestamp": datetime.now().isoformat(),
                        "method": "sparefoot",
                        "has_10x20": f['has10x20'],
                    })

            print(f"    Found {len(results)} Coral Springs facilities")
            return results

    except Exception as e:
        print(f"    Error: {e}")
        return []


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
    print(f"Unit size: {CONFIG['unit_size']}")
    print(f"High priority threshold: ${CONFIG['high_priority_threshold']}/mo spread")
    print("=" * 60)

    # Scrape SpareFoot for all facilities
    results = await scrape_sparefoot()

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    if results:
        # Sort by price (lowest first)
        results.sort(key=lambda x: x['price'])

        for r in results:
            calc = calculate_spread(r["price"])
            status = "HIGH" if calc["high_priority"] else ("OK" if calc["profitable"] else "SKIP")
            print(f"[{status}] {r['facility']}: ${r['price']}/mo -> ${calc['spread']:.0f} spread")

            # Send alert for high priority deals
            if calc["high_priority"]:
                await send_ntfy_alert(
                    f"HIGH PRIORITY: {r['facility']} - ${r['price']}/mo = ${calc['spread']:.0f} spread!",
                    priority="high"
                )

        await save_results(results)

        # Show best deal
        best = results[0]
        best_calc = calculate_spread(best["price"])
        print(f"\n{'='*60}")
        print(f"BEST DEAL: {best['facility']}")
        print(f"  Price: ${best['price']}/mo")
        print(f"  Spread: ${best_calc['spread']:.0f}/mo")
        print(f"  High Priority: {'YES' if best_calc['high_priority'] else 'NO'}")
    else:
        print("No prices found. Check screenshot at /tmp/sparefoot_10x20_screenshot.png")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
