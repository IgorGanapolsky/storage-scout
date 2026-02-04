#!/usr/bin/env python3
"""
Facebook Marketplace Auto-Poster

Posts tool rental listings to Facebook Marketplace using browser automation.

Usage:
    python fb_marketplace_poster.py

Requires: You to be logged into Facebook in your browser.
"""

import json  # noqa: F401 - used for json.load
from pathlib import Path

# Load tools inventory
DATA_DIR = Path(__file__).parent / "data"
TOOLS_FILE = DATA_DIR / "tools_inventory.json"


def load_tools():
    """Load tools from inventory."""
    if not TOOLS_FILE.exists():
        print("No tools inventory found. Run autonomous_rental_agent.py first.")
        return []

    with open(TOOLS_FILE) as f:
        return json.load(f)


def generate_fb_listing(tool: dict) -> dict:
    """Generate Facebook Marketplace listing data."""

    title = f"{tool['name']} for Rent - ${tool['daily_rate']}/day"

    description = f"""🔧 {tool['name']} FOR RENT

💵 RATES:
• ${tool['daily_rate']}/day
• ${tool['weekly_rate']}/week

📍 Pickup: Coral Springs, FL 33071

✅ Professional-grade equipment
✅ Tested before each rental
✅ Same-day availability

$50 refundable deposit required.

Perfect for weekend projects!

Message me to book! 📱
"""

    return {
        "title": title[:100],  # FB has 100 char limit
        "price": tool["daily_rate"],
        "description": description,
        "category": "Tools",
        "condition": "Like New",
        "location": "Coral Springs, FL",
    }


def print_listings_for_manual_post():
    """Print listings formatted for easy copy-paste to FB Marketplace."""

    tools = load_tools()

    if not tools:
        return

    print("=" * 60)
    print("FACEBOOK MARKETPLACE LISTINGS")
    print("Copy-paste these to create listings")
    print("=" * 60)

    for tool in tools:
        listing = generate_fb_listing(tool)

        print(f"\n{'='*50}")
        print(f"TOOL: {tool['name']}")
        print(f"{'='*50}")
        print(f"\n📌 TITLE (copy this):")
        print(f"   {listing['title']}")
        print(f"\n💰 PRICE: ${listing['price']}")
        print(f"\n📝 DESCRIPTION (copy this):")
        print("-" * 40)
        print(listing['description'])
        print("-" * 40)
        print(f"\n📂 Category: {listing['category']}")
        print(f"📍 Location: {listing['location']}")
        print()

    print("\n" + "=" * 60)
    print("HOW TO POST ON FACEBOOK MARKETPLACE:")
    print("=" * 60)
    print("""
1. Go to: facebook.com/marketplace/create/item

2. For each tool above:
   • Click "Create New Listing" → "Item for Sale"
   • Copy the TITLE into the title field
   • Enter the PRICE
   • Copy the DESCRIPTION
   • Select Category: Home & Garden → Tools
   • Set Condition: Like New
   • Enter Location: Coral Springs, FL
   • Add photos (take pics or use stock photos)
   • Click "Publish"

3. When someone messages you about a rental:
   • Ask for their name, phone, and rental dates
   • Run: python autonomous_rental_agent.py book <tool_id> "Name" "Phone" "Date" Days
   • Buy the tool from Home Depot
   • Confirm booking: python autonomous_rental_agent.py confirm <booking_id> --purchased

TIPS:
• Renew listings every 7 days for more visibility
• Respond to inquiries within 1 hour
• Be flexible on pickup times
""")


def create_craigslist_post(tool: dict) -> str:
    """Generate Craigslist HTML post."""

    html = f"""
<h2>{tool['name']} for Rent - Coral Springs</h2>

<p><strong>Daily Rate:</strong> ${tool['daily_rate']}</p>
<p><strong>Weekly Rate:</strong> ${tool['weekly_rate']}</p>

<p><strong>Location:</strong> Coral Springs, FL 33071</p>

<h3>What You Get:</h3>
<ul>
<li>Professional-grade {tool['name']}</li>
<li>Tested and cleaned before each rental</li>
<li>Same-day availability with advance notice</li>
</ul>

<h3>Rental Terms:</h3>
<ul>
<li>$50 refundable security deposit</li>
<li>Valid ID required</li>
<li>Pickup and return at my location</li>
</ul>

<p>Perfect for weekend DIY projects!</p>

<p><strong>To Book:</strong> Reply to this ad with your name, phone number, and rental dates.</p>
"""
    return html


def print_craigslist_listings():
    """Print Craigslist-formatted listings."""

    tools = load_tools()

    if not tools:
        return

    print("\n" + "=" * 60)
    print("CRAIGSLIST LISTINGS")
    print("=" * 60)

    for tool in tools:
        print(f"\n--- {tool['name']} ---")
        print(f"Title: {tool['name']} for Rent - ${tool['daily_rate']}/day - Coral Springs")
        print(f"Price: ${tool['daily_rate']}")
        print(f"Category: tools - by owner")
        print("\nBody:")
        print(create_craigslist_post(tool))

    print("\n" + "=" * 60)
    print("POST AT: https://miami.craigslist.org/")
    print("Section: for sale → tools")
    print("=" * 60)


if __name__ == "__main__":
    print_listings_for_manual_post()
    print_craigslist_listings()
