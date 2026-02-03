#!/usr/bin/env python3
"""
Just-In-Time Tool Rental Arbitrage

ZERO UPFRONT INVESTMENT model:
1. List tools you DON'T own yet (virtual inventory)
2. When booking request comes in, THEN buy the tool
3. Fulfill the rental, keep the spread

Flow:
┌─────────────────────────────────────────────────────────────┐
│  ZERO-INVENTORY ARBITRAGE                                   │
│                                                             │
│  1. Scraper finds: Pressure washer $89 at HD               │
│  2. Auto-list on Neighbor/2Quip at $40/day                 │
│  3. Customer books 3-day rental ($120)                     │
│  4. Alert: "BUY NOW - Guaranteed profit!"                  │
│  5. You buy tool ($89), fulfill rental                     │
│  6. Keep tool for future rentals (now free inventory)      │
│                                                             │
│  PROFIT: $120 - $89 = $31 on FIRST rental                  │
│  Future rentals = 100% profit (tool is paid off)           │
└─────────────────────────────────────────────────────────────┘

This is the Amazon FBA model applied to tool rentals.
"""

import json
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from config import LOCATION, MARKET_RATES, NTFY_TOPIC


@dataclass
class VirtualListing:
    """A tool listed for rent that we don't own yet."""
    id: str
    name: str
    category: str

    # Where we can buy it
    source_store: str  # "home_depot", "lowes", "amazon"
    source_price: float
    source_url: Optional[str]

    # What we're listing it for
    rental_daily: float
    rental_weekly: float

    # Profit calculation
    min_rental_days_to_profit: int  # How many days to break even

    # Status
    status: str = "virtual"  # virtual, pending_purchase, owned
    listing_urls: Dict[str, str] = None  # platform -> listing URL

    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.listing_urls is None:
            self.listing_urls = {}

        # Calculate break-even
        self.min_rental_days_to_profit = int(self.source_price / self.rental_daily) + 1

    @property
    def first_rental_profit(self) -> float:
        """Profit if someone books 3 days."""
        return (self.rental_daily * 3) - self.source_price

    @property
    def is_profitable_first_rental(self) -> bool:
        """Can we profit on the very first 3-day rental?"""
        return self.first_rental_profit > 0

    def to_listing_text(self) -> Dict[str, str]:
        """Generate listing for rental platforms."""
        title = f"{self.name} - Available Now in {LOCATION['city']}"

        description = f"""
{self.name} available for rent in {LOCATION['city']}, {LOCATION['state']}.

✓ Professional-grade equipment
✓ Well-maintained and tested
✓ Pickup in {LOCATION['city']} ({LOCATION['zip']})
✓ Same-day availability with advance notice

RATES:
• Daily: ${self.rental_daily:.0f}
• Weekly: ${self.rental_weekly:.0f} (save ${self.rental_daily * 7 - self.rental_weekly:.0f}!)

Perfect for weekend projects, home renovations, or one-time jobs.

Message to check availability and schedule pickup!
"""
        return {
            "title": title,
            "description": description.strip(),
            "daily_rate": self.rental_daily,
            "weekly_rate": self.rental_weekly,
            "location": f"{LOCATION['city']}, {LOCATION['state']} {LOCATION['zip']}",
        }


