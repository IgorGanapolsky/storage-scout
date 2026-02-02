#!/usr/bin/env python3
"""
AI-Powered Listing Generator for Tool Rentals

Generates professional rental listings for peer-to-peer platforms.
Uses templates optimized for conversion.
"""

from typing import Dict, List, Optional
from config import MARKET_RATES, LOCATION


def generate_listing(
    tool_name: str,
    category: str,
    condition: str = "excellent",
    features: Optional[List[str]] = None,
    daily_rate: Optional[float] = None,
    weekly_rate: Optional[float] = None,
) -> Dict[str, str]:
    """
    Generate a complete rental listing with title, description, and pricing.

    Returns dict with: title, description, short_description, tags
    """

    # Get market rate if not specified
    if daily_rate is None:
        daily_rate = MARKET_RATES.get(category, {}).get("daily", 30)
    if weekly_rate is None:
        weekly_rate = MARKET_RATES.get(category, {}).get("weekly", daily_rate * 4)

    # Default features by category
    default_features = {
        "pressure_washer": [
            "Powerful cleaning for decks, driveways, siding",
            "Easy to transport and set up",
            "Includes spray tips for different applications",
            "Perfect for home projects or small business use",
        ],
        "carpet_cleaner": [
            "Deep cleans carpets and upholstery",
            "Removes tough stains and odors",
            "Easy to use - just fill and go",
            "Great for move-out cleaning or pet stains",
        ],
        "tile_saw": [
            "Clean, precise cuts on tile and stone",
            "Wet cutting reduces dust",
            "Adjustable for angled cuts",
            "Perfect for bathroom/kitchen renovations",
        ],
        "generator": [
            "Reliable backup power",
            "Multiple outlets for various devices",
            "Fuel-efficient operation",
            "Great for outdoor events or emergencies",
        ],
        "drill_set": [
            "Cordless convenience with long battery life",
            "Multiple bits included",
            "Perfect for hanging shelves, assembling furniture",
            "Lightweight and easy to handle",
        ],
    }

    features = features or default_features.get(category, [
        "Well-maintained and reliable",
        "Easy to use",
        "Perfect for DIY projects",
    ])

    # Generate title
    condition_text = {
        "excellent": "Like-New",
        "good": "Great Condition",
        "fair": "Working",
    }.get(condition, "")

    title = f"{condition_text} {tool_name} for Rent - {LOCATION['city']}"

    # Generate description
    description = f"""# {tool_name} Available for Rent

Located in {LOCATION['city']}, {LOCATION['state']} ({LOCATION['zip']})

## What You Get
{chr(10).join(f"✓ {f}" for f in features)}

## Rental Rates
- **Daily:** ${daily_rate:.0f}
- **Weekly:** ${weekly_rate:.0f} (save ${(daily_rate * 7 - weekly_rate):.0f}!)

## Rental Terms
- Pickup/dropoff in {LOCATION['city']} area
- Valid ID required
- Security deposit may apply for first-time renters
- Fuel/consumables not included (if applicable)

## Condition
This {tool_name.lower()} is in {condition} condition and has been tested before listing. You'll receive a quick demonstration at pickup if needed.

## Availability
Check the calendar for current availability. Same-day rentals possible with advance notice!

---
*Rent with confidence - I take pride in maintaining my equipment.*
"""

    # Short description for previews
    short_description = f"{condition_text} {tool_name} in {LOCATION['city']}. ${daily_rate:.0f}/day or ${weekly_rate:.0f}/week. Pickup available. {features[0]}"

    # Tags for searchability
    category_tags = {
        "pressure_washer": ["pressure washer", "power washer", "cleaning", "outdoor", "deck cleaning", "driveway"],
        "carpet_cleaner": ["carpet cleaner", "rug cleaner", "upholstery", "deep clean", "stain remover"],
        "tile_saw": ["tile saw", "wet saw", "tile cutter", "renovation", "bathroom", "kitchen"],
        "generator": ["generator", "portable power", "backup power", "outdoor", "camping", "emergency"],
        "drill_set": ["drill", "cordless drill", "power drill", "driver", "home improvement"],
    }

    tags = category_tags.get(category, ["tool", "rental", "equipment"])
    tags.extend([LOCATION['city'].lower(), LOCATION['state'].lower()])

    return {
        "title": title,
        "description": description,
        "short_description": short_description[:200],
        "tags": tags,
        "daily_rate": daily_rate,
        "weekly_rate": weekly_rate,
        "location": f"{LOCATION['city']}, {LOCATION['state']}",
    }


