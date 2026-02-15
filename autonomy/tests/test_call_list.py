from __future__ import annotations

import csv
import uuid
from pathlib import Path

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.call_list import generate_call_list


def _tmp_state_paths(tmp_name: str) -> tuple[str, str]:
    # ContextStore restricts writes under autonomy/state.
    db_path = f"autonomy/state/{tmp_name}.sqlite3"
    audit_path = f"autonomy/state/{tmp_name}.jsonl"
    return db_path, audit_path


def test_call_list_includes_website_and_flags_role_inbox(tmp_path: Path) -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    store.upsert_lead(
        Lead(
            id="info@example.com",
            name="",
            company="A Med Spa",
            email="info@example.com",
            phone="555-0001",
            service="med spa",
            city="Fort Lauderdale",
            state="FL",
            source="t",
            score=80,
            status="new",
            email_method="unknown",
        )
    )
    store.add_message(lead_id="info@example.com", channel="email", subject="s", body="b", status="sent")

    store.upsert_lead(
        Lead(
            id="jane.doe@example.com",
            name="Jane",
            company="B Med Spa",
            email="jane.doe@example.com",
            phone="555-0002",
            service="med spa",
            city="Fort Lauderdale",
            state="FL",
            source="t",
            score=70,
            status="new",
            email_method="direct",
        )
    )
    store.add_opt_out("jane.doe@example.com")

    csv_path = tmp_path / "leads.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "website"])
        writer.writeheader()
        writer.writerow({"email": "info@example.com", "website": "https://a.example.com"})
        writer.writerow({"email": "jane.doe@example.com", "website": "https://b.example.com"})

    rows = generate_call_list(
        sqlite_path=Path(sqlite_path),
        services=["med spa"],
        limit=50,
        require_phone=True,
        include_opt_outs=False,
        source_csv=csv_path,
    )

    # Opt-outs are excluded by default.
    assert len(rows) == 1
    r = rows[0]
    assert r.company == "A Med Spa"
    assert r.website == "https://a.example.com"
    assert r.role_inbox == "yes"
    assert r.email_sent_count == 1

