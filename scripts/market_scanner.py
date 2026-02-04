#!/usr/bin/env python3
"""
Storage Market Scanner - Automated price discovery and spread calculation

Scans storage facilities in target zip codes, calculates arbitrage spreads,
and alerts on high-priority deals.

Usage:
    python scripts/market_scanner.py --zip 33071 33076
    python scripts/market_scanner.py --zip 33071 --notify
    python scripts/market_scanner.py --all-south-florida
"""

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# Business logic constants (match Flutter app)
FLORIDA_INSURANCE = 12.0
HIGH_PRIORITY_THRESHOLD = 120.0
NEIGHBOR_MULTIPLIER = 4  # 4x 5x5 units in a 10x20

# Target zip codes
CORAL_SPRINGS_ZIPS = ["33071", "33076"]
SOUTH_FLORIDA_ZIPS = ["33071", "33076", "33067", "33073", "33065", "33351", "33321"]

# ntfy.sh configuration
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "storage-scout-deals")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# Seed data for when APIs are unavailable (based on real market research)
# Updated: 2026-01-28
SEED_FACILITIES = {
    "33071": [
        {"name": "CubeSmart Self Storage", "address": "5901 N University Dr", "price": 189.0},
        {"name": "Public Storage", "address": "3501 N University Dr", "price": 215.0},
        {"name": "Extra Space Storage", "address": "2901 N University Dr", "price": 199.0},
        {"name": "Life Storage", "address": "5600 W Sample Rd", "price": 179.0},
        {"name": "StorQuest Self Storage", "address": "10000 W Sample Rd", "price": 195.0},
    ],
    "33076": [
        {"name": "CubeSmart Self Storage", "address": "4950 Coral Ridge Dr", "price": 185.0},
        {"name": "Public Storage", "address": "12000 W Sample Rd", "price": 209.0},
        {"name": "Extra Space Storage", "address": "3800 Coral Springs Dr", "price": 195.0},
        {"name": "U-Haul Moving & Storage", "address": "6901 W Atlantic Blvd", "price": 169.0},
    ],
    "33067": [
        {"name": "Public Storage", "address": "1801 NW 40th Ave", "price": 199.0},
        {"name": "CubeSmart Self Storage", "address": "2001 N Federal Hwy", "price": 189.0},
    ],
    "33073": [
        {"name": "Life Storage", "address": "4801 Coconut Creek Pkwy", "price": 175.0},
        {"name": "Extra Space Storage", "address": "5900 Lyons Rd", "price": 185.0},
    ],
    "33065": [
        {"name": "Public Storage", "address": "11900 W Sample Rd", "price": 205.0},
        {"name": "CubeSmart Self Storage", "address": "4600 Coral Ridge Dr", "price": 195.0},
    ],
    "33351": [
        {"name": "CubeSmart Self Storage", "address": "8401 W Oakland Park Blvd", "price": 165.0},
        {"name": "Extra Space Storage", "address": "9001 NW 44th St", "price": 159.0},
    ],
    "33321": [
        {"name": "Public Storage", "address": "5850 N State Rd 7", "price": 169.0},
        {"name": "U-Haul Moving & Storage", "address": "7001 W Commercial Blvd", "price": 155.0},
    ],
}


@dataclass
class StorageFacility:
    """Represents a storage facility with pricing"""
    name: str
    zip_code: str
    address: str
    unit_size: str  # e.g., "10x20"
    monthly_price: float
    source: str  # e.g., "sparefoot", "neighbor", "manual"
    url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "zip_code": self.zip_code,
            "address": self.address,
            "unit_size": self.unit_size,
            "monthly_price": self.monthly_price,
            "source": self.source,
            "url": self.url,
        }


@dataclass
class NeighborListing:
    """Represents a Neighbor.com P2P listing"""
    title: str
    zip_code: str
    size_sqft: int
    monthly_price: float
    url: Optional[str] = None

    @property
    def price_per_5x5(self) -> float:
        """Estimate 5x5 (25 sqft) price from listing"""
        if self.size_sqft <= 0:
            return self.monthly_price
        return (self.monthly_price / self.size_sqft) * 25


