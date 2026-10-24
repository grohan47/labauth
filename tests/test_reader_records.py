"""Credential reader persistence tests using an isolated SQLite database."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_tmp = tempfile.TemporaryDirectory(prefix="labauth-reader-test-")
os.environ["LABAUTH_DB_PATH"] = str(Path(_tmp.name) / "reader.db")

import database as db  # noqa: E402
from services.reader_records import process_credential  # noqa: E402


def setup_function():
    path = db.db_path()
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    db.init_db()


def _user(name="Reader User", *, access=True):
    areas = db.list_access_areas()
    return db.create_enrolment(name, access_area_ids=[areas[0].id] if access else [])


def test_poll_toggles_presence_and_keeps_history():
    saved = _user()
    db.attach_credentials(saved["id"], [("nfc", "04AABB")])
    first = process_credential("nfc", "04AABB", "POLL", cooldown_seconds=0)
    assert first["outcome"] == "success"
    assert first["event"]["type"] == "IN"
    assert first["event"]["person"]["user_id"] == saved["id"]
    assert db.is_user_inside(saved["id"])

    second = process_credential("nfc", "04AABB", "POLL", cooldown_seconds=0)
    assert second["event"]["type"] == "OUT"
    assert not db.is_user_inside(saved["id"])
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM presence_log WHERE user_id=?", (saved["id"],)).fetchone()[0] == 2


def test_check_is_lookup_only_and_cross_reader_cooldown_is_per_user():
    saved = _user()
    db.attach_credentials(saved["id"], [("nfc", "04AABC"), ("fingerprint", "slot:7")])
    checked = process_credential("nfc", "04AABC", "CHECK", cooldown_seconds=0)
    assert checked["event"]["type"] == "CHECK"
    assert checked["event"]["person"]["is_inside"] is False
    assert checked["event"]["check_in"] is None and checked["event"]["check_out"] is None
    assert not db.is_user_inside(saved["id"])
    blocked = process_credential("fingerprint", "slot:7", "POLL")
    assert blocked["outcome"] == "cooldown"
    assert not db.is_user_inside(saved["id"])


def test_check_card_uses_recorded_times_without_writing_attendance():
    saved = _user()
    db.attach_credentials(saved["id"], [("fingerprint", "template:51")])
    entered = process_credential("fingerprint", "template:51", "POLL", cooldown_seconds=0)
    inside = process_credential("fingerprint", "template:51", "CHECK", cooldown_seconds=0)["event"]
    assert inside["person"]["is_inside"] is True
    assert inside["check_in"] == entered["event"]["check_in"]
    assert inside["check_out"] is None
    exited = process_credential("fingerprint", "template:51", "POLL", cooldown_seconds=0)
    outside = process_credential("fingerprint", "template:51", "CHECK", cooldown_seconds=0)["event"]
    assert outside["person"]["is_inside"] is False
    assert outside["check_in"] == exited["event"]["check_in"]
    assert outside["check_out"] == exited["event"]["check_out"]
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM presence_log WHERE user_id=?", (saved["id"],)).fetchone()[0] == 2


def test_concurrent_poll_serializes_cooldown_and_presence_write():
    saved = _user()
    db.attach_credentials(saved["id"], [("nfc", "race-uid")])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: process_credential("nfc", "race-uid", "POLL", cooldown_seconds=3),
            range(2),
        ))
    assert sorted(result["outcome"] for result in results) == ["cooldown", "success"]
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM presence_log WHERE user_id=?", (saved["id"],)).fetchone()[0] == 1
        outcomes = [r[0] for r in conn.execute("SELECT outcome FROM credential_attempts ORDER BY id")]
    assert outcomes == ["success", "cooldown"]
    assert db.is_user_inside(saved["id"])


def test_unknown_denied_and_no_access_are_logged():
    unknown = process_credential("nfc", "missing", "POLL")
    assert unknown["outcome"] == "unknown_credential"
    no_access = _user("No Access", access=False)
    db.attach_credentials(no_access["id"], [("nfc", "04AABD")])
    denied = process_credential("nfc", "04AABD", "POLL")
    assert denied["outcome"] == "denied"
    with db.get_db() as conn:
        attempts = conn.execute("SELECT outcome FROM credential_attempts ORDER BY id").fetchall()
    assert [row["outcome"] for row in attempts] == ["unknown_credential", "reader_error"]


def test_attach_credentials_is_atomic_and_audited():
    saved = _user()
    db.attach_credentials(saved["id"], [("nfc", "unique-uid")])
    try:
        db.attach_credentials(saved["id"], [("fingerprint", "slot:9"), ("nfc", "unique-uid")])
    except Exception:
        pass
    else:
        raise AssertionError("duplicate identifier must reject the whole association")
    credentials = db.list_credentials(user_id=saved["id"])
    assert [(item.credential_type, item.identifier) for item in credentials] == [("nfc", "unique-uid")]
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM admin_audit_log WHERE action='attach_credentials'").fetchone()[0] == 1


def test_enrolment_credentials_and_reader_draft_lease():
    areas = db.list_access_areas()
    saved = db.create_enrolment("Credential Enrolment", access_area_ids=[areas[0].id], credentials=[("nfc", "enrol-uid")])
    assert saved["credentials"][0]["identifier"] == "enrol-uid"
    draft_id = db.create_draft("session-a", saved["id"], ttl=60)
    assert db.get_draft(draft_id, "other-session") is None
    assert db.get_draft(draft_id, "session-a")["user_id"] == saved["id"]
    assert db.update_draft(draft_id, stage="capture", fp_template=12)["stage"] == "capture"
    assert [draft["id"] for draft in db.list_pending_drafts()] == [draft_id]
    try:
        db.create_draft("session-b")
    except RuntimeError:
        pass
    else:
        raise AssertionError("a second live lease must be rejected")


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            setup_function()
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
