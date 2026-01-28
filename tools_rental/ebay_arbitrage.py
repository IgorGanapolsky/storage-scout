#!/usr/bin/env python3
"""
eBay Arbitrage Tool

Finds Home Depot clearance tools and checks eBay sold prices.
Alerts when profitable opportunities exist.

Flow:
1. Scrape HD clearance/deals
2. Search eBay sold listings for same item
3. Calculate spread
4. Alert if profit margin > 20%
"""

import json
import re
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class ArbitrageOpportunity:
    """A profitable buy-resell opportunity."""
    name: str
    source: str  # home_depot, lowes, etc
    source_price: float
    source_url: Optional[str]

    ebay_avg_sold: float
    ebay_min_sold: float
    ebay_max_sold: float
    ebay_sold_count: int

    estimated_profit: float
    profit_margin_pct: float

    category: str
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


class EbayArbitrageScanner:
    """
    Scans for arbitrage opportunities between retail stores and eBay.
    """

    NTFY_TOPIC = "igor_tools_alerts"
    MIN_PROFIT_MARGIN = 0.15  # 15% minimum profit
    MIN_PROFIT_DOLLARS = 10   # $10 minimum profit

    # Known profitable categories
    CATEGORIES = {
        "power_tools": [
            "dewalt 20v starter kit",
            "dewalt powerstack",
            "milwaukee m18 battery",
            "ryobi one+ battery",
            "makita 18v battery",
        ],
        "tool_accessories": [
            "milwaukee oscillating blades",
            "dewalt drill bits",
            "diablo saw blades",
        ],
        "outdoor_power": [
            "ryobi pressure washer",
            "dewalt blower",
            "ego battery",
        ],
    }

    # Home Depot clearance URLs to check
    HD_CLEARANCE_URLS = [
        "https://www.homedepot.com/b/Tools-Power-Tools/Clearance/N-5yc1vZc298Z1z11adf",
        "https://www.homedepot.com/b/Tool-Savings/N-5yc1vZ1z1zuqf",
    ]

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path(__file__).parent / "data"
        self.data_dir.mkdir(exist_ok=True)
        self.opportunities_file = self.data_dir / "arbitrage_opportunities.json"
        self.opportunities: List[ArbitrageOpportunity] = []
        self._load()

    def _load(self):
        if self.opportunities_file.exists():
            with open(self.opportunities_file) as f:
                data = json.load(f)
                self.opportunities = [ArbitrageOpportunity(**o) for o in data]

    def _save(self):
        with open(self.opportunities_file, 'w') as f:
            from dataclasses import asdict
            json.dump([asdict(o) for o in self.opportunities], f, indent=2)

    def search_ebay_sold(self, query: str) -> dict:
        """
        Search eBay for sold listings of an item.
        Returns average, min, max sold prices.

        Note: This is a simplified version. In production, use eBay API.
        """
        # Encode search query
        encoded = urllib.parse.quote(query)
        url = f"https://www.ebay.com/sch/i.html?_nkw={encoded}&LH_Sold=1&LH_Complete=1"

        print(f"  Searching eBay: {query}")
        print(f"  URL: {url}")

        # For now, return placeholder - in production use eBay API or scraping
        # This is where you'd parse actual eBay data
        return {
            "query": query,
            "url": url,
            "note": "Check manually or implement eBay API",
        }

    def calculate_opportunity(
        self,
        name: str,
        source_price: float,
        ebay_sold_prices: List[float],
        source: str = "home_depot",
        source_url: str = None,
        category: str = "power_tools",
    ) -> Optional[ArbitrageOpportunity]:
        """
        Calculate if an arbitrage opportunity exists.
        """
        if not ebay_sold_prices:
            return None

        avg_sold = sum(ebay_sold_prices) / len(ebay_sold_prices)
        min_sold = min(ebay_sold_prices)
        max_sold = max(ebay_sold_prices)

        # Calculate profit (conservative - use average, account for fees)
        ebay_fees = 0.13  # ~13% eBay + PayPal fees
        shipping_cost = 10  # Estimated

        net_after_fees = avg_sold * (1 - ebay_fees) - shipping_cost
        profit = net_after_fees - source_price
        margin = profit / source_price if source_price > 0 else 0

        if profit >= self.MIN_PROFIT_DOLLARS and margin >= self.MIN_PROFIT_MARGIN:
            return ArbitrageOpportunity(
                name=name,
                source=source,
                source_price=source_price,
                source_url=source_url,
                ebay_avg_sold=avg_sold,
                ebay_min_sold=min_sold,
                ebay_max_sold=max_sold,
                ebay_sold_count=len(ebay_sold_prices),
                estimated_profit=round(profit, 2),
                profit_margin_pct=round(margin * 100, 1),
                category=category,
            )
        return None

    def add_manual_opportunity(
        self,
        name: str,
        source_price: float,
        ebay_sold_prices: List[float],
        source_url: str = None,
    ):
        """
        Manually add an opportunity after checking prices.
        """
        opp = self.calculate_opportunity(
            name=name,
            source_price=source_price,
            ebay_sold_prices=ebay_sold_prices,
            source_url=source_url,
        )

        if opp:
            self.opportunities.append(opp)
            self._save()
            self._send_alert(opp)
            return opp
        else:
            print(f"Not profitable enough: {name}")
            return None

    def _send_alert(self, opp: ArbitrageOpportunity):
        """Send push notification for opportunity."""
        message = f"""🤑 ARBITRAGE OPPORTUNITY

{opp.name}

BUY: {opp.source} @ ${opp.source_price:.2f}
{opp.source_url or ''}

SELL: eBay avg ${opp.ebay_avg_sold:.2f}
(Range: ${opp.ebay_min_sold:.2f} - ${opp.ebay_max_sold:.2f})
Sold count: {opp.ebay_sold_count}

💰 PROFIT: ${opp.estimated_profit:.2f} ({opp.profit_margin_pct}%)

ACT NOW - Clearance items sell out!"""

        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{self.NTFY_TOPIC}",
                data=message.encode(),
                headers={
                    "Title": f"${opp.estimated_profit:.0f} profit: {opp.name[:30]}",
                    "Priority": "high",
                    "Tags": "moneybag,shopping",
                }
            )
            urllib.request.urlopen(req, timeout=10)
            print(f"Alert sent!")
        except Exception as e:
            print(f"Alert failed: {e}")

    def list_opportunities(self) -> List[ArbitrageOpportunity]:
        """List all current opportunities sorted by profit."""
        return sorted(
            self.opportunities,
            key=lambda x: x.estimated_profit,
            reverse=True
        )

    def print_opportunities(self):
        """Print opportunities in a nice table."""
        opps = self.list_opportunities()

        if not opps:
            print("No opportunities found yet.")
            print("\nTo add one manually:")
            print('  scanner.add_manual_opportunity(')
            print('      name="DeWalt 20V Starter Kit",')
            print('      source_price=65,')
            print('      ebay_sold_prices=[75, 80, 85, 90],')
            print('      source_url="https://homedepot.com/..."')
            print('  )')
            return

        print("\n" + "=" * 70)
        print("ARBITRAGE OPPORTUNITIES")
        print("=" * 70)

        for opp in opps:
            print(f"\n{opp.name}")
            print(f"  Buy:    ${opp.source_price:.2f} @ {opp.source}")
            print(f"  Sell:   ${opp.ebay_avg_sold:.2f} avg on eBay ({opp.ebay_sold_count} sold)")
            print(f"  Profit: ${opp.estimated_profit:.2f} ({opp.profit_margin_pct}%)")
            if opp.source_url:
                print(f"  URL:    {opp.source_url}")