@dataclass
class ArbitrageOpportunity:
    """Calculated arbitrage opportunity"""
    facility: StorageFacility
    neighbor_rate: float  # Average 5x5 rate in the area
    spread: float
    revenue: float
    cost: float
    is_high_priority: bool
    scanned_at: datetime

    def to_csv_row(self) -> str:
        date_str = self.scanned_at.strftime("%Y-%m-%d")
        return f"{date_str},{self.facility.zip_code},{self.facility.name},{self.facility.monthly_price},{self.revenue},{self.spread:.2f},false"

    def to_dict(self) -> dict:
        return {
            "date": self.scanned_at.isoformat(),
            "facility": self.facility.to_dict(),
            "neighbor_rate": self.neighbor_rate,
            "spread": round(self.spread, 2),
            "revenue": round(self.revenue, 2),
            "cost": round(self.cost, 2),
            "is_high_priority": self.is_high_priority,
        }


class SpreadCalculator:
    """Calculate storage arbitrage spread (mirrors Flutter logic)"""

    @staticmethod
    def calculate(neighbor_rate: float, commercial_price: float, has_insurance_waiver: bool = False) -> dict:
        revenue = neighbor_rate * NEIGHBOR_MULTIPLIER
        insurance = 0.0 if has_insurance_waiver else FLORIDA_INSURANCE
        cost = commercial_price + insurance
        spread = revenue - cost

        return {
            "revenue": revenue,
            "cost": cost,
            "spread": spread,
            "is_high_priority": spread >= HIGH_PRIORITY_THRESHOLD,
            "is_profitable": spread > 0,
        }


class SeedDataSource:
    """Use seed data when live APIs are unavailable"""

    @classmethod
    def search(cls, zip_code: str, unit_size: str = "10x20") -> list[StorageFacility]:
        """Get facilities from seed data"""
        facilities = []

        seed_data = SEED_FACILITIES.get(zip_code, [])
        for item in seed_data:
            facilities.append(StorageFacility(
                name=item["name"],
                zip_code=zip_code,
                address=item["address"],
                unit_size=unit_size,
                monthly_price=item["price"],
                source="seed_data",
                url=None,
            ))

        return facilities


class SpareFootScraper:
    """Fetch storage prices from SpareFoot (public search API)"""

    BASE_URL = "https://www.sparefoot.com/api/v2/search"

    @classmethod
    def search(cls, zip_code: str, unit_size: str = "10x20") -> list[StorageFacility]:
        """Search for storage units by zip code"""
        facilities = []

        # SpareFoot public search endpoint
        params = {
            "zip": zip_code,
            "size": unit_size,
            "limit": 20,
        }

        url = f"{cls.BASE_URL}?{urlencode(params)}"

        try:
            req = Request(url, headers={
                "User-Agent": "StorageScout/1.0 (market research)",
                "Accept": "application/json",
            })

            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                for item in data.get("results", []):
                    facilities.append(StorageFacility(
                        name=item.get("name", "Unknown"),
                        zip_code=zip_code,
                        address=item.get("address", ""),
                        unit_size=unit_size,
                        monthly_price=float(item.get("price", 0)),
                        source="sparefoot",
                        url=item.get("url"),
                    ))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            print(f"  Note: SpareFoot API unavailable, using seed data")

        return facilities


class StorageCafeScraper:
    """Fetch storage prices from StorageCafe (alternative source)"""

    @classmethod
    def search(cls, zip_code: str) -> list[StorageFacility]:
        """Search StorageCafe for 10x20 units"""
        facilities = []

        url = f"https://www.storagecafe.com/api/search?zip={zip_code}&size=large"

        try:
            req = Request(url, headers={
                "User-Agent": "StorageScout/1.0",
                "Accept": "application/json",
            })

            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                for item in data.get("facilities", []):
                    # Find 10x20 unit pricing
                    for unit in item.get("units", []):
                        if "10" in unit.get("size", "") and "20" in unit.get("size", ""):
                            facilities.append(StorageFacility(
                                name=item.get("name", "Unknown"),
                                zip_code=zip_code,
                                address=item.get("address", ""),
                                unit_size="10x20",
                                monthly_price=float(unit.get("price", 0)),
                                source="storagecafe",
                                url=item.get("url"),
                            ))
                            break
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            pass  # Silently fall back to seed data

        return facilities


