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


def test_call_list_prioritizes_warm_statuses() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    for email, status in (
        ("new@example.com", "new"),
        ("contacted@example.com", "contacted"),
        ("replied@example.com", "replied"),
    ):
        store.upsert_lead(
            Lead(
                id=email,
                name="",
                company=email.split("@", 1)[0],
                email=email,
                phone="555-1000",
                service="med spa",
                city="Coral Springs",
                state="FL",
                source="t",
                score=80,
                status=status,
                email_method="direct",
            )
        )

    rows = generate_call_list(
        sqlite_path=Path(sqlite_path),
        services=["med spa"],
        limit=10,
        require_phone=True,
        include_opt_outs=False,
        source_csv=None,
    )

    ordered = [r.email for r in rows]
    assert ordered[:3] == ["replied@example.com", "contacted@example.com", "new@example.com"]


def test_call_list_high_intent_filters_role_inbox_and_low_scores() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    store.upsert_lead(
        Lead(
            id="info@clinic.example",
            name="",
            company="Role Inbox Clinic",
            email="info@clinic.example",
            phone="555-2001",
            service="med spa",
            city="Coral Springs",
            state="FL",
            source="t",
            score=95,
            status="replied",
            email_method="direct",
        )
    )
    store.upsert_lead(
        Lead(
            id="owner@clinic.example",
            name="Owner",
            company="Owner Clinic",
            email="owner@clinic.example",
            phone="555-2002",
            service="med spa",
            city="Coral Springs",
            state="FL",
            source="t",
            score=65,
            status="replied",
            email_method="direct",
        )
    )
    store.upsert_lead(
        Lead(
            id="jane@clinic.example",
            name="Jane",
            company="Jane Clinic",
            email="jane@clinic.example",
            phone="555-2003",
            service="med spa",
            city="Coral Springs",
            state="FL",
            source="t",
            score=92,
            status="replied",
            email_method="direct",
        )
    )

    rows = generate_call_list(
        sqlite_path=Path(sqlite_path),
        services=["med spa"],
        statuses=["replied", "contacted"],
        min_score=80,
        exclude_role_inbox=True,
        limit=25,
        require_phone=True,
        include_opt_outs=False,
    )

    assert [r.email for r in rows] == ["jane@clinic.example"]


def test_call_list_enrichment_prioritizes_recent_spoke_signals() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    for email in ("spoke@clinic.example", "noanswer@clinic.example"):
        store.upsert_lead(
            Lead(
                id=email,
                name="",
                company=email.split("@", 1)[0],
                email=email,
                phone="555-3000",
                service="dentist",
                city="Coral Springs",
                state="FL",
                source="t",
                score=80,
                status="contacted",
                email_method="direct",
            )
        )

    store.log_action(
        agent_id="agent.autocall.twilio.v1",
        action_type="call.attempt",
        trace_id="t1",
        payload={"lead_id": "spoke@clinic.example", "outcome": "spoke"},
    )
    store.log_action(
        agent_id="agent.autocall.twilio.v1",
        action_type="call.attempt",
        trace_id="t2",
        payload={"lead_id": "noanswer@clinic.example", "outcome": "no_answer"},
    )

    rows = generate_call_list(
        sqlite_path=Path(sqlite_path),
        services=["dentist"],
        statuses=["contacted"],
        limit=10,
        require_phone=True,
        include_opt_outs=False,
    )

    assert [r.email for r in rows[:2]] == ["spoke@clinic.example", "noanswer@clinic.example"]
    assert rows[0].priority_score > rows[1].priority_score
    assert rows[0].recent_spoke == 1
    assert rows[1].recent_no_answer == 1


def test_call_list_can_disable_enrichment_for_static_ranking() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    store.upsert_lead(
        Lead(
            id="highnew@clinic.example",
            name="",
            company="High New",
            email="highnew@clinic.example",
            phone="555-4001",
            service="dentist",
            city="Coral Springs",
            state="FL",
            source="t",
            score=95,
            status="new",
            email_method="direct",
        )
    )
    store.upsert_lead(
        Lead(
            id="lowcontacted@clinic.example",
            name="",
            company="Low Contacted",
            email="lowcontacted@clinic.example",
            phone="555-4002",
            service="dentist",
            city="Coral Springs",
            state="FL",
            source="t",
            score=70,
            status="contacted",
            email_method="direct",
        )
    )

    rows = generate_call_list(
        sqlite_path=Path(sqlite_path),
        services=["dentist"],
        statuses=["new", "contacted"],
        limit=10,
        require_phone=True,
        include_opt_outs=False,
        enrichment_enabled=False,
    )

    # Without enrichment, static ordering still favors warm status buckets.
    assert [r.email for r in rows[:2]] == ["lowcontacted@clinic.example", "highnew@clinic.example"]
