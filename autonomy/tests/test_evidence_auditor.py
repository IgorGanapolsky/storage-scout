import sqlite3
from pathlib import Path

from autonomy.tools.evidence_auditor import EvidenceAuditor, EvidenceSignal


def test_evidence_auditor_init(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    EvidenceAuditor(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, statement, status FROM assumptions ORDER BY id")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 3
    ids = {r[0] for r in rows}
    assert "price_point_249" in ids
    assert "sms_recovery_priority" in ids
    assert "connect_rate_threshold" in ids


def test_evidence_auditor_no_actions_table(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    auditor = EvidenceAuditor(db_path)
    signals = auditor.audit_interactions()
    assert len(signals) == 0


def test_evidence_auditor_with_payments(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    auditor = EvidenceAuditor(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE actions (action_type TEXT)")
    conn.execute("INSERT INTO actions VALUES ('payment.received')")
    conn.commit()
    conn.close()

    signals = auditor.audit_interactions()
    assert len(signals) == 1
    assert signals[0].assumption_id == "price_point_249"
    assert signals[0].impact == "positive"


def test_evidence_auditor_with_replied_leads(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    auditor = EvidenceAuditor(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE leads (status TEXT)")
    conn.executemany("INSERT INTO leads VALUES (?)", [("replied",)] * 6)
    conn.commit()
    conn.close()

    signals = auditor.audit_interactions()
    assert len(signals) == 1
    assert signals[0].assumption_id == "price_point_249"
    assert signals[0].impact == "negative"


def test_evidence_auditor_connect_rate(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    auditor = EvidenceAuditor(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE actions (action_type TEXT, payload_json TEXT)")
    conn.executemany(
        "INSERT INTO actions VALUES (?, ?)",
        [
            ("call.attempt", '{"outcome": "spoke"}'),
            ("call.attempt", '{"outcome": "voicemail"}'),
            ("call.attempt", '{"outcome": "voicemail"}'),
            ("call.attempt", '{"outcome": "voicemail"}'),
        ]
    )
    conn.commit()
    conn.close()

    signals = auditor.audit_interactions()
    assert len(signals) == 1
    assert signals[0].assumption_id == "connect_rate_threshold"
    assert signals[0].impact == "positive"  # 1/4 = 25% >= 20%

    # test negative impact
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO actions VALUES (?, ?)",
        [
            ("call.attempt", '{"outcome": "voicemail"}'),
            ("call.attempt", '{"outcome": "voicemail"}'),
        ]
    )
    conn.commit()
    conn.close()

    signals = auditor.audit_interactions()
    assert len(signals) == 1
    assert signals[0].assumption_id == "connect_rate_threshold"
    assert signals[0].impact == "negative"  # 1/6 = 16.6% < 20%


def test_evidence_auditor_update_assumptions(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    auditor = EvidenceAuditor(db_path)

    signals = [
        EvidenceSignal(source_id="test", impact="positive", note="Test", assumption_id="price_point_249")
    ]
    auditor.update_assumptions(signals)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT evidence_count FROM assumptions WHERE id='price_point_249'")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1