@dataclass
class BookingRequest:
    """An incoming booking request."""
    id: str
    listing_id: str
    platform: str  # where the request came from

    renter_name: str
    renter_contact: str

    start_date: str
    end_date: str
    rental_days: int

    quoted_amount: float

    # Purchase decision
    source_price: float
    profit_if_fulfilled: float

    status: str = "pending"  # pending, approved, purchased, fulfilled, cancelled

    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class JITArbitrageEngine:
    """
    Just-In-Time Arbitrage Engine

    Manages virtual inventory and converts booking requests into purchases.
    """

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path(__file__).parent / "data"
        self.data_dir.mkdir(exist_ok=True)

        self.listings_file = self.data_dir / "virtual_listings.json"
        self.requests_file = self.data_dir / "booking_requests.json"

        self.listings: Dict[str, VirtualListing] = {}
        self.requests: List[BookingRequest] = []

        self._load()

    def _load(self):
        if self.listings_file.exists():
            with open(self.listings_file) as f:
                data = json.load(f)
                self.listings = {item['id']: VirtualListing(**item) for item in data}

        if self.requests_file.exists():
            with open(self.requests_file) as f:
                data = json.load(f)
                self.requests = [BookingRequest(**r) for r in data]

    def _save(self):
        with open(self.listings_file, 'w') as f:
            json.dump([asdict(listing) for listing in self.listings.values()], f, indent=2)

        with open(self.requests_file, 'w') as f:
            json.dump([asdict(r) for r in self.requests], f, indent=2)

    def create_virtual_listing(
        self,
        name: str,
        category: str,
        source_store: str,
        source_price: float,
        source_url: str = None,
    ) -> VirtualListing:
        """
        Create a listing for a tool we don't own yet.
        Pricing is auto-calculated based on market rates.
        """
        market = MARKET_RATES.get(category, {"daily": 30, "weekly": 100})

        listing = VirtualListing(
            id=f"{category[:2]}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            name=name,
            category=category,
            source_store=source_store,
            source_price=source_price,
            source_url=source_url,
            rental_daily=market["daily"],
            rental_weekly=market["weekly"],
            min_rental_days_to_profit=0,  # Will be calculated
        )

        self.listings[listing.id] = listing
        self._save()

        print(f"Created virtual listing: {listing.name}")
        print(f"  Source: {source_store} @ ${source_price}")
        print(f"  Rental: ${listing.rental_daily}/day")
        print(f"  Break-even: {listing.min_rental_days_to_profit} days")
        print(f"  First 3-day profit: ${listing.first_rental_profit:.2f}")

        return listing

    def process_booking_request(
        self,
        listing_id: str,
        renter_name: str,
        renter_contact: str,
        start_date: str,
        end_date: str,
        platform: str = "direct",
    ) -> BookingRequest:
        """
        Process an incoming booking request.
        Calculate profit and alert if profitable.
        """
        if listing_id not in self.listings:
            raise ValueError(f"Listing {listing_id} not found")

        listing = self.listings[listing_id]

        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        days = (end - start).days

        # Calculate rental amount
        if days >= 7:
            weeks = days // 7
            remaining = days % 7
            amount = (weeks * listing.rental_weekly) + (remaining * listing.rental_daily)
        else:
            amount = days * listing.rental_daily

        profit = amount - listing.source_price

        request = BookingRequest(
            id=f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            listing_id=listing_id,
            platform=platform,
            renter_name=renter_name,
            renter_contact=renter_contact,
            start_date=start_date,
            end_date=end_date,
            rental_days=days,
            quoted_amount=amount,
            source_price=listing.source_price,
            profit_if_fulfilled=profit,
        )

        self.requests.append(request)
        self._save()

        # Alert!
        self._send_booking_alert(request, listing)

        return request

    def _send_booking_alert(self, request: BookingRequest, listing: VirtualListing):
        """Send push notification for booking request."""

        if request.profit_if_fulfilled > 0:
            priority = "urgent"
            emoji = "🤑"
            action = "BUY NOW"
        else:
            priority = "default"
            emoji = "⚠️"
            action = "REVIEW"

        message = f"""{emoji} BOOKING REQUEST - {action}

{listing.name}
Renter: {request.renter_name}
Dates: {request.start_date} to {request.end_date} ({request.rental_days} days)
Rental: ${request.quoted_amount:.0f}

PURCHASE: {listing.source_store} @ ${listing.source_price:.0f}
{listing.source_url or ''}

💰 PROFIT: ${request.profit_if_fulfilled:.0f}

Reply YES to approve and get purchase link."""

        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=message.encode(),
                headers={
                    "Title": f"{action}: ${request.profit_if_fulfilled:.0f} profit opportunity",
                    "Priority": priority,
                    "Tags": "moneybag,hammer" if request.profit_if_fulfilled > 0 else "warning",
                    "Actions": f"view, Buy Tool, {listing.source_url}" if listing.source_url else "",
                }
            )
            urllib.request.urlopen(req, timeout=10)
            print(f"Alert sent for {request.id}")
        except Exception as e:
            print(f"Failed to send alert: {e}")

    def approve_request(self, request_id: str) -> Dict:
        """
        Approve a booking request.
        Returns purchase instructions.
        """
        request = next((r for r in self.requests if r.id == request_id), None)
        if not request:
            raise ValueError(f"Request {request_id} not found")

        listing = self.listings[request.listing_id]

        request.status = "approved"
        self._save()

        return {
            "status": "approved",
            "request_id": request_id,
            "action_required": "PURCHASE TOOL",
            "purchase": {
                "store": listing.source_store,
                "item": listing.name,
                "price": listing.source_price,
                "url": listing.source_url,
            },
            "rental": {
                "renter": request.renter_name,
                "contact": request.renter_contact,
                "dates": f"{request.start_date} to {request.end_date}",
                "amount": request.quoted_amount,
            },
            "profit": request.profit_if_fulfilled,
            "next_steps": [
                f"1. Buy {listing.name} from {listing.source_store} for ${listing.source_price}",
                f"2. Contact {request.renter_name} at {request.renter_contact}",
                f"3. Arrange pickup for {request.start_date}",
                f"4. Collect ${request.quoted_amount} + deposit",
                f"5. Profit: ${request.profit_if_fulfilled}",
            ],
        }

    def get_profitable_opportunities(self) -> List[Dict]:
        """Get all virtual listings that profit on first rental."""
        opportunities = []

        for listing in self.listings.values():
            if listing.status == "virtual" and listing.is_profitable_first_rental:
                opportunities.append({
                    "listing_id": listing.id,
                    "name": listing.name,
                    "source_price": listing.source_price,
                    "rental_daily": listing.rental_daily,
                    "first_rental_profit": listing.first_rental_profit,
                    "break_even_days": listing.min_rental_days_to_profit,
                })

        return sorted(opportunities, key=lambda x: x["first_rental_profit"], reverse=True)

    def get_pending_requests(self) -> List[BookingRequest]:
        """Get all pending booking requests."""
        return [r for r in self.requests if r.status == "pending"]


