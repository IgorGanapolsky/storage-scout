#!/usr/bin/env python3
"""
Home Depot Clearance Scraper

Monitors Home Depot clearance section for power tool deals.
Sends alerts via ntfy.sh when good deals are found.

Run via GitHub Actions on schedule or manually.
"""

import asyncio
import ssl
import urllib.request
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import NTFY_TOPIC, MARKET_RATES, LOCATION

# Create SSL context for secure HTTPS requests
_SSL_CONTEXT = ssl.create_default_context()


# Minimum discount to alert on
MIN_DISCOUNT_PERCENT = 30

# Target categories and keywords
TARGET_KEYWORDS = [
    "pressure washer",
    "carpet cleaner",
    "tile saw",
    "generator",
    "drill",
    "circular saw",
    "reciprocating saw",
    "air compressor",
    "nail gun",
    "sander",
    "jigsaw",
    "grinder",
]

# Price thresholds - alert if clearance price is at or below
PRICE_THRESHOLDS = {
    "pressure_washer": 120,
    "carpet_cleaner": 100,
    "tile_saw": 180,
    "generator": 250,
    "drill": 80,
    "circular_saw": 60,
    "reciprocating_saw": 70,
    "air_compressor": 100,
}


def calculate_rental_roi(buy_price: float, category: str) -> Dict:
    """Calculate potential rental ROI for a clearance tool."""
    market = MARKET_RATES.get(category, {"daily": 25, "weekly": 90})
    daily_rate = market["daily"]

    # Assume 4 rentals per month, 12% platform fee
    monthly_gross = daily_rate * 4
    monthly_net = monthly_gross * 0.88
    payback_months = buy_price / monthly_net if monthly_net > 0 else 99

    return {
        "daily_rate": daily_rate,
        "monthly_net": round(monthly_net, 2),
        "payback_months": round(payback_months, 1),
        "annual_profit": round(monthly_net * 12 - buy_price, 2),
    }


def categorize_tool(name: str) -> Optional[str]:
    """Determine tool category from name."""
    name_lower = name.lower()

    if "pressure" in name_lower or "power wash" in name_lower:
        return "pressure_washer"
    elif "carpet" in name_lower or "upholstery" in name_lower:
        return "carpet_cleaner"
    elif "tile saw" in name_lower or "wet saw" in name_lower:
        return "tile_saw"
    elif "generator" in name_lower:
        return "generator"
    elif "drill" in name_lower:
        return "drill"
    elif "circular saw" in name_lower:
        return "circular_saw"
    elif "reciprocating" in name_lower or "sawzall" in name_lower:
        return "reciprocating_saw"
    elif "compressor" in name_lower:
        return "air_compressor"
    elif "nailer" in name_lower or "nail gun" in name_lower:
        return "nail_gun"
    elif "sander" in name_lower:
        return "sander"

    return None


async def send_alert(message: str, priority: str = "default", tags: str = "toolbox"):
    """Send push notification via ntfy.sh (HTTPS with verified SSL)."""
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode(),
            headers={
                "Title": "Tool Deal Alert",
                "Priority": priority,
                "Tags": tags,
            }
        )
        urllib.request.urlopen(req, timeout=10, context=_SSL_CONTEXT)
        print(f"  Alert sent: {message[:50]}...")
    except Exception as e:
        print(f"  Failed to send alert: {e}")


