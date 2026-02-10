#!/usr/bin/env python3
"""
Tool Inventory Tracker

Tracks your rental tool inventory, calculates ROI, and manages availability.
Syncs data to GitHub CSV for dashboard visualization.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from config import PLATFORMS


@dataclass
class Tool:
    """Represents a rental tool in inventory."""
    id: str
    name: str
    category: str
    buy_price: float
    buy_date: str
    daily_rate: float
    weekly_rate: float
    condition: str
    platforms: List[str]
    total_rentals: int = 0
    total_revenue: float = 0.0
    last_rental_date: Optional[str] = None
    notes: str = ""

    @property
    def monthly_avg_revenue(self) -> float:
        """Calculate average monthly revenue."""
        if not self.buy_date:
            return 0
        buy = datetime.fromisoformat(self.buy_date)
        months = max(1, (datetime.now() - buy).days / 30)
        return self.total_revenue / months

    @property
    def roi_percent(self) -> float:
        """Calculate ROI percentage."""
        if self.buy_price <= 0:
            return 0
        return ((self.total_revenue - self.buy_price) / self.buy_price) * 100

    @property
    def payback_status(self) -> str:
        """Check if tool has paid for itself."""
        if self.total_revenue >= self.buy_price:
            return f"PAID ({self.roi_percent:.0f}% ROI)"
        remaining = self.buy_price - self.total_revenue
        return f"${remaining:.0f} to break-even"


@dataclass
class Rental:
    """Represents a single rental transaction."""
    tool_id: str
    start_date: str
    end_date: str
    platform: str
    gross_amount: float
    platform_fee: float
    net_amount: float
    renter_name: str = ""
    notes: str = ""

    @classmethod
    def create(cls, tool_id: str, start: str, end: str, platform: str,
               gross: float, renter: str = "") -> "Rental":
        """Create rental with auto-calculated fees."""
        fee_percent = PLATFORMS.get(platform, {}).get("fee_percent", 15) / 100
        fee = gross * fee_percent
        return cls(
            tool_id=tool_id,
            start_date=start,
            end_date=end,
            platform=platform,
            gross_amount=gross,
            platform_fee=fee,
            net_amount=gross - fee,
            renter_name=renter,
        )


class InventoryManager:
    """Manages tool inventory and rental tracking."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(__file__).parent / "data"
        self.data_dir.mkdir(exist_ok=True)

        self.tools_file = self.data_dir / "tools.json"
        self.rentals_file = self.data_dir / "rentals.json"
        self.csv_file = self.data_dir / "tools_summary.csv"

        self.tools: Dict[str, Tool] = {}
        self.rentals: List[Rental] = []

        self._load()

    def _load(self):
        """Load data from files."""
        if self.tools_file.exists():
            with open(self.tools_file) as f:
                data = json.load(f)
                self.tools = {t['id']: Tool(**t) for t in data}

        if self.rentals_file.exists():
            with open(self.rentals_file) as f:
                data = json.load(f)
                self.rentals = [Rental(**r) for r in data]

    def _save(self):
        """Save data to files."""
        with open(self.tools_file, 'w') as f:
            json.dump([asdict(t) for t in self.tools.values()], f, indent=2)

        with open(self.rentals_file, 'w') as f:
            json.dump([asdict(r) for r in self.rentals], f, indent=2)

        self._export_csv()

    def _export_csv(self):
        """Export summary to CSV for dashboard."""
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'id', 'name', 'category', 'buy_price', 'daily_rate',
                'total_rentals', 'total_revenue', 'monthly_avg', 'roi_percent',
                'payback_status', 'condition'
            ])
            for tool in self.tools.values():
                writer.writerow([
                    tool.id, tool.name, tool.category, tool.buy_price,
                    tool.daily_rate, tool.total_rentals, tool.total_revenue,
                    f"{tool.monthly_avg_revenue:.2f}", f"{tool.roi_percent:.1f}",
                    tool.payback_status, tool.condition
                ])

    def add_tool(self, tool: Tool) -> Tool:
        """Add a new tool to inventory."""
        self.tools[tool.id] = tool
        self._save()
        print(f"Added tool: {tool.name} (${tool.buy_price})")
        return tool

    def record_rental(self, rental: Rental) -> Rental:
        """Record a completed rental."""
        self.rentals.append(rental)

        # Update tool stats
        if rental.tool_id in self.tools:
            tool = self.tools[rental.tool_id]
            tool.total_rentals += 1
            tool.total_revenue += rental.net_amount
            tool.last_rental_date = rental.end_date

        self._save()
        print(f"Recorded rental: {rental.tool_id} - ${rental.net_amount:.2f} net")
        return rental

    def get_summary(self) -> Dict:
        """Get portfolio summary."""
        total_invested = sum(t.buy_price for t in self.tools.values())
        total_revenue = sum(t.total_revenue for t in self.tools.values())
        total_rentals = sum(t.total_rentals for t in self.tools.values())

        return {
            "total_tools": len(self.tools),
            "total_invested": total_invested,
            "total_revenue": total_revenue,
            "total_rentals": total_rentals,
            "net_profit": total_revenue - total_invested,
            "overall_roi": ((total_revenue - total_invested) / total_invested * 100)
                          if total_invested > 0 else 0,
            "avg_monthly_revenue": sum(t.monthly_avg_revenue for t in self.tools.values()),
        }

    def get_recommendations(self) -> List[str]:
        """Get actionable recommendations."""
        recs = []

        summary = self.get_summary()

        # No tools yet
        if summary['total_tools'] == 0:
            recs.append("Start by adding your first tool! Pressure washers have best ROI.")
            return recs

        # Underperforming tools
        for tool in self.tools.values():
            if tool.total_rentals == 0 and tool.buy_date:
                buy = datetime.fromisoformat(tool.buy_date)
                days = (datetime.now() - buy).days
                if days > 14:
                    recs.append(f"'{tool.name}' has 0 rentals in {days} days. "
                               f"Consider lowering price or adding to more platforms.")

            elif tool.monthly_avg_revenue < tool.buy_price * 0.15:
                recs.append(f"'{tool.name}' earning ${tool.monthly_avg_revenue:.0f}/mo. "
                           f"Target: ${tool.buy_price * 0.25:.0f}/mo for 4-month payback.")

        # Good performers
        best = max(self.tools.values(), key=lambda t: t.roi_percent, default=None)
        if best and best.roi_percent > 50:
            recs.append(f"'{best.name}' is your best performer ({best.roi_percent:.0f}% ROI). "
                       f"Consider adding another {best.category}.")

        # Portfolio diversity
        categories = set(t.category for t in self.tools.values())
        if len(categories) < 3 and len(self.tools) >= 3:
            recs.append("Consider diversifying - add a tool from a different category.")

        return recs


