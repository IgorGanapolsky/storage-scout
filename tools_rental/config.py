#!/usr/bin/env python3
"""
Tools Rental Arbitrage - Configuration
"""

# Your inventory - add tools as you acquire them
INVENTORY = [
    # {
    #     "id": "pw-001",
    #     "name": "Ryobi 2300 PSI Pressure Washer",
    #     "category": "pressure_washer",
    #     "buy_price": 89.00,
    #     "daily_rate": 40.00,
    #     "weekly_rate": 150.00,
    #     "condition": "excellent",
    #     "platforms": ["2quip", "rentmytool"],
    # },
]

# Rental platforms
PLATFORMS = {
    "2quip": {
        "name": "2Quip / RentMyEquipment",
        "url": "https://www.rentmyequipment.com/",
        "fee_percent": 15,
        "coverage": "nationwide",
    },
    "rentmytool": {
        "name": "RentMyTool",
        "url": "https://rentmytool.app/",
        "fee_percent": 12,
        "coverage": "local",
    },
    "choretools": {
        "name": "CHORE TOOLS",
        "url": "https://play.google.com/store/apps/details?id=com.choretools.app",
        "fee_percent": 10,
        "coverage": "nationwide",
    },
    "friendwitha": {
        "name": "FriendWithA",
        "url": "https://friendwitha.com/",
        "fee_percent": 8,
        "coverage": "community",
    },
}

# Home Depot clearance categories to monitor
HD_CLEARANCE_CATEGORIES = [
    "power-tools",
    "outdoor-power-equipment",
    "pressure-washers",
    "generators",
    "air-compressors",
    "tile-saws",
    "carpet-cleaners",
]

# Competitor rental rates (for pricing guidance)
MARKET_RATES = {
    "pressure_washer": {"daily": 40, "weekly": 150},
    "carpet_cleaner": {"daily": 35, "weekly": 120},
    "tile_saw": {"daily": 50, "weekly": 180},
    "generator": {"daily": 60, "weekly": 220},
    "drill_set": {"daily": 15, "weekly": 50},
    "circular_saw": {"daily": 20, "weekly": 70},
    "reciprocating_saw": {"daily": 25, "weekly": 85},
    "air_compressor": {"daily": 35, "weekly": 120},
    "nail_gun": {"daily": 30, "weekly": 100},
    "sander": {"daily": 20, "weekly": 70},
}

# Notification settings
NTFY_TOPIC = "igor_tools_alerts"
TELEGRAM_BOT_TOKEN = ""  # Add your bot token
TELEGRAM_CHAT_ID = ""    # Add your chat ID

# Location
LOCATION = {
    "city": "Coral Springs",
    "state": "FL",
    "zip": "33071",
}