def create_virtual_inventory_from_clearance(clearance_deals: List[Dict]) -> List[VirtualListing]:
    """
    Take clearance deals and create virtual listings.
    Call this after running clearance_scraper.py
    """
    engine = JITArbitrageEngine()
    listings = []

    for deal in clearance_deals:
        listing = engine.create_virtual_listing(
            name=deal["name"],
            category=deal["category"],
            source_store="home_depot",
            source_price=deal["current_price"],
            source_url=deal.get("url"),
        )
        listings.append(listing)

    return listings


if __name__ == "__main__":
    print("=" * 60)
    print("JUST-IN-TIME TOOL RENTAL ARBITRAGE")
    print("Zero Inventory Model")
    print("=" * 60)

    engine = JITArbitrageEngine()

    # Demo: Create virtual listing
    print("\n📦 Creating virtual listing (we don't own this yet)...")
    listing = engine.create_virtual_listing(
        name="Ryobi 2300 PSI Electric Pressure Washer",
        category="pressure_washer",
        source_store="home_depot",
        source_price=89.00,
        source_url="https://www.homedepot.com/p/123456",
    )

    # Demo: Simulate booking request
    print("\n📱 Simulating booking request...")
    request = engine.process_booking_request(
        listing_id=listing.id,
        renter_name="John Smith",
        renter_contact="john@email.com",
        start_date="2026-02-01",
        end_date="2026-02-04",  # 3 days
        platform="neighbor",
    )

    print("\n✅ Booking request received!")
    print(f"   Rental: ${request.quoted_amount} for {request.rental_days} days")
    print(f"   Tool cost: ${request.source_price}")
    print(f"   PROFIT: ${request.profit_if_fulfilled}")

    # Show approval flow
    print("\n" + "=" * 60)
    print("APPROVAL FLOW")
    print("=" * 60)
    approval = engine.approve_request(request.id)
    for step in approval["next_steps"]:
        print(f"   {step}")

    print("\n" + "=" * 60)
    print("💡 THE MODEL")
    print("=" * 60)
    print("""
    1. List tools you DON'T own (virtual inventory)
    2. When someone books, you get an alert
    3. Alert shows: profit, where to buy, customer info
    4. YOU decide: Buy the tool and fulfill, or decline
    5. First rental pays for the tool + profit
    6. Keep tool for future rentals (100% profit)

    ZERO UPFRONT COST. Only buy when you have a customer.
    """)