def print_dashboard(manager: InventoryManager):
    """Print a nice dashboard summary."""
    print("=" * 60)
    print("TOOL RENTAL PORTFOLIO")
    print("=" * 60)

    summary = manager.get_summary()

    print(f"""
📊 SUMMARY
  Tools: {summary['total_tools']}
  Invested: ${summary['total_invested']:.2f}
  Revenue: ${summary['total_revenue']:.2f}
  Rentals: {summary['total_rentals']}
  Net Profit: ${summary['net_profit']:.2f}
  ROI: {summary['overall_roi']:.1f}%
  Avg Monthly: ${summary['avg_monthly_revenue']:.2f}
""")

    if manager.tools:
        print("-" * 60)
        print("INVENTORY")
        print("-" * 60)
        for tool in manager.tools.values():
            print(f"""
  {tool.name}
    Buy: ${tool.buy_price} | Rate: ${tool.daily_rate}/day
    Rentals: {tool.total_rentals} | Revenue: ${tool.total_revenue:.2f}
    Status: {tool.payback_status}
""")

    recs = manager.get_recommendations()
    if recs:
        print("-" * 60)
        print("RECOMMENDATIONS")
        print("-" * 60)
        for rec in recs:
            print(f"  → {rec}")

    print("=" * 60)


if __name__ == "__main__":
    import sys

    manager = InventoryManager()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "add":
            # Interactive add
            print("Add New Tool")
            print("-" * 40)
            tool = Tool(
                id=input("ID (e.g., pw-001): "),
                name=input("Name: "),
                category=input("Category (pressure_washer/carpet_cleaner/etc): "),
                buy_price=float(input("Buy price: $")),
                buy_date=datetime.now().strftime("%Y-%m-%d"),
                daily_rate=float(input("Daily rate: $")),
                weekly_rate=float(input("Weekly rate: $")),
                condition=input("Condition (excellent/good/fair): "),
                platforms=input("Platforms (comma-separated): ").split(","),
            )
            manager.add_tool(tool)

        elif cmd == "rental":
            # Record rental
            print("Record Rental")
            print("-" * 40)
            rental = Rental.create(
                tool_id=input("Tool ID: "),
                start=input("Start date (YYYY-MM-DD): "),
                end=input("End date (YYYY-MM-DD): "),
                platform=input("Platform: "),
                gross=float(input("Gross amount: $")),
                renter=input("Renter name (optional): "),
            )
            manager.record_rental(rental)

        elif cmd == "csv":
            manager._export_csv()
            print(f"Exported to {manager.csv_file}")

    else:
        print_dashboard(manager)
