#!/usr/bin/env python3
"""Tests for the LabAuth SQLite data layer and the backup service.

Run directly:  PYTHONPATH=src uv run python tests/test_database.py
Pytest:        uv run pytest tests/test_database.py

The suite always points LABAUTH_DB_PATH at a throwaway temporary database.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_TMP_DIR = Path(tempfile.mkdtemp(prefix="labauth-db-test-"))
os.environ["LABAUTH_DB_PATH"] = str(_TMP_DIR / "labauth.db")

import database as db  # noqa: E402
import presence  # noqa: E402
from services.backup import BackupService, snapshot_database  # noqa: E402

EXPECTED_TABLES = {
    "users",
    "access_areas",
    "user_access_areas",
    "bans",
    "credentials",
    "presence_log",
    "credential_attempts",
    "admin_audit_log",
    "backup_runs",
    "current_presence",
}


def _table_names() -> set[str]:
    with db.get_db() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_schema_and_seed():
    db.init_db()
    names = _table_names()
    missing = EXPECTED_TABLES - names
    assert not missing, f"Missing tables: {missing}"

    codes = {area.code for area in db.list_access_areas()}
    assert {"indoor_lab", "tool_area"} <= codes, f"Access areas not seeded: {codes}"


def test_fresh_database_is_empty():
    """Nothing is seeded automatically: a new database starts with no users."""
    original = os.environ["LABAUTH_DB_PATH"]
    fresh = Path(tempfile.mkdtemp(prefix="labauth-fresh-")) / "fresh.db"
    os.environ["LABAUTH_DB_PATH"] = str(fresh)
    try:
        db.init_db()
        assert db.count_users() == 0, db.list_users()
        assert db.current_occupants() == []

        # The store must not invent anyone on startup either.
        store = presence.PresenceStore()
        assert store.get_people() == ()

        # Access areas are configuration, not demo data, so they are seeded.
        assert {a.code for a in db.list_access_areas()} >= {"indoor_lab", "tool_area"}
    finally:
        os.environ["LABAUTH_DB_PATH"] = original


def test_check_in_and_check_out_roundtrip():
    person = presence.store.check_in("Elena Rossi", access=("Lab interior", "CNC mill"), checked_in="09:15")
    assert person.checked_in == "09:15"
    assert person.user_id is not None
    assert db.is_user_inside(person.user_id)
    assert {"Indoor lab", "CNC mill"} <= set(person.access)

    people = {p.name: p for p in presence.store.get_people()}
    assert "Elena Rossi" in people

    changed, removed, out_time = presence.store.check_out("Elena Rossi", check_out_time="17:45")
    assert changed and removed is not None and out_time == "17:45"
    assert not db.is_user_inside(person.user_id)

    changed2, removed2, _ = presence.store.check_out("Elena Rossi")
    assert not changed2 and removed2 is None


def test_search_by_name_and_plaksha_id():
    user = db.create_user("Nisha Verma", plaksha_id="PLK-12345")
    by_name = db.search_users("nisha")
    by_id = db.search_users("PLK-123")
    assert any(u.id == user.id for u in by_name)
    assert any(u.id == user.id for u in by_id)
    assert db.get_user_by_plaksha_id("PLK-12345").id == user.id


def test_temp_user_flag_and_listing():
    temp = db.create_user("Walk In", is_temp=True, plaksha_id=None)
    assert temp.is_temp is True
    assert "Walk In" in {u.name for u in db.list_temp_users()}

    presence.store.check_in("Walk In", access=(), is_temp=True)
    person = next(p for p in presence.store.get_people() if p.name == "Walk In")
    assert person.is_temp is True
    assert person.access == ()
    presence.store.check_out("Walk In")


def test_bans_lifecycle():
    user = db.create_user("Banned Person")
    assert db.is_user_banned(user.id) is False
    ban = db.create_ban(user.id, reason="Safety violation", banned_by="admin")
    assert db.is_user_banned(user.id) is True
    assert ban.unbanned_at is None

    # At most one open ban per user.
    try:
        db.create_ban(user.id, reason="duplicate")
        raise AssertionError("Expected a uniqueness violation for a second open ban")
    except sqlite3.IntegrityError:
        pass

    assert db.lift_ban(user.id) is True
    assert db.is_user_banned(user.id) is False
    assert db.list_bans(user_id=user.id)[0].unbanned_at is not None


def test_credentials_and_attempts():
    user = db.create_user("Credential Holder")
    credential = db.enroll_credential(user.id, "nfc", "04A7B2C3")
    resolved = db.resolve_user_by_credential("nfc", "04A7B2C3")
    assert resolved is not None and resolved.id == user.id

    try:
        db.enroll_credential(user.id, "nfc", "04A7B2C3")
        raise AssertionError("Expected duplicate credential rejection")
    except sqlite3.IntegrityError:
        pass

    db.set_credential_active(credential.id, False)
    assert db.resolve_user_by_credential("nfc", "04A7B2C3") is None

    attempt = db.log_credential_attempt(
        "fingerprint",
        "template:41",
        "low_confidence",
        message="Match score 31/100",
        device_id="fp-0",
    )
    assert attempt.outcome == "low_confidence"
    assert attempt.message == "Match score 31/100"
    assert db.list_credential_attempts(limit=1)[0].id == attempt.id


def test_admin_audit_log():
    db.log_audit("admin", "user_created", "user", entity_id="7", after={"name": "X"})
    db.log_audit("admin", "settings_changed", "display", entity_id="alert", before=None, after="Evacuate")
    entries = db.list_audit_log(limit=2)
    assert entries[0].action == "settings_changed"
    assert entries[0].before is None
    assert "Evacuate" in (entries[0].after or "")


def test_presence_events_feed():
    presence.store.check_in("Event Person", access=("Indoor lab",), checked_in="11:00")
    events = presence.store.get_events(since_id=0, max_age_seconds=60.0)
    assert any(event["person"]["name"] == "Event Person" for event in events)
    latest = events[-1]
    assert latest["type"] == "IN"
    assert {"id", "person", "check_in", "check_out", "timestamp"} <= set(latest)
    presence.store.check_out("Event Person")


def test_reset_empties_lab_and_populate_does_not_log():
    before = db.count_presence()
    presence.store.populate(5)
    assert len(presence.store.get_people()) == 5
    # populate/reset use the realtime cache only; the immutable log is untouched.
    assert db.count_presence() == before

    presence.store.reset()
    # reset empties the lab and invents nobody.
    assert presence.store.get_people() == ()
    assert db.count_presence() == before


def test_snapshot_and_local_backup():
    snapshot = _TMP_DIR / "snapshot.db"
    snapshot_database(snapshot)
    assert snapshot.exists()
    conn = sqlite3.connect(snapshot)
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 3
        assert conn.execute("SELECT COUNT(*) FROM access_areas").fetchone()[0] >= 2
    finally:
        conn.close()

    result = BackupService(snapshot_dir=_TMP_DIR / "backups", push=False).run()
    assert result.run.status == "success"
    assert result.snapshot_path and Path(result.snapshot_path).exists()
    assert db.latest_backup_run().id == result.run.id


def test_failed_remote_backup_is_recorded():
    service = BackupService(
        target_url="postgresql://labauth:labauth@127.0.0.1:1/labauth",
        snapshot_dir=_TMP_DIR / "backups",
        push=True,
    )
    try:
        service.run(keep_snapshot=False)
        raised = False
    except Exception:
        raised = True
    assert raised, "Expected the remote backup to fail against an unreachable target"
    run = db.latest_backup_run()
    assert run is not None and run.status == "failed"
    assert run.error


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    print("=" * 65)
    print("  LABAUTH DATABASE SUITE")
    print("=" * 65)
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print("-" * 65)
    print(f"  {len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