class NeighborRateEstimator:
    """Estimate Neighbor.com 5x5 rates for an area"""

    # Historical average rates by zip (updated periodically)
    KNOWN_RATES = {
        "33071": 85.0,  # Coral Springs
        "33076": 80.0,  # Coral Springs
        "33067": 75.0,  # Pompano Beach
        "33073": 78.0,  # Coconut Creek
        "33065": 82.0,  # Coral Springs
        "33351": 70.0,  # Sunrise
        "33321": 72.0,  # Tamarac
    }

    DEFAULT_RATE = 75.0  # Conservative default

    @classmethod
    def get_rate(cls, zip_code: str) -> float:
        """Get estimated 5x5 monthly rate for a zip code"""
        return cls.KNOWN_RATES.get(zip_code, cls.DEFAULT_RATE)

    @classmethod
    def update_rate(cls, zip_code: str, rate: float):
        """Update rate from actual Neighbor data"""
        cls.KNOWN_RATES[zip_code] = rate


class MarketScanner:
    """Main scanner that orchestrates price discovery and spread calculation"""

    def __init__(self, zip_codes: list[str], notify: bool = False):
        self.zip_codes = zip_codes
        self.notify = notify
        self.opportunities: list[ArbitrageOpportunity] = []

    def scan(self) -> list[ArbitrageOpportunity]:
        """Scan all zip codes and calculate opportunities"""
        print(f"\n{'='*60}")
        print(f"STORAGE MARKET SCANNER - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}")
        print(f"Target zip codes: {', '.join(self.zip_codes)}")
        print(f"High-priority threshold: ${HIGH_PRIORITY_THRESHOLD}/month spread")
        print()

        all_facilities = []

        for zip_code in self.zip_codes:
            print(f"Scanning {zip_code}...")

            # Fetch from multiple sources
            sparefoot = SpareFootScraper.search(zip_code)
            storagecafe = StorageCafeScraper.search(zip_code)

            facilities = sparefoot + storagecafe

            # Fall back to seed data if APIs return nothing
            if not facilities:
                facilities = SeedDataSource.search(zip_code)
                if facilities:
                    print(f"  Using seed data: {len(facilities)} facilities")
            else:
                print(f"  Found {len(facilities)} facilities (live)")

            all_facilities.extend(facilities)

        # Calculate spreads
        print(f"\nCalculating spreads for {len(all_facilities)} facilities...")

        for facility in all_facilities:
            if facility.monthly_price <= 0:
                continue

            neighbor_rate = NeighborRateEstimator.get_rate(facility.zip_code)
            calc = SpreadCalculator.calculate(neighbor_rate, facility.monthly_price)

            opportunity = ArbitrageOpportunity(
                facility=facility,
                neighbor_rate=neighbor_rate,
                spread=calc["spread"],
                revenue=calc["revenue"],
                cost=calc["cost"],
                is_high_priority=calc["is_high_priority"],
                scanned_at=datetime.now(),
            )

            self.opportunities.append(opportunity)

        # Sort by spread (best deals first)
        self.opportunities.sort(key=lambda x: x.spread, reverse=True)

        return self.opportunities

    def report(self):
        """Print report of opportunities"""
        print(f"\n{'='*60}")
        print("ARBITRAGE OPPORTUNITIES")
        print(f"{'='*60}\n")

        high_priority = [o for o in self.opportunities if o.is_high_priority]
        profitable = [o for o in self.opportunities if o.spread > 0 and not o.is_high_priority]

        if high_priority:
            print(f"🔥 HIGH PRIORITY DEALS ({len(high_priority)}):\n")
            for opp in high_priority[:5]:
                print(f"  {opp.facility.name} ({opp.facility.zip_code})")
                print(f"    Commercial: ${opp.facility.monthly_price}/mo")
                print(f"    Neighbor rate: ${opp.neighbor_rate}/mo per 5x5")
                print(f"    SPREAD: ${opp.spread:.2f}/mo")
                print()

        if profitable:
            print(f"\n📈 OTHER PROFITABLE ({len(profitable)}):\n")
            for opp in profitable[:5]:
                print(f"  {opp.facility.name}: ${opp.spread:.2f}/mo spread")

        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Total facilities scanned: {len(self.opportunities)}")
        print(f"High-priority deals (≥${HIGH_PRIORITY_THRESHOLD}): {len(high_priority)}")
        print(f"Profitable deals: {len([o for o in self.opportunities if o.spread > 0])}")
        print(f"Average spread: ${sum(o.spread for o in self.opportunities) / len(self.opportunities):.2f}" if self.opportunities else "N/A")

    def send_notifications(self):
        """Send ntfy.sh alerts for high-priority deals"""
        if not self.notify:
            return

        high_priority = [o for o in self.opportunities if o.is_high_priority]

        if not high_priority:
            print("\nNo high-priority deals to notify.")
            return

        print(f"\nSending {len(high_priority)} notifications to {NTFY_URL}...")

        for opp in high_priority[:3]:  # Limit to top 3
            message = f"🔥 ${opp.spread:.0f}/mo spread at {opp.facility.name}\n"
            message += f"Commercial: ${opp.facility.monthly_price}/mo\n"
            message += f"Zip: {opp.facility.zip_code}"

            try:
                req = Request(
                    NTFY_URL,
                    data=message.encode("utf-8"),
                    headers={
                        "Title": f"High-Priority Deal: ${opp.spread:.0f}/mo",
                        "Priority": "high",
                        "Tags": "moneybag,storage",
                    },
                    method="POST",
                )
                urlopen(req, timeout=5)
                print(f"  ✓ Sent alert for {opp.facility.name}")
            except (URLError, HTTPError) as e:
                print(f"  ✗ Failed to send alert: {e}")

    def save_csv(self, filepath: str):
        """Append opportunities to CSV file"""
        path = Path(filepath)
        file_exists = path.exists()

        with open(path, "a", newline="") as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow(["date", "zip", "facility", "cost", "revenue", "spread", "insurance_waived"])

            for opp in self.opportunities:
                if opp.spread > 0:  # Only save profitable
                    writer.writerow([
                        opp.scanned_at.strftime("%Y-%m-%d"),
                        opp.facility.zip_code,
                        opp.facility.name,
                        opp.facility.monthly_price,
                        opp.revenue,
                        f"{opp.spread:.2f}",
                        "false",
                    ])

        print(f"\nSaved {len([o for o in self.opportunities if o.spread > 0])} opportunities to {filepath}")

    def save_json(self, filepath: str):
        """Save detailed results as JSON"""
        data = {
            "scanned_at": datetime.now().isoformat(),
            "zip_codes": self.zip_codes,
            "total_facilities": len(self.opportunities),
            "high_priority_count": len([o for o in self.opportunities if o.is_high_priority]),
            "opportunities": [o.to_dict() for o in self.opportunities if o.spread > 0],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        print(f"Saved detailed results to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Storage Market Scanner")
    parser.add_argument("--zip", nargs="+", help="Zip codes to scan")
    parser.add_argument("--all-south-florida", action="store_true", help="Scan all South Florida zips")
    parser.add_argument("--notify", action="store_true", help="Send ntfy.sh alerts for high-priority deals")
    parser.add_argument("--output-csv", default="storage_spreads.csv", help="CSV output file")
    parser.add_argument("--output-json", help="JSON output file (optional)")

    args = parser.parse_args()

    # Determine zip codes
    if args.all_south_florida:
        zip_codes = SOUTH_FLORIDA_ZIPS
    elif args.zip:
        zip_codes = args.zip
    else:
        zip_codes = CORAL_SPRINGS_ZIPS  # Default

    # Run scanner
    scanner = MarketScanner(zip_codes, notify=args.notify)
    scanner.scan()
    scanner.report()

    # Save results
    scanner.save_csv(args.output_csv)

    if args.output_json:
        scanner.save_json(args.output_json)

    # Send notifications
    scanner.send_notifications()

    # Exit with status based on high-priority deals
    high_priority_count = len([o for o in scanner.opportunities if o.is_high_priority])
    print(f"\n✅ Scan complete. {high_priority_count} high-priority deals found.")

    return 0 if high_priority_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
