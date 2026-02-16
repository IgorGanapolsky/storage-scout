#!/usr/bin/env python3
import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="GA4 event counts for CallCatcher Ops (optional).")
    parser.add_argument("--days", type=int, default=7, help="Lookback window.")
    args = parser.parse_args()

    property_id = (os.getenv("GA4_PROPERTY_ID") or "").strip()
    credentials_path = Path(os.getenv("GA_SERVICE_ACCOUNT_JSON", ".secrets/callcatcherops-ga.json"))

    if not property_id:
        raise SystemExit("Missing GA4_PROPERTY_ID env var (numeric GA4 property id).")
    if not credentials_path.exists():
        raise SystemExit(f"Missing service account JSON at {credentials_path}.")

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )
        from google.oauth2 import service_account
    except Exception as exc:
        raise SystemExit(
            "Missing GA4 client deps. Install: pip install google-analytics-data google-auth"
        ) from exc

    creds = service_account.Credentials.from_service_account_file(
        str(credentials_path),
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=f"{int(args.days)}daysAgo", end_date="today")],
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")],
    )

    response = client.run_report(request)
    counts: dict[str, int] = {}
    for row in response.rows:
        name = row.dimension_values[0].value
        count = int(float(row.metric_values[0].value or "0"))
        counts[name] = count

    def show(label: str) -> None:
        print(f"{label}: {counts.get(label, 0)}")

    print("GA4 Event Counts")
    print(f"property_id: {property_id}")
    print(f"window_days: {int(args.days)}")
    show("page_view")
    show("cta_click")
    show("intake_submit")


if __name__ == "__main__":
    main()

