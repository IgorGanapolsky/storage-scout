#!/usr/bin/env python3
"""
SAGE-Inspired Feedback Loop for Tool Rental Arbitrage

Based on Google's SAGE research (Steerable Agentic Data Generation for Deep Search
with Execution Feedback), this module tracks which listings get inquiries and feeds
conversion data back to the market scanner to improve targeting.

Key SAGE principles applied:
1. Execution feedback - Track what actually converts, not just what seems good
2. When to search again - Only deep-search when initial results look promising
3. When to stop - Don't waste API credits on low-probability listings
4. Reason across sources - Combine platform, timing, and pricing signals

Usage:
    # Record an inquiry
    python sage_feedback_loop.py inquiry <listing_id> <platform> <inquiry_type>

    # Record a conversion (booking)
    python sage_feedback_loop.py conversion <listing_id> <platform> <revenue>

    # Get high-conversion insights
    python sage_feedback_loop.py insights

    # Retrain market scanner weights
    python sage_feedback_loop.py retrain
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional
from collections import defaultdict

# Paths
STORAGE_ROOT = Path(__file__).parent.parent
DATA_DIR = STORAGE_ROOT / "data" / "sage_feedback"
WEIGHTS_FILE = DATA_DIR / "scanner_weights.json"
EVENTS_FILE = DATA_DIR / "conversion_events.jsonl"

DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ConversionEvent:
    """A single event in the conversion funnel."""
    event_type: str  # "listing_created", "inquiry", "message", "booking", "completed", "cancelled"
    listing_id: str
    platform: str  # "facebook", "craigslist", "2quip", "neighbor", "nextdoor"
    timestamp: str

    # Listing context
    tool_category: str = ""
    asking_price: float = 0.0
    source_price: float = 0.0

    # Inquiry details (if applicable)
    inquiry_type: str = ""  # "price_question", "availability", "location", "booking_request"
    response_time_minutes: int = 0

    # Conversion details (if applicable)
    revenue: float = 0.0
    rental_days: int = 0
    profit: float = 0.0

    # SAGE signals
    search_confidence: float = 0.0  # How confident was the scanner about this listing?
    did_deep_search: bool = False  # Did we do additional research?

    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class SAGEFeedbackLoop:
    """
    Tracks conversion funnel and feeds insights back to market scanner.

    Implements SAGE's key insight: agents should learn "when to search again,
    when to stop, and how to reason across sources."
    """

    def __init__(self):
        self.events: List[ConversionEvent] = []
        self.weights = self._load_weights()
        self._load_events()

    def _load_weights(self) -> Dict:
        """Load market scanner weights."""
        default_weights = {
            # Platform weights (which platforms convert best?)
            "platform_weights": {
                "facebook": 1.0,
                "craigslist": 1.0,
                "2quip": 1.0,
                "neighbor": 1.0,
                "nextdoor": 1.0,
            },
            # Category weights (which tool categories convert?)
            "category_weights": {
                "pressure_washer": 1.0,
                "tile_saw": 1.0,
                "carpet_cleaner": 1.0,
                "air_compressor": 1.0,
                "circular_saw": 1.0,
            },
            # Price sensitivity (optimal price points)
            "price_multipliers": {
                "under_30": 1.0,  # <$30/day
                "30_to_50": 1.0,  # $30-50/day
                "over_50": 1.0,  # >$50/day
            },
            # Timing weights (day of week)
            "timing_weights": {
                "monday": 1.0,
                "tuesday": 1.0,
                "wednesday": 1.0,
                "thursday": 1.0,
                "friday": 1.0,
                "saturday": 1.0,
                "sunday": 1.0,
            },
            # SAGE search strategy
            "deep_search_threshold": 0.6,  # Confidence needed to skip deep search
            "stop_search_threshold": 0.3,   # Below this, don't bother listing

            # Stats
            "total_inquiries": 0,
            "total_conversions": 0,
            "total_revenue": 0.0,
            "last_updated": datetime.now().isoformat(),
        }

        if WEIGHTS_FILE.exists():
            with open(WEIGHTS_FILE) as f:
                saved = json.load(f)
                default_weights.update(saved)

        return default_weights

    def _save_weights(self):
        """Save updated weights."""
        self.weights["last_updated"] = datetime.now().isoformat()
        with open(WEIGHTS_FILE, "w") as f:
            json.dump(self.weights, f, indent=2)

    def _load_events(self):
        """Load conversion events from JSONL."""
        if EVENTS_FILE.exists():
            with open(EVENTS_FILE) as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self.events.append(ConversionEvent(**data))

    def _save_event(self, event: ConversionEvent):
        """Append event to JSONL."""
        with open(EVENTS_FILE, "a") as f:
            f.write(json.dumps(asdict(event)) + "\n")
        self.events.append(event)

    def record_inquiry(
        self,
        listing_id: str,
        platform: str,
        inquiry_type: str,
        tool_category: str = "",
        asking_price: float = 0.0,
        response_time_minutes: int = 0,
    ) -> ConversionEvent:
        """Record an inquiry on a listing."""
        event = ConversionEvent(
            event_type="inquiry",
            listing_id=listing_id,
            platform=platform,
            timestamp=datetime.now().isoformat(),
            tool_category=tool_category,
            asking_price=asking_price,
            inquiry_type=inquiry_type,
            response_time_minutes=response_time_minutes,
        )
        self._save_event(event)
        self.weights["total_inquiries"] += 1
        self._save_weights()

        print(f"Recorded inquiry: {listing_id} on {platform} ({inquiry_type})")
        return event

    def record_conversion(
        self,
        listing_id: str,
        platform: str,
        revenue: float,
        rental_days: int,
        source_price: float = 0.0,
        tool_category: str = "",
    ) -> ConversionEvent:
        """Record a successful conversion (booking)."""
        profit = revenue - source_price

        event = ConversionEvent(
            event_type="booking",
            listing_id=listing_id,
            platform=platform,
            timestamp=datetime.now().isoformat(),
            tool_category=tool_category,
            revenue=revenue,
            rental_days=rental_days,
            source_price=source_price,
            profit=profit,
        )
        self._save_event(event)

        self.weights["total_conversions"] += 1
        self.weights["total_revenue"] += revenue
        self._save_weights()

        # Immediately boost weights for this platform/category
        self._boost_weights(platform, tool_category, revenue)

        print(f"CONVERSION! {listing_id} on {platform}: ${revenue} revenue, ${profit} profit")
        return event

    def _boost_weights(self, platform: str, category: str, revenue: float):
        """Boost weights for successful conversions (Thompson Sampling style)."""
        boost_factor = 1.1 + (revenue / 100)  # Higher revenue = bigger boost

        if platform in self.weights["platform_weights"]:
            self.weights["platform_weights"][platform] *= boost_factor

        if category in self.weights["category_weights"]:
            self.weights["category_weights"][category] *= boost_factor

        # Normalize weights to prevent explosion
        self._normalize_weights()
        self._save_weights()

    def _normalize_weights(self):
        """Keep weights in reasonable range."""
        for weight_group in ["platform_weights", "category_weights", "price_multipliers", "timing_weights"]:
            weights = self.weights[weight_group]
            max_weight = max(weights.values())
            if max_weight > 3.0:
                for key in weights:
                    weights[key] /= max_weight

    def get_listing_score(
        self,
        platform: str,
        category: str,
        daily_price: float,
    ) -> Dict:
        """
        Calculate a listing's conversion probability score.

        Used by market scanner to decide:
        - Should we list this? (score > stop_threshold)
        - Should we do deep research? (score < deep_search_threshold)
        """
        score = 1.0

        # Platform weight
        platform_weight = self.weights["platform_weights"].get(platform, 1.0)
        score *= platform_weight

        # Category weight
        category_weight = self.weights["category_weights"].get(category, 1.0)
        score *= category_weight

        # Price weight
        if daily_price < 30:
            price_key = "under_30"
        elif daily_price <= 50:
            price_key = "30_to_50"
        else:
            price_key = "over_50"
        score *= self.weights["price_multipliers"].get(price_key, 1.0)

        # Day of week
        day = datetime.now().strftime("%A").lower()
        score *= self.weights["timing_weights"].get(day, 1.0)

        # Normalize to 0-1 range
        normalized_score = min(1.0, score / 3.0)

        return {
            "score": normalized_score,
            "should_list": normalized_score > self.weights["stop_search_threshold"],
            "needs_deep_search": normalized_score < self.weights["deep_search_threshold"],
            "breakdown": {
                "platform": platform_weight,
                "category": category_weight,
                "price": self.weights["price_multipliers"].get(price_key, 1.0),
                "timing": self.weights["timing_weights"].get(day, 1.0),
            }
        }

    def get_insights(self) -> Dict:
        """
        Analyze conversion data and return actionable insights.

        This is the SAGE "reason across sources" capability.
        """
        if not self.events:
            return {"status": "no_data", "message": "No conversion events recorded yet."}

        # Aggregate by platform
        platform_stats = defaultdict(lambda: {"inquiries": 0, "conversions": 0, "revenue": 0.0})
        for event in self.events:
            if event.event_type == "inquiry":
                platform_stats[event.platform]["inquiries"] += 1
            elif event.event_type == "booking":
                platform_stats[event.platform]["conversions"] += 1
                platform_stats[event.platform]["revenue"] += event.revenue

        # Calculate conversion rates
        platform_performance = []
        for platform, stats in platform_stats.items():
            conv_rate = stats["conversions"] / max(1, stats["inquiries"])
            platform_performance.append({
                "platform": platform,
                "inquiries": stats["inquiries"],
                "conversions": stats["conversions"],
                "revenue": stats["revenue"],
                "conversion_rate": conv_rate,
                "recommendation": "FOCUS" if conv_rate > 0.1 else "REDUCE" if conv_rate < 0.02 else "MAINTAIN"
            })

        # Sort by conversion rate
        platform_performance.sort(key=lambda x: x["conversion_rate"], reverse=True)

        # Category analysis
        category_stats = defaultdict(lambda: {"inquiries": 0, "conversions": 0, "revenue": 0.0})
        for event in self.events:
            if event.tool_category:
                if event.event_type == "inquiry":
                    category_stats[event.tool_category]["inquiries"] += 1
                elif event.event_type == "booking":
                    category_stats[event.tool_category]["conversions"] += 1
                    category_stats[event.tool_category]["revenue"] += event.revenue

        # Response time analysis
        response_times = [e.response_time_minutes for e in self.events if e.response_time_minutes > 0]
        avg_response_time = sum(response_times) / max(1, len(response_times))

        return {
            "summary": {
                "total_inquiries": self.weights["total_inquiries"],
                "total_conversions": self.weights["total_conversions"],
                "total_revenue": self.weights["total_revenue"],
                "overall_conversion_rate": self.weights["total_conversions"] / max(1, self.weights["total_inquiries"]),
            },
            "platform_performance": platform_performance,
            "category_performance": dict(category_stats),
            "response_time_avg_minutes": avg_response_time,
            "recommendations": self._generate_recommendations(platform_performance),
        }

    def _generate_recommendations(self, platform_performance: List[Dict]) -> List[str]:
        """Generate actionable recommendations from data."""
        recommendations = []

        # Platform recommendations
        if platform_performance:
            best = platform_performance[0]
            if best["conversion_rate"] > 0.1:
                recommendations.append(
                    f"DOUBLE DOWN on {best['platform']}: {best['conversion_rate']:.0%} conversion rate"
                )

            for p in platform_performance:
                if p["conversion_rate"] < 0.02 and p["inquiries"] > 5:
                    recommendations.append(
                        f"REDUCE effort on {p['platform']}: only {p['conversion_rate']:.1%} converting"
                    )

        # Price recommendations (from weights)
        price_weights = self.weights["price_multipliers"]
        if price_weights["under_30"] > price_weights["over_50"] * 1.5:
            recommendations.append("LOWER PRICES: Sub-$30/day listings convert significantly better")
        elif price_weights["over_50"] > price_weights["under_30"] * 1.5:
            recommendations.append("PREMIUM OK: Higher-priced listings are converting well")

        # Response time
        if self.events:
            converted = [e for e in self.events if e.event_type == "booking"]
            if converted:
                avg_response = sum(e.response_time_minutes for e in converted) / len(converted)
                if avg_response < 30:
                    recommendations.append(f"FAST RESPONSE WORKS: Average {avg_response:.0f}min response for conversions")

        if not recommendations:
            recommendations.append("NEED MORE DATA: Keep tracking inquiries and conversions")

        return recommendations

    def retrain_weights(self):
        """
        Retrain market scanner weights from conversion data.

        Uses Bayesian updating similar to Thompson Sampling.
        """
        if len(self.events) < 10:
            print("Need at least 10 events to retrain. Current:", len(self.events))
            return

        # Reset to base weights
        for weight_group in ["platform_weights", "category_weights"]:
            for key in self.weights[weight_group]:
                self.weights[weight_group][key] = 1.0

        # Replay all conversion events
        for event in self.events:
            if event.event_type == "booking":
                boost = 1.05 + (event.revenue / 200)

                if event.platform in self.weights["platform_weights"]:
                    self.weights["platform_weights"][event.platform] *= boost

                if event.tool_category in self.weights["category_weights"]:
                    self.weights["category_weights"][event.tool_category] *= boost

        # Normalize
        self._normalize_weights()
        self._save_weights()

        print("Retrained weights from", len(self.events), "events")
        print("Platform weights:", json.dumps(self.weights["platform_weights"], indent=2))
        print("Category weights:", json.dumps(self.weights["category_weights"], indent=2))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCurrent stats:")
        loop = SAGEFeedbackLoop()
        insights = loop.get_insights()
        print(json.dumps(insights["summary"], indent=2))
        return

    command = sys.argv[1]
    loop = SAGEFeedbackLoop()

    if command == "inquiry":
        if len(sys.argv) < 5:
            print("Usage: sage_feedback_loop.py inquiry <listing_id> <platform> <inquiry_type>")
            return
        loop.record_inquiry(
            listing_id=sys.argv[2],
            platform=sys.argv[3],
            inquiry_type=sys.argv[4],
        )

    elif command == "conversion":
        if len(sys.argv) < 5:
            print("Usage: sage_feedback_loop.py conversion <listing_id> <platform> <revenue>")
            return
        loop.record_conversion(
            listing_id=sys.argv[2],
            platform=sys.argv[3],
            revenue=float(sys.argv[4]),
            rental_days=3,  # Default
        )

    elif command == "insights":
        insights = loop.get_insights()
        print(json.dumps(insights, indent=2))

    elif command == "retrain":
        loop.retrain_weights()

    elif command == "score":
        if len(sys.argv) < 5:
            print("Usage: sage_feedback_loop.py score <platform> <category> <daily_price>")
            return
        score = loop.get_listing_score(
            platform=sys.argv[2],
            category=sys.argv[3],
            daily_price=float(sys.argv[4]),
        )
        print(json.dumps(score, indent=2))

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