def generate_response_templates() -> Dict[str, str]:
    """
    Generate automated response templates for common inquiries.
    """
    return {
        "inquiry": f"""Hi! Thanks for your interest in renting.

Yes, this is available! Here's how it works:
1. Let me know what dates you need
2. We'll arrange pickup/dropoff in {LOCATION['city']}
3. Bring valid ID and we're good to go

When were you thinking of renting?""",

        "booking_confirmed": """Great, you're all set!

📅 Rental: {dates}
💰 Total: ${total}
📍 Pickup: {pickup_location}

I'll send you the exact address the day before. See you then!""",

        "reminder": """Just a reminder - your rental pickup is tomorrow!

📍 Address: {address}
⏰ Time: {time}
📱 Text me when you're on the way: {phone}

See you soon!""",

        "return_reminder": """Hi! Just a reminder that your rental is due back today.

📍 Dropoff: {address}
⏰ By: {time}

Thanks for renting! Hope it worked out well.""",

        "review_request": """Thanks for renting! Hope the {tool_name} worked out great.

If you have a moment, a quick review would really help others find quality equipment.

Thanks again and let me know if you need anything in the future!""",
    }


def calculate_roi(buy_price: float, daily_rate: float, rentals_per_month: int = 4) -> Dict:
    """
    Calculate ROI metrics for a rental tool.
    """
    monthly_gross = daily_rate * rentals_per_month
    avg_platform_fee = 0.12  # 12% average
    monthly_net = monthly_gross * (1 - avg_platform_fee)

    payback_days = (buy_price / (monthly_net / 30))
    annual_roi = (monthly_net * 12 - buy_price) / buy_price * 100

    return {
        "buy_price": buy_price,
        "daily_rate": daily_rate,
        "monthly_gross": monthly_gross,
        "monthly_net": monthly_net,
        "payback_days": round(payback_days),
        "annual_roi_percent": round(annual_roi, 1),
        "break_even_rentals": round(buy_price / (daily_rate * (1 - avg_platform_fee))),
    }


if __name__ == "__main__":
    # Example: Generate listing for a pressure washer
    print("=" * 60)
    print("TOOL LISTING GENERATOR")
    print("=" * 60)

    listing = generate_listing(
        tool_name="Ryobi 2300 PSI Electric Pressure Washer",
        category="pressure_washer",
        condition="excellent",
    )

    print(f"\n📝 TITLE:\n{listing['title']}")
    print(f"\n📄 DESCRIPTION:\n{listing['description']}")
    print(f"\n🏷️ TAGS: {', '.join(listing['tags'])}")

    print("\n" + "=" * 60)
    print("ROI ANALYSIS")
    print("=" * 60)

    roi = calculate_roi(buy_price=89, daily_rate=40, rentals_per_month=4)
    print(f"""
Buy Price: ${roi['buy_price']}
Daily Rate: ${roi['daily_rate']}
Monthly Gross: ${roi['monthly_gross']}
Monthly Net (after fees): ${roi['monthly_net']:.2f}
Payback: {roi['payback_days']} days
Annual ROI: {roi['annual_roi_percent']}%
Break-even: {roi['break_even_rentals']} rentals
""")

    print("\n" + "=" * 60)
    print("RESPONSE TEMPLATES")
    print("=" * 60)

    templates = generate_response_templates()
    print(f"\n📨 INQUIRY RESPONSE:\n{templates['inquiry']}")
