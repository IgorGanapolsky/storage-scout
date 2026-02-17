#!/usr/bin/env python3
import argparse
import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def main() -> None:
    parser = argparse.ArgumentParser(description="Stripe revenue snapshot (optional).")
    parser.add_argument("--days", type=int, default=30, help="Lookback window.")
    parser.add_argument(
        "--amount-usd",
        type=int,
        default=0,
        help="If set, only count charges matching this amount (USD). Example: 249",
    )
    args = parser.parse_args()

    api_key = (os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("Missing STRIPE_SECRET_KEY env var.")

    try:
        import stripe
    except Exception as exc:
        raise SystemExit("Missing stripe client. Install: pip install stripe") from exc

    stripe.api_key = api_key

    since = datetime.now(UTC) - timedelta(days=int(args.days))
    since_ts = int(since.timestamp())

    target_amount = int(args.amount_usd) * 100 if int(args.amount_usd) > 0 else 0

    count = 0
    gross_cents = 0
    refunded_cents = 0

    charges = stripe.Charge.list(created={"gte": since_ts}, limit=100)
    for charge in charges.auto_paging_iter():
        if not getattr(charge, "paid", False):
            continue
        if getattr(charge, "status", "") != "succeeded":
            continue
        amount = int(getattr(charge, "amount", 0) or 0)
        if target_amount and amount != target_amount:
            continue
        count += 1
        gross_cents += amount
        refunded_cents += int(getattr(charge, "amount_refunded", 0) or 0)

    net_cents = gross_cents - refunded_cents

    print("Stripe Revenue Snapshot")
    print(f"window_days: {int(args.days)}")
    if target_amount:
        print(f"filter_amount_usd: {int(args.amount_usd)}")
    print(f"charge_count: {count}")
    print(f"gross_usd: {gross_cents / 100:.2f}")
    print(f"refunded_usd: {refunded_cents / 100:.2f}")
    print(f"net_usd: {net_cents / 100:.2f}")


if __name__ == "__main__":
    main()