# Known opportunities based on research
KNOWN_OPPORTUNITIES = [
    {
        "name": "DeWalt 20V MAX Battery Starter Kit DCB205-2CK",
        "source_price": 89,
        "ebay_sold_prices": [129.97, 119.99, 124.95, 115.00],
        "source_url": "https://www.homedepot.com/p/DEWALT-20V-MAX-Lithium-Ion-Battery-Pack-5-0Ah-2-Pack-with-Charger-DCB205-2CK/318936011",
    },
    {
        "name": "DeWalt Powerstack 20V Starter Kit DCBP034C",
        "source_price": 65,
        "ebay_sold_prices": [64.95, 65.00, 75.00, 82.99],
        "source_url": "https://www.homedepot.com/p/DEWALT-20V-MAX-POWERSTACK-Compact-Battery-Starter-Kit-DCBP034C/320897892",
    },
    {
        "name": "Milwaukee Oscillating Multi-Tool Blades 5-Pack",
        "source_price": 15,
        "ebay_sold_prices": [24.99, 27.50, 29.99, 22.00],
        "source_url": None,
    },
]


if __name__ == "__main__":
    print("=" * 60)
    print("EBAY ARBITRAGE SCANNER")
    print("Home Depot → eBay Resale Profit Finder")
    print("=" * 60)

    scanner = EbayArbitrageScanner()

    # Add known opportunities
    print("\nChecking known opportunities...")
    for item in KNOWN_OPPORTUNITIES:
        opp = scanner.add_manual_opportunity(
            name=item["name"],
            source_price=item["source_price"],
            ebay_sold_prices=item["ebay_sold_prices"],
            source_url=item.get("source_url"),
        )
        if opp:
            print(f"  ✓ {opp.name}: ${opp.estimated_profit:.2f} profit")
        else:
            print(f"  ✗ {item['name']}: Not profitable")

    # Print all opportunities
    scanner.print_opportunities()

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    print("""
1. Check Home Depot clearance:
   https://www.homedepot.com/b/Tools-Power-Tools/Clearance/

2. For each item, search eBay SOLD listings:
   https://www.ebay.com/sch/i.html?_nkw=ITEM+NAME&LH_Sold=1&LH_Complete=1

3. If profitable, add to scanner:
   scanner.add_manual_opportunity(
       name="Item Name",
       source_price=XX.XX,
       ebay_sold_prices=[price1, price2, price3],
       source_url="https://..."
   )

4. Buy the item at Home Depot
5. List on eBay at market price
6. Ship when sold, collect profit
""")
