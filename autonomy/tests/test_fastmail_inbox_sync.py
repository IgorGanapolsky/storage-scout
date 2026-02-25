import shutil
from unittest.mock import MagicMock, patch

import pytest

from autonomy.context_store import ContextStore, STATE_DIR
from autonomy.tools.fastmail_inbox_sync import sync_fastmail_inbox


@pytest.fixture
def test_state_dir():
    # ContextStore enforces paths under autonomy/state
    tdir = STATE_DIR / "test_tmp"
    tdir.mkdir(parents=True, exist_ok=True)
    yield tdir
    # Cleanup after tests
    if tdir.exists():
        shutil.rmtree(tdir)


@patch("imaplib.IMAP4_SSL")
def test_sync_fastmail_intake_scoring(mock_imap_cls, test_state_dir):
    sqlite_path = test_state_dir / "test.sqlite3"
    audit_log = test_state_dir / "audit.jsonl"
    state_path = test_state_dir / "state.json"

    # Mock IMAP instance
    mock_imap = MagicMock()
    mock_imap_cls.return_value = mock_imap

    # Mock login and select
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])

    # Mock search response (UIDs)
    mock_imap.uid.side_effect = [
        ("OK", [b"101"]),  # search UIDs
        ("OK", [
            (b"101 (RFC822 {1234}", b"From: \"FormSubmit\" <noreply@formsubmit.co>\r\n"
             b"Subject: New Baseline Intake from CallCatcher\r\n\r\n"
             b"Name: Alice Test\r\n"
             b"Email: alice@example.com\r\n"
             b"Phone: 555-0101\r\n"
             b"Company: Alice Dental\r\n"
             b"Service: Dentist\r\n"
             b"City: Miami\r\n"
             b"State: FL\r\n")
        ]), # fetch content for UID 101
    ]

    res = sync_fastmail_inbox(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        fastmail_user="test@fastmail.com",
        fastmail_password="password",
        state_path=state_path
    )

    assert res.intake_submissions == 1
    assert res.last_uid == 101

    # Verify lead was added and scored
    store = ContextStore(str(sqlite_path), str(audit_log))
    status = store.get_lead_status("alice@example.com")
    assert status == "new"

    with store.conn:
        row = store.conn.execute("SELECT * FROM leads WHERE id='alice@example.com'").fetchone()
        assert row["name"] == "Alice Test"
        assert row["company"] == "Alice Dental"
        assert row["phone"] == "555-0101"
        assert row["service"] == "Dentist"
        assert row["city"] == "Miami"
        assert row["state"] == "FL"
        assert row["source"] == "intake"
        # Score calculation:
        # company (+20) + phone (+15) + service (+10 + 15) + city/state (+10 + 5) + email (+20) = 95
        assert row["score"] == 95

@patch("imaplib.IMAP4_SSL")
def test_sync_fastmail_bounce(mock_imap_cls, test_state_dir):
    sqlite_path = test_state_dir / "test_bounce.sqlite3"
    audit_log = test_state_dir / "audit_bounce.jsonl"
    state_path = test_state_dir / "state_bounce.json"

    # Pre-populate lead
    store = ContextStore(str(sqlite_path), str(audit_log))
    from autonomy.context_store import Lead
    store.upsert_lead(Lead(id="bounce@example.com", name="", company="", email="bounce@example.com", phone="", service="", city="", state="", source="test", status="contacted"))

    mock_imap = MagicMock()
    mock_imap_cls.return_value = mock_imap
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_imap.select.return_value = ("OK", [b"1"])

    mock_imap.uid.side_effect = [
        ("OK", [b"102"]),
        ("OK", [
            (b"102 (RFC822 {1234}", b"From: mailer-daemon@fastmail.com\r\n"
             b"Subject: Delivery Status Notification (Failure)\r\n\r\n"
             b"Final-Recipient: rfc822; bounce@example.com\r\n"
             b"Action: failed\r\n")
        ]),
    ]

    res = sync_fastmail_inbox(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        fastmail_user="test@fastmail.com",
        fastmail_password="password",
        state_path=state_path
    )

    assert res.new_bounces == 1
    assert store.get_lead_status("bounce@example.com") == "bounced"