async def scrape_homedepot_clearance() -> List[Dict]:
    """
    Scrape Home Depot clearance section for power tool deals.

    Note: Home Depot has aggressive bot protection.
    This uses their public search API with respectful rate limiting.
    """
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        print("Patchright not installed. Install with: pip install patchright")
        return []

    print("\nScraping Home Depot clearance...")
    print(f"Location: {LOCATION['city']}, {LOCATION['state']}")

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]
            )

            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                locale="en-US",
            )

            page = await context.new_page()

            # Search clearance power tools
            search_url = f"https://www.homedepot.com/b/Savings-Center-Special-Buys/Power-Tools/N-5yc1vZ1z0ui8rZbwo5s?storeSelection={LOCATION['zip']}"

            print(f"  URL: {search_url}")
            await page.goto(search_url, wait_until="networkidle", timeout=45000)
            await asyncio.sleep(3)

            # Scroll to load products
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1)

            # Extract product data
            products = await page.evaluate("""
                () => {
                    const results = [];
                    const items = document.querySelectorAll('[data-testid="product-pod"], .product-pod, [class*="ProductPod"]');

                    items.forEach(item => {
                        const text = item.innerText;

                        // Extract name
                        const nameEl = item.querySelector('[data-testid="product-title"], .product-title, h3, h2');
                        const name = nameEl ? nameEl.innerText.trim() : '';

                        // Extract prices
                        const prices = text.match(/\\$([\\d,]+\\.?\\d*)/g) || [];
                        const priceNums = prices.map(p => parseFloat(p.replace(/[$,]/g, '')));

                        // Look for "was" price (original)
                        const wasMatch = text.match(/was\\s*\\$([\\d,]+)/i);
                        const originalPrice = wasMatch ? parseFloat(wasMatch[1].replace(',', '')) : null;

                        // Current price is usually the lowest
                        const currentPrice = priceNums.length > 0 ? Math.min(...priceNums) : null;

                        if (name && currentPrice && currentPrice < 500) {
                            results.push({
                                name: name.substring(0, 100),
                                currentPrice,
                                originalPrice,
                                discount: originalPrice ? Math.round((1 - currentPrice/originalPrice) * 100) : null,
                            });
                        }
                    });

                    return results;
                }
            """)

            # Screenshot for debugging
            screenshot_path = "/tmp/homedepot_clearance.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"  Screenshot saved: {screenshot_path}")

            await browser.close()

            # Process and filter results
            for product in products:
                category = categorize_tool(product['name'])
                if not category:
                    continue

                threshold = PRICE_THRESHOLDS.get(category, 150)
                discount = product.get('discount', 0) or 0

                if product['currentPrice'] <= threshold or discount >= MIN_DISCOUNT_PERCENT:
                    roi = calculate_rental_roi(product['currentPrice'], category)

                    results.append({
                        "name": product['name'],
                        "category": category,
                        "current_price": product['currentPrice'],
                        "original_price": product['originalPrice'],
                        "discount_percent": discount,
                        "rental_daily": roi['daily_rate'],
                        "rental_monthly_net": roi['monthly_net'],
                        "payback_months": roi['payback_months'],
                        "annual_profit": roi['annual_profit'],
                        "timestamp": datetime.now().isoformat(),
                    })

            print(f"  Found {len(results)} qualifying deals")

    except Exception as e:
        print(f"  Error: {e}")

    return results


async def check_and_alert():
    """Main function: scrape and send alerts for good deals."""
    print("=" * 60)
    print("HOME DEPOT CLEARANCE MONITOR")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Min discount: {MIN_DISCOUNT_PERCENT}%")

    deals = await scrape_homedepot_clearance()

    if not deals:
        print("\nNo qualifying deals found.")
        return

    print("\n" + "=" * 60)
    print("DEALS FOUND")
    print("=" * 60)

    for deal in deals:
        # Format alert message
        msg = f"""🔧 {deal['name'][:50]}

💰 ${deal['current_price']:.0f}"""

        if deal['original_price']:
            msg += f" (was ${deal['original_price']:.0f} = {deal['discount_percent']}% off)"

        msg += f"""

📊 Rental ROI:
  • Daily rate: ${deal['rental_daily']}
  • Monthly net: ${deal['rental_monthly_net']}
  • Payback: {deal['payback_months']} months
  • Annual profit: ${deal['annual_profit']}"""

        print(msg)
        print("-" * 40)

        # Send alert
        priority = "high" if deal['payback_months'] < 2 else "default"
        tags = "moneybag" if deal['annual_profit'] > 300 else "toolbox"

        await send_alert(msg, priority=priority, tags=tags)

    # Save results
    results_path = Path(__file__).parent / "clearance_deals.json"
    with open(results_path, 'w') as f:
        json.dump(deals, f, indent=2)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    asyncio.run(check_and_alert())
