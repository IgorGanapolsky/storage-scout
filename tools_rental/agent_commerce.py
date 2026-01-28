#!/usr/bin/env python3
"""
Agentic Commerce Layer for Tools Rental

Implements Google's Universal Commerce Protocol (UCP) patterns to make
tool listings discoverable by AI shopping agents.

Architecture:
┌─────────────────────────────────────────────────────────────┐
│  AGENTIC COMMERCE LAYER                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ Product API │  │ Pricing     │  │ Booking     │         │
│  │ (JSON-LD)   │  │ Agent       │  │ Agent       │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│         ↓                ↓                ↓                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           Universal Commerce Protocol                │   │
│  │     (Machine-readable, Agent-discoverable)           │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

References:
- https://developers.googleblog.com/under-the-hood-universal-commerce-protocol-ucp/
- https://cloud.google.com/transform/the-invisible-shelf-retail-cpg-agentic-commerce-how-to
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

from config import INVENTORY, PLATFORMS, MARKET_RATES, LOCATION


# Schema.org types for structured data
SCHEMA_CONTEXT = "https://schema.org"


@dataclass
class AgentReadableProduct:
    """
    Product data structured for AI agent discovery.
    Uses Schema.org Product + Offer patterns.
    """
    id: str
    name: str
    description: str
    category: str
    brand: Optional[str]
    condition: str

    # Pricing
    price_daily: float
    price_weekly: float
    price_currency: str = "USD"

    # Availability
    availability: str  # InStock, OutOfStock, PreOrder
    available_from: Optional[str] = None
    available_until: Optional[str] = None

    # Location
    area_served: str
    pickup_location: str
    delivery_available: bool = False

    # Attributes (for agent filtering)
    attributes: Dict[str, Any] = None

    # Merchant info
    merchant_name: str = "Igor's Tool Rentals"
    merchant_id: str = "igor-tools-coral-springs"

    def to_jsonld(self) -> Dict:
        """
        Convert to JSON-LD format for agent discovery.
        This is what AI shopping agents read.
        """
        return {
            "@context": SCHEMA_CONTEXT,
            "@type": "Product",
            "@id": f"urn:ucp:product:{self.merchant_id}:{self.id}",
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "brand": {"@type": "Brand", "name": self.brand} if self.brand else None,
            "itemCondition": f"https://schema.org/{self.condition.title()}Condition",
            "offers": {
                "@type": "AggregateOffer",
                "priceCurrency": self.price_currency,
                "lowPrice": self.price_daily,
                "highPrice": self.price_weekly,
                "offerCount": 2,
                "offers": [
                    {
                        "@type": "Offer",
                        "name": "Daily Rental",
                        "price": self.price_daily,
                        "priceCurrency": self.price_currency,
                        "priceValidUntil": (datetime.now() + timedelta(days=30)).isoformat(),
                        "availability": f"https://schema.org/{self.availability}",
                        "availableAtOrFrom": {
                            "@type": "Place",
                            "address": self.pickup_location,
                        },
                        "areaServed": {
                            "@type": "City",
                            "name": self.area_served,
                        },
                    },
                    {
                        "@type": "Offer",
                        "name": "Weekly Rental",
                        "price": self.price_weekly,
                        "priceCurrency": self.price_currency,
                        "priceValidUntil": (datetime.now() + timedelta(days=30)).isoformat(),
                        "availability": f"https://schema.org/{self.availability}",
                    },
                ],
            },
            "additionalProperty": [
                {"@type": "PropertyValue", "name": k, "value": v}
                for k, v in (self.attributes or {}).items()
            ],
            "seller": {
                "@type": "LocalBusiness",
                "name": self.merchant_name,
                "identifier": self.merchant_id,
                "areaServed": self.area_served,
            },
        }

    def to_ucp_catalog_entry(self) -> Dict:
        """
        Universal Commerce Protocol catalog entry.
        Used for agent-to-agent commerce.
        """
        return {
            "ucp_version": "1.0",
            "entry_type": "rental_product",
            "product_id": self.id,
            "merchant_id": self.merchant_id,
            "payload": {
                "name": self.name,
                "description": self.description,
                "category": self.category,
                "condition": self.condition,
                "pricing": {
                    "model": "rental",
                    "daily_rate": self.price_daily,
                    "weekly_rate": self.price_weekly,
                    "currency": self.price_currency,
                    "deposit_required": self.price_daily * 2,
                },
                "availability": {
                    "status": self.availability.lower(),
                    "next_available": self.available_from,
                    "booking_lead_time_hours": 2,
                },
                "location": {
                    "pickup_address": self.pickup_location,
                    "service_area": self.area_served,
                    "delivery_available": self.delivery_available,
                    "delivery_fee": 20.0 if self.delivery_available else None,
                },
                "attributes": self.attributes or {},
            },
            "actions": {
                "check_availability": f"/api/v1/products/{self.id}/availability",
                "get_quote": f"/api/v1/products/{self.id}/quote",
                "reserve": f"/api/v1/products/{self.id}/reserve",
                "book": f"/api/v1/products/{self.id}/book",
            },
            "updated_at": datetime.now().isoformat(),
        }


class PricingAgent:
    """
    Autonomous pricing agent that monitors market and adjusts rates.
    """

    def __init__(self, market_rates: Dict = None):
        self.market_rates = market_rates or MARKET_RATES
        self.price_history = []

    def get_optimal_price(
        self,
        category: str,
        demand_level: str = "normal",  # low, normal, high
        competitor_prices: List[float] = None,
    ) -> Dict[str, float]:
        """
        Calculate optimal rental price based on market conditions.
        """
        base = self.market_rates.get(category, {"daily": 30, "weekly": 100})

        # Demand multiplier
        demand_multipliers = {
            "low": 0.85,
            "normal": 1.0,
            "high": 1.25,
        }
        multiplier = demand_multipliers.get(demand_level, 1.0)

        # Competitor adjustment
        if competitor_prices:
            avg_competitor = sum(competitor_prices) / len(competitor_prices)
            # Price 5-10% below average competitor
            competitive_price = avg_competitor * 0.92
            base_adjusted = min(base["daily"] * multiplier, competitive_price)
        else:
            base_adjusted = base["daily"] * multiplier

        daily = round(base_adjusted, 0)
        weekly = round(daily * 3.5, 0)  # ~50% discount for weekly

        return {
            "daily": daily,
            "weekly": weekly,
            "strategy": f"demand_{demand_level}" + ("_competitive" if competitor_prices else ""),
        }

    def analyze_market_position(self, our_price: float, category: str) -> Dict:
        """
        Analyze how our pricing compares to market.
        """
        market = self.market_rates.get(category, {"daily": 30})
        market_daily = market["daily"]

        position = "at_market"
        if our_price < market_daily * 0.9:
            position = "below_market"
        elif our_price > market_daily * 1.1:
            position = "above_market"

        return {
            "our_price": our_price,
            "market_avg": market_daily,
            "position": position,
            "difference_percent": round((our_price - market_daily) / market_daily * 100, 1),
            "recommendation": self._get_pricing_recommendation(position, our_price, market_daily),
        }

    def _get_pricing_recommendation(self, position: str, our: float, market: float) -> str:
        if position == "below_market":
            return f"Consider raising to ${market:.0f} to match market (+${market - our:.0f})"
        elif position == "above_market":
            return f"Price may be limiting bookings. Market is ${market:.0f}"
        return "Price is competitive with market"


class BookingAgent:
    """
    Handles booking requests from other agents or customers.
    """

    def __init__(self):
        self.bookings = []
        self.blocked_dates = {}  # product_id -> list of date ranges

    def check_availability(
        self,
        product_id: str,
        start_date: str,
        end_date: str,
    ) -> Dict:
        """
        Check if product is available for given dates.
        Called by shopping agents.
        """
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        blocked = self.blocked_dates.get(product_id, [])

        for block_start, block_end in blocked:
            if not (end <= block_start or start >= block_end):
                return {
                    "available": False,
                    "product_id": product_id,
                    "requested_dates": {"start": start_date, "end": end_date},
                    "conflict": {"start": block_start.isoformat(), "end": block_end.isoformat()},
                    "next_available": block_end.isoformat(),
                }

        return {
            "available": True,
            "product_id": product_id,
            "requested_dates": {"start": start_date, "end": end_date},
            "hold_until": (datetime.now() + timedelta(hours=2)).isoformat(),
        }

    def get_quote(
        self,
        product_id: str,
        start_date: str,
        end_date: str,
        daily_rate: float,
        weekly_rate: float,
    ) -> Dict:
        """
        Generate a quote for a rental period.
        """
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        days = (end - start).days

        # Calculate best rate
        if days >= 7:
            weeks = days // 7
            remaining_days = days % 7
            total = (weeks * weekly_rate) + (remaining_days * daily_rate)
        else:
            total = days * daily_rate

        deposit = daily_rate * 2

        return {
            "product_id": product_id,
            "rental_period": {
                "start": start_date,
                "end": end_date,
                "days": days,
            },
            "pricing": {
                "subtotal": round(total, 2),
                "deposit": deposit,
                "platform_fee": 0,  # Direct booking
                "total_due_now": round(total + deposit, 2),
                "refundable_deposit": deposit,
            },
            "quote_valid_until": (datetime.now() + timedelta(hours=24)).isoformat(),
            "quote_id": f"Q-{product_id}-{datetime.now().strftime('%Y%m%d%H%M')}",
        }

    def create_reservation(
        self,
        product_id: str,
        quote_id: str,
        renter_info: Dict,
    ) -> Dict:
        """
        Create a reservation (hold before payment).
        """
        reservation = {
            "reservation_id": f"R-{product_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "quote_id": quote_id,
            "product_id": product_id,
            "renter": renter_info,
            "status": "pending_payment",
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=2)).isoformat(),
            "next_action": "complete_payment",
            "payment_url": f"/api/v1/reservations/{product_id}/pay",
        }

        self.bookings.append(reservation)
        return reservation


class AgentCommerceCatalog:
    """
    Main catalog that exposes all products in agent-readable formats.
    """

    def __init__(self, inventory: List[Dict] = None):
        self.inventory = inventory or INVENTORY
        self.pricing_agent = PricingAgent()
        self.booking_agent = BookingAgent()
        self.products: Dict[str, AgentReadableProduct] = {}

        self._load_products()

    def _load_products(self):
        """Load inventory into agent-readable format."""
        for item in self.inventory:
            product = AgentReadableProduct(
                id=item.get("id", ""),
                name=item.get("name", ""),
                description=self._generate_description(item),
                category=item.get("category", ""),
                brand=item.get("brand"),
                condition=item.get("condition", "good"),
                price_daily=item.get("daily_rate", 30),
                price_weekly=item.get("weekly_rate", 100),
                availability="InStock",
                area_served=f"{LOCATION['city']}, {LOCATION['state']}",
                pickup_location=f"{LOCATION['city']}, {LOCATION['state']} {LOCATION['zip']}",
                attributes={
                    "rental_type": "peer_to_peer",
                    "min_rental_period": "1 day",
                    "deposit_required": True,
                    "id_required": True,
                },
            )
            self.products[product.id] = product

    def _generate_description(self, item: Dict) -> str:
        """Generate SEO/GEO optimized description."""
        category = item.get("category", "tool")
        name = item.get("name", "Tool")

        templates = {
            "pressure_washer": f"{name} available for rent in {LOCATION['city']}. Perfect for deck cleaning, driveway washing, and exterior home projects. Professional-grade equipment at affordable daily rates.",
            "carpet_cleaner": f"{name} rental in {LOCATION['city']}. Deep clean carpets and upholstery. Great for move-out cleaning, pet stains, and spring cleaning.",
            "tile_saw": f"{name} for rent. Make precise tile cuts for your bathroom or kitchen renovation. Wet cutting for minimal dust.",
            "generator": f"Portable {name} rental in {LOCATION['city']}. Reliable backup power for outdoor events, job sites, or emergencies.",
        }

        return templates.get(category, f"{name} available for rent in {LOCATION['city']}. Quality equipment at competitive rates.")

    def get_full_catalog_jsonld(self) -> Dict:
        """
        Get full catalog in JSON-LD format.
        This can be embedded in HTML for discovery.
        """
        return {
            "@context": SCHEMA_CONTEXT,
            "@type": "ItemList",
            "name": "Igor's Tool Rentals - Coral Springs",
            "description": "Peer-to-peer tool rentals in Coral Springs, FL",
            "numberOfItems": len(self.products),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "item": product.to_jsonld(),
                }
                for i, product in enumerate(self.products.values())
            ],
        }

    def get_ucp_catalog(self) -> Dict:
        """
        Get catalog in Universal Commerce Protocol format.
        For agent-to-agent discovery.
        """
        return {
            "ucp_version": "1.0",
            "catalog_type": "rental_equipment",
            "merchant": {
                "id": "igor-tools-coral-springs",
                "name": "Igor's Tool Rentals",
                "location": LOCATION,
                "service_area_miles": 15,
            },
            "products": [
                product.to_ucp_catalog_entry()
                for product in self.products.values()
            ],
            "capabilities": {
                "instant_booking": True,
                "quotes": True,
                "availability_check": True,
                "delivery": False,
                "pickup_only": True,
            },
            "endpoints": {
                "catalog": "/api/v1/catalog",
                "search": "/api/v1/search",
                "availability": "/api/v1/availability",
                "quote": "/api/v1/quote",
                "book": "/api/v1/book",
            },
            "updated_at": datetime.now().isoformat(),
        }

    def handle_agent_query(self, query: Dict) -> Dict:
        """
        Handle queries from shopping agents.

        Example query:
        {
            "intent": "find_rental",
            "category": "pressure_washer",
            "location": "Coral Springs, FL",
            "dates": {"start": "2026-02-01", "end": "2026-02-02"},
            "max_price": 50
        }
        """
        intent = query.get("intent", "search")

        if intent == "find_rental":
            return self._handle_find_rental(query)
        elif intent == "check_availability":
            return self._handle_availability(query)
        elif intent == "get_quote":
            return self._handle_quote(query)
        elif intent == "book":
            return self._handle_book(query)
        else:
            return {"error": "Unknown intent", "supported": ["find_rental", "check_availability", "get_quote", "book"]}

    def _handle_find_rental(self, query: Dict) -> Dict:
        """Find matching rentals."""
        category = query.get("category")
        max_price = query.get("max_price", 999)

        matches = []
        for product in self.products.values():
            if category and product.category != category:
                continue
            if product.price_daily > max_price:
                continue
            matches.append(product.to_ucp_catalog_entry())

        return {
            "results": matches,
            "count": len(matches),
            "query": query,
        }

    def _handle_availability(self, query: Dict) -> Dict:
        """Check availability for a product."""
        product_id = query.get("product_id")
        if not product_id or product_id not in self.products:
            return {"error": "Product not found"}

        return self.booking_agent.check_availability(
            product_id,
            query.get("start_date", datetime.now().isoformat()),
            query.get("end_date", (datetime.now() + timedelta(days=1)).isoformat()),
        )

    def _handle_quote(self, query: Dict) -> Dict:
        """Generate a quote."""
        product_id = query.get("product_id")
        if not product_id or product_id not in self.products:
            return {"error": "Product not found"}

        product = self.products[product_id]
        return self.booking_agent.get_quote(
            product_id,
            query.get("start_date"),
            query.get("end_date"),
            product.price_daily,
            product.price_weekly,
        )

    def _handle_book(self, query: Dict) -> Dict:
        """Create a reservation."""
        return self.booking_agent.create_reservation(
            query.get("product_id"),
            query.get("quote_id"),
            query.get("renter_info", {}),
        )


def export_for_web(catalog: AgentCommerceCatalog, output_dir: Path = None):
    """
    Export catalog files for web deployment.
    These files make your listings discoverable by AI agents.
    """
    output_dir = output_dir or Path(__file__).parent / "api"
    output_dir.mkdir(exist_ok=True)

    # JSON-LD for HTML embedding (SEO/GEO)
    jsonld_path = output_dir / "catalog.jsonld"
    with open(jsonld_path, 'w') as f:
        json.dump(catalog.get_full_catalog_jsonld(), f, indent=2)
    print(f"Exported: {jsonld_path}")

    # UCP catalog for agent discovery
    ucp_path = output_dir / "ucp-catalog.json"
    with open(ucp_path, 'w') as f:
        json.dump(catalog.get_ucp_catalog(), f, indent=2)
    print(f"Exported: {ucp_path}")

    # Individual product files
    products_dir = output_dir / "products"
    products_dir.mkdir(exist_ok=True)
    for product_id, product in catalog.products.items():
        product_path = products_dir / f"{product_id}.json"
        with open(product_path, 'w') as f:
            json.dump(product.to_ucp_catalog_entry(), f, indent=2)
    print(f"Exported {len(catalog.products)} product files to {products_dir}")


if __name__ == "__main__":
    print("=" * 60)
    print("AGENTIC COMMERCE LAYER")
    print("=" * 60)

    # Demo with sample inventory
    sample_inventory = [
        {
            "id": "pw-001",
            "name": "Ryobi 2300 PSI Electric Pressure Washer",
            "category": "pressure_washer",
            "brand": "Ryobi",
            "condition": "excellent",
            "daily_rate": 40,
            "weekly_rate": 150,
        },
        {
            "id": "cc-001",
            "name": "Bissell ProHeat Carpet Cleaner",
            "category": "carpet_cleaner",
            "brand": "Bissell",
            "condition": "good",
            "daily_rate": 35,
            "weekly_rate": 120,
        },
    ]

    catalog = AgentCommerceCatalog(sample_inventory)

    # Test agent query
    print("\n📡 Simulating Agent Query...")
    query = {
        "intent": "find_rental",
        "category": "pressure_washer",
        "location": "Coral Springs, FL",
        "max_price": 50,
    }
    result = catalog.handle_agent_query(query)
    print(f"Query: {query}")
    print(f"Results: {result['count']} matches found")

    # Test quote
    print("\n💰 Generating Quote...")
    quote_query = {
        "intent": "get_quote",
        "product_id": "pw-001",
        "start_date": "2026-02-01",
        "end_date": "2026-02-03",
    }
    quote = catalog.handle_agent_query(quote_query)
    print(f"Quote for 2 days: ${quote['pricing']['total_due_now']}")

    # Export files
    print("\n📁 Exporting Agent-Readable Files...")
    export_for_web(catalog)

    # Show JSON-LD sample
    print("\n📋 JSON-LD Sample (for HTML embedding):")
    jsonld = catalog.products["pw-001"].to_jsonld()
    print(json.dumps(jsonld, indent=2)[:500] + "...")

    print("\n" + "=" * 60)
    print("✅ Agentic commerce layer ready!")
    print("   - Listings are now machine-readable")
    print("   - AI shopping agents can discover and book")
    print("   - Pricing agent optimizes rates")
    print("=" * 60)
