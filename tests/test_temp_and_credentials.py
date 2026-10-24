import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database as db
from presence import PresenceStore, PersonInside
from ui.display import _person_card, _presence_content


def test_24_hour_checkin_denotation():
    now = datetime.now(timezone.utc)
    # 2 hours ago: no suffix
    t_2h = (now - timedelta(hours=2)).isoformat()
    hhmm_2h = db.iso_to_local_hhmm(t_2h, reference_time=now)
    assert "+" not in hhmm_2h

    # 25 hours ago: +1
    t_25h = (now - timedelta(hours=25)).isoformat()
    hhmm_25h = db.iso_to_local_hhmm(t_25h, reference_time=now)
    assert "+1" in hhmm_25h

    # 50 hours ago: +2
    t_50h = (now - timedelta(hours=50)).isoformat()
    hhmm_50h = db.iso_to_local_hhmm(t_50h, reference_time=now)
    assert "+2" in hhmm_50h

    # 75 hours ago: +3
    t_75h = (now - timedelta(hours=75)).isoformat()
    hhmm_75h = db.iso_to_local_hhmm(t_75h, reference_time=now)
    assert "+3" in hhmm_75h


def test_temp_card_rendering_and_exit_button():
    # Regular person card
    regular = PersonInside(
        name="Alice Smith",
        photo="/static/portraits/default.svg",
        checked_in="10:00",
        access=("Tool Area",),
        is_temp=False,
    )
    regular_html = _person_card(regular, density="3rows")
    assert "person-card--temp" not in regular_html
    assert "Temporary" not in regular_html
    assert "temp-exit-btn" not in regular_html
    assert "Tool Area" in regular_html

    # Temporary person card
    temp = PersonInside(
        name="Bob Visitor",
        photo="/static/portraits/default.svg",
        checked_in="10:05",
        access=(),
        is_temp=True,
    )
    temp_html = _person_card(temp, density="3rows")
    assert "person-card--temp" in temp_html
    assert "Temporary" in temp_html
    assert "temp-exit-btn" in temp_html
    assert "Sign out" in temp_html

    # Empty presence still shows temp registration card
    content_empty = _presence_content(())
    assert "person-card--temp-register" in content_empty
    assert "Not Enrolled?" in content_empty
    assert "Click here to register your presence temporarily" in content_empty


def test_presence_store_temp_checkin_and_uid_match():
    with tempfile.TemporaryDirectory(prefix="labauth-temp-qa-") as tmp:
        db_file = Path(tmp) / "test.db"
        orig_db = os.environ.get("LABAUTH_DB_PATH")
        os.environ["LABAUTH_DB_PATH"] = str(db_file)
        try:
            db.init_db()
            store = PresenceStore()

            # First registration of temp visitor
            p1 = store.check_in(
                name="John Doe",
                plaksha_id="P9999",
                phone="9876543210",
                is_temp=True,
            )
            assert p1.is_temp is True
            assert p1.name == "John Doe"
            people = store.get_people()
            assert len(people) == 1
            assert people[0].name == "John Doe"
            assert people[0].is_temp is True

            # Check-out
            removed, person, _ = store.check_out("John Doe")
            assert removed is True
            assert len(store.get_people()) == 0

            # Re-checkin with same Plaksha UID: should match existing user, not create duplicate
            p2 = store.check_in(
                name="John Doe",
                plaksha_id="P9999",
                phone="9876543210",
                is_temp=True,
            )
            assert p2.user_id == p1.user_id
            with db.get_db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM users WHERE plaksha_id = 'P9999'").fetchone()[0]
                assert count == 1
        finally:
            if orig_db:
                os.environ["LABAUTH_DB_PATH"] = orig_db
            else:
                os.environ.pop("LABAUTH_DB_PATH", None)


def test_multiple_credentials_per_person():
    with tempfile.TemporaryDirectory(prefix="labauth-creds-qa-") as tmp:
        db_file = Path(tmp) / "test.db"
        orig_db = os.environ.get("LABAUTH_DB_PATH")
        os.environ["LABAUTH_DB_PATH"] = str(db_file)
        try:
            db.init_db()
            user = db.create_user("Multi Cred User", plaksha_id="MC001")

            # Attach multiple NFC cards and multiple fingerprints
            creds = db.attach_credentials(
                user.id,
                [
                    ("nfc", "AABBCCDD"),
                    ("nfc", "11223344"),
                    ("fingerprint", "template:10"),
                    ("fingerprint", "template:20"),
                ],
            )
            assert len(creds) == 4

            user_creds = db.list_credentials(user_id=user.id)
            assert len(user_creds) == 4
            types = [c.credential_type for c in user_creds]
            assert types.count("nfc") == 2
            assert types.count("fingerprint") == 2

            # list_credentials_with_users
            rows, total = db.list_credentials_with_users()
            assert total == 4
            assert all(r["user_name"] == "Multi Cred User" for r in rows)
        finally:
            if orig_db:
                os.environ["LABAUTH_DB_PATH"] = orig_db
            else:
                os.environ.pop("LABAUTH_DB_PATH", None)
