#!/usr/bin/env python3
"""
Inventory RAG System - Track all tool rental listings across platforms.

Uses LanceDB (same as RLHF system) for semantic search of inventory.

Usage:
    python inventory_rag.py index          # Index all listings
    python inventory_rag.py search "query" # Search inventory
    python inventory_rag.py expiring 7     # Listings expiring in N days
    python inventory_rag.py stats          # Show inventory stats
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import lancedb
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("Install dependencies: pip install lancedb sentence-transformers")
    sys.exit(1)

# Paths
STORAGE_ROOT = Path(__file__).parent.parent
DATA_DIR = STORAGE_ROOT / "data" / "listings"
DB_PATH = STORAGE_ROOT / "data" / "inventory_lancedb"

# Use same model as RLHF system for consistency
MODEL_NAME = "all-MiniLM-L6-v2"


def load_all_listings():
    """Load all listings from JSON files."""
    listings = []

    for json_file in DATA_DIR.glob("*.json"):
        with open(json_file) as f:
            data = json.load(f)
            platform = data.get("platform", json_file.stem)

            for listing in data.get("listings", []):
                listing["platform"] = platform
                listing["source_file"] = json_file.name
                listings.append(listing)

    return listings


def create_search_text(listing):
    """Create searchable text from listing."""
    parts = [
        listing.get("title", ""),
        listing.get("tool", ""),
        listing.get("model", ""),
        listing.get("location", ""),
        listing.get("platform", ""),
        f"${listing.get('price_daily', 0)}/day",
        listing.get("notes", ""),
    ]
    return " ".join(str(p) for p in parts if p)


def index_inventory():
    """Index all listings into LanceDB."""
    print("Loading sentence transformer model...")
    model = SentenceTransformer(MODEL_NAME)

    print("Loading listings from JSON files...")
    listings = load_all_listings()
    print(f"Found {len(listings)} listings across all platforms")

    # Create embeddings
    print("Creating embeddings...")
    records = []
    for listing in listings:
        text = create_search_text(listing)
        embedding = model.encode(text).tolist()

        records.append({
            "id": listing.get("id", ""),
            "platform": listing.get("platform", ""),
            "title": listing.get("title", ""),
            "tool": listing.get("tool", ""),
            "model": listing.get("model", ""),
            "price_daily": listing.get("price_daily", 0),
            "price_weekly": listing.get("price_weekly", 0),
            "url": listing.get("url", ""),
            "location": listing.get("location", ""),
            "posted_date": listing.get("posted_date", ""),
            "expires_date": listing.get("expires_date", ""),
            "status": listing.get("status", "active"),
            "search_text": text,
            "vector": embedding,
        })

    # Store in LanceDB
    print(f"Storing in LanceDB at {DB_PATH}...")
    db = lancedb.connect(str(DB_PATH))

    # Drop existing table if exists
    try:
        db.drop_table("inventory")
    except:
        pass

    table = db.create_table("inventory", records)
    print(f"Indexed {len(records)} listings")

    return len(records)


def search_inventory(query: str, limit: int = 10):
    """Search inventory using semantic search."""
    model = SentenceTransformer(MODEL_NAME)
    query_embedding = model.encode(query).tolist()

    db = lancedb.connect(str(DB_PATH))
    table = db.open_table("inventory")

    results = table.search(query_embedding).limit(limit).to_list()
    return results


def get_expiring_listings(days: int = 7):
    """Get listings expiring within N days."""
    db = lancedb.connect(str(DB_PATH))
    table = db.open_table("inventory")

    # Get all listings
    all_listings = table.to_pandas()

    cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    expiring = all_listings[
        (all_listings["expires_date"] != "") &
        (all_listings["expires_date"] <= cutoff) &
        (all_listings["expires_date"] >= today)
    ]

    return expiring.to_dict("records")


def get_stats():
    """Get inventory statistics."""
    listings = load_all_listings()

    stats = {
        "total_listings": len(listings),
        "by_platform": {},
        "by_status": {},
        "total_daily_revenue_potential": 0,
        "average_daily_rate": 0,
    }

    for listing in listings:
        platform = listing.get("platform", "unknown")
        status = listing.get("status", "unknown")
        price = listing.get("price_daily", 0)

        stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
        stats["total_daily_revenue_potential"] += price

    if listings:
        stats["average_daily_rate"] = round(
            stats["total_daily_revenue_potential"] / len(listings), 2
        )

    return stats


def print_listing(listing, show_url=True):
    """Pretty print a listing."""
    print(f"  [{listing.get('platform', '?')}] {listing.get('title', 'Untitled')}")
    print(f"    Tool: {listing.get('tool', 'N/A')}")
    print(f"    Price: ${listing.get('price_daily', 0)}/day, ${listing.get('price_weekly', 0)}/week")
    print(f"    Status: {listing.get('status', 'unknown')}")
    if show_url and listing.get('url'):
        print(f"    URL: {listing.get('url')}")
    if listing.get('expires_date'):
        print(f"    Expires: {listing.get('expires_date')}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1]

    if command == "index":
        count = index_inventory()
        print(f"\n✅ Indexed {count} listings into LanceDB")

    elif command == "search":
        if len(sys.argv) < 3:
            print("Usage: python inventory_rag.py search 'query'")
            sys.exit(1)
        query = sys.argv[2]
        print(f"\n🔍 Searching for: {query}\n")
        results = search_inventory(query)
        for r in results:
            print_listing(r)

    elif command == "expiring":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        print(f"\n⏰ Listings expiring within {days} days:\n")
        expiring = get_expiring_listings(days)
        if expiring:
            for listing in expiring:
                print_listing(listing)
        else:
            print("  No listings expiring soon!")

    elif command == "stats":
        stats = get_stats()
        print("\n📊 Inventory Statistics\n")
        print(f"  Total Listings: {stats['total_listings']}")
        print(f"  Average Daily Rate: ${stats['average_daily_rate']}")
        print(f"  Total Daily Revenue Potential: ${stats['total_daily_revenue_potential']}")
        print("\n  By Platform:")
        for platform, count in stats['by_platform'].items():
            print(f"    {platform}: {count}")
        print("\n  By Status:")
        for status, count in stats['by_status'].items():
            print(f"    {status}: {count}")

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
