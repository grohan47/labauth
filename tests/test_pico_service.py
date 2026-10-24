"""POSIX PTY integration tests for the ASCII Pico protocol and service."""

from __future__ import annotations

import os
from pathlib import Path
import pty
import select
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_tmp = tempfile.TemporaryDirectory(prefix="labauth-pico-test-")
os.environ["LABAUTH_DB_PATH"] = str(Path(_tmp.name) / "pico.db")

import database as db  # noqa: E402
from services.pico import PicoService, ReaderError  # noqa: E402


class PicoEmulator:
    """Small firmware emulator attached to the master side of a real PTY."""

    def __init__(self, master_fd: int):
        self.master_fd = master_fd
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.mode = "IDLE"
        self.fp_enabled = True
        self.nfc_enabled = True
        self.cleanup = "OFF"
        self.learning = "OFF"
        self.fp_state = "READY"
        self.startup_statuses = 0
        self.restart_after_enable = False
        self.async_error_before_next_ack = None
        self.provisional = False
        self.cleanup_on_cancel = False
        self.templates: set[int] = set()
        self.block_command = None
        self.command_entered = threading.Event()
        self.command_release = threading.Event()
        self.buffer = bytearray()
        self.commands: list[str] = []
        self.lines: list[str] = []
        os.set_blocking(master_fd, False)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1)

    def send(self, line: str):
        self.lines.append(line)
        try:
            os.write(self.master_fd, (line + "\n").encode("ascii"))
        except OSError:
            pass

    def _status(self):
        fp_state = self.fp_state
        if self.startup_statuses:
            fp_state = "BUSY"
            self.startup_statuses -= 1
        else:
            self.fp_state = "READY"
        return (
            f"STATUS fw=1 mode={self.mode} fp={fp_state} nfc=READY "
            f"cleanup={self.cleanup} learning={self.learning} "
            f"fp_enabled={'ON' if self.fp_enabled else 'OFF'} "
            f"nfc_enabled={'ON' if self.nfc_enabled else 'OFF'}"
        )

    def _reply(self, command: str):
        self.commands.append(command)
        words = command.split()
        if self.block_command == command:
            self.command_entered.set()
            self.command_release.wait(timeout=5)
        if self.async_error_before_next_ack:
            self.send(self.async_error_before_next_ack)
            self.async_error_before_next_ack = None
        if command == "PING":
            self.send("OK PONG")
        elif command == "STATUS":
            self.send(self._status())
        elif command == "CANCEL":
            self.cleanup = "OFF"
            self.learning = "OFF"
            if self.provisional and self.cleanup_on_cancel:
                self.provisional = False
                self.send("EVT FP ENROLL_CLEANED id=41")
            self.send("OK CANCEL")
        elif len(words) == 2 and words[0] == "MODE":
            self.mode = words[1]
            self.send("OK " + command)
        elif command in ("FP ENABLE", "FP DISABLE"):
            self.fp_enabled = command.endswith("ENABLE")
            if self.fp_enabled and self.restart_after_enable:
                self.fp_state = "BUSY"
                self.startup_statuses = 1
            self.send("OK " + command)
        elif command in ("NFC ENABLE", "NFC DISABLE"):
            self.nfc_enabled = command.endswith("ENABLE")
            self.send("OK " + command)
        elif command == "ENROLL":
            self.provisional = True
            self.send("EVT FP PROGRESS phase=FREE_ID id=41")
            self.send("EVT FP PROGRESS phase=LEARN_READY id=41")
            self.send("OK ENROLL")
        elif command == "ENROLL FINISH":
            self.learning = "OFF"
            self.provisional = False
            self.templates.add(41)
            self.send("EVT FP ENROLLED id=41")
            self.send("OK ENROLL FINISH")
        elif command == "NFC READ":
            self.send("EVT NFC UID uid=00112233")
            self.send("OK NFC READ")
        elif command == "FP LIST":
            self.send("OK FP LIST")
            for slot in sorted(self.templates):
                self.send(f"EVT FP SLOT id={slot}")
            self.send("EVT FP LIST_END")
        elif command.startswith("FP DELETE "):
            value = command.rsplit(" ", 1)[1].split("=", 1)[-1]
            self.send(f"OK FP DELETE id={value}")
            if int(value) in self.templates:
                self.templates.remove(int(value))
                self.send(f"EVT FP DELETED id={value}")
            else:
                self.send("ERR FP 0x12 NO_TEMPLATE")
        else:
            self.send("ERR unknown_command")

    def _run(self):
        while not self.stop_event.is_set():
            try:
                ready, _, _ = select.select([self.master_fd], [], [], .05)
                if not ready:
                    continue
                chunk = os.read(self.master_fd, 1024)
            except OSError:
                if self.stop_event.is_set():
                    return
                time.sleep(.02)
                continue
            for byte in chunk:
                if byte == 10:
                    line = self.buffer.decode("ascii", errors="replace").rstrip("\r")
                    self.buffer.clear()
                    if line:
                        self._reply(line)
                else:
                    self.buffer.append(byte)


class PicoServiceTests(unittest.TestCase):
    def setUp(self):
        self.db_path = db.db_path()
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.db_path) + suffix).unlink(missing_ok=True)
        db.init_db()
        self.master_fd, self.slave_fd = pty.openpty()
        self.port = os.ttyname(self.slave_fd)
        self.emulator = PicoEmulator(self.master_fd)
        self.emulator.start()
        self.service = PicoService(port=self.port, command_timeout=.5)
        self.service.start()
        self.addCleanup(self._cleanup)
        self.wait_for(lambda: self.service.status()["ready"], timeout=4)

    def test_inventory_merges_ghosts_filters_and_confirms_deletion(self):
        user = db.create_user('Inventory Person', plaksha_id='INV1')
        db.enroll_credential(user.id, 'fingerprint', 'template:41')
        self.emulator.templates = {41, 42, 1000}
        self.service.call('control', mode='CHECK')
        inventory = self.service.call('inventory')
        self.assertEqual(inventory['templates'], [41, 42, 1000])
        self.assertEqual(self.emulator.mode, 'CHECK')
        records, total = db.list_credentials_with_users(sensor_templates=inventory['templates'])
        self.assertEqual(total, 3)
        self.assertEqual([r['identifier'] for r in records if r['user_id'] is None], ['template:42', 'template:1000'])
        records, total = db.list_credentials_with_users(sensor_templates=inventory['templates'], query='1000', limit=1)
        self.assertEqual(total, 1)
        self.assertEqual(records[0]['id'], 'sensor:1000')
        with self.assertRaisesRegex(ReaderError, 'not on the sensor'):
            self.service.call('manage', verify_template=99, change=lambda cleanup: self.fail('saved absent slot'))
        self.service.call('manage', verify_template=42,
                          change=lambda cleanup: db.enroll_credential(user.id, 'fingerprint', 'template:42'))
        self.service.call('manage', change=lambda cleanup: cleanup(['template:1000']))
        self.assertNotIn(1000, self.emulator.templates)
        self.assertNotIn(1000, self.service.fingerprint_inventory()['templates'])
        self.assertEqual(self.emulator.mode, 'CHECK')

    def test_inventory_waits_for_fresh_ready_after_enable(self):
        self.emulator.templates = {41}
        self.emulator.restart_after_enable = True
        result = self.service.call('inventory')
        self.assertEqual(result['templates'], [41])
        commands = self.emulator.commands
        start = commands.index('MODE MAINT')
        self.assertGreaterEqual(commands[start:commands.index('FP LIST')].count('STATUS'), 2)

    def test_inventory_waits_for_list_end_and_retains_last_complete_list_on_error(self):
        self.emulator.templates = {41}
        self.service.call('inventory')
        original = self.emulator._reply
        def partial(command):
            if command == 'FP LIST':
                self.emulator.send('OK FP LIST')
                self.emulator.send('EVT FP SLOT id=42')
                self.emulator.send('ERR FP 0x01 FAILED')
            else:
                original(command)
        self.emulator._reply = partial
        with self.assertRaisesRegex(ReaderError, 'FAILED'):
            self.service.call('inventory')
        self.assertEqual(self.service.fingerprint_inventory()['templates'], [41])
        self.assertEqual(self.emulator.mode, 'POLL')

    def _cleanup(self):
        self.service.stop()
        self.emulator.stop()
        for fd in (self.slave_fd, self.master_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    @staticmethod
    def wait_for(predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError("Timed out waiting for Pico service state")

    def make_user(self, name="PTY User", credentials=()):
        area = db.list_access_areas()[0]
        return db.create_enrolment(name, access_area_ids=[area.id], credentials=credentials)

    def set_mode(self, mode):
        return self.service.call("control", owner="admin", mode=mode)

    def attempt_rows(self):
        with db.get_db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM credential_attempts ORDER BY id")]

    def presence_count(self):
        with db.get_db() as conn:
            return conn.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0]

    def test_people_delete_confirms_registered_sensor_template_and_preserves_mode(self):
        from services.people import delete_people
        from services.user_queries import user_details
        user = self.make_user(credentials=[('fingerprint', 'template:41')])
        self.emulator.templates.add(41)
        self.set_mode('CHECK')
        result = self.service.call('manage', change=lambda cleanup: delete_people([user['id']], cleanup))
        self.assertEqual(result, [user['id']])
        self.assertIn('FP DELETE 41', self.emulator.commands)
        self.assertNotIn(41, self.emulator.templates)
        self.assertIsNone(user_details(user['id']))
        self.assertEqual(self.service.status()['mode'], 'CHECK')

    def test_people_mutation_cannot_interrupt_enrollment(self):
        from services.people import edit_person
        user = self.make_user()
        self.service.call('begin', owner='owner')
        with self.assertRaisesRegex(ReaderError, 'Finish or cancel'):
            self.service.call('manage', change=lambda cleanup: edit_person(user['id'], {'name':'Changed'}, cleanup))
        self.assertNotEqual(db.get_user(user['id']).name, 'Changed')

    def test_duplicate_fingerprint_event_has_explicit_error(self):
        draft = self.service.call('begin', owner='owner')
        self.service.call('action', owner='owner', session=draft['id'], operation='fingerprint')
        self.wait_for(lambda: db.get_draft(draft['id'])['stage'] == 'learning')
        self.emulator.send('EVT FP DUPLICATE id=19')
        self.wait_for(lambda: db.get_draft(draft['id'])['stage'] == 'error')
        self.assertIn('already enrolled', db.get_draft(draft['id'])['message'])
        self.assertEqual(db.list_credentials(), [])

    def test_polling_busy_reports_ready_without_hiding_raw_state_or_faults(self):
        for mode, state, flags, expected in [
            ('POLL', 'BUSY', '', 'READY'),
            ('CHECK', 'BUSY', '', 'BUSY'),
            ('ENROLL', 'BUSY', '', 'BUSY'),
            ('MAINT', 'BUSY', '', 'BUSY'),
            ('POLL', 'FAULT', '', 'FAULT'),
            ('POLL', 'STARTING', '', 'STARTING'),
            ('POLL', 'OFF', '', 'OFF'),
            ('POLL', 'BUSY', ' cleanup=ON', 'BUSY'),
            ('POLL', 'BUSY', ' learning=ON', 'BUSY'),
            # Updated firmware owns the availability decision, including startup.
            ('POLL', 'BUSY', ' fp_state=BUSY', 'BUSY'),
            ('POLL', 'READY', ' fp_state=BUSY', 'READY'),
        ]:
            with self.subTest(mode=mode, state=state, flags=flags):
                fields = {'mode': mode, 'fp': state, 'cleanup': 'OFF', 'learning': 'OFF'}
                fields.update(token.split('=', 1) for token in flags.split())
                self.service.handle_line('STATUS ' + ' '.join(f'{key}={value}' for key, value in fields.items()))
                status = self.service.status()
                self.assertEqual(status['fp'], expected)
                self.assertEqual(status['fp_state'], 'BUSY' if 'fp_state=BUSY' in flags else state)
        self.service.call('control', reader='fingerprint', enabled=False)
        self.service.handle_line('STATUS mode=POLL fp=BUSY cleanup=OFF learning=OFF')
        self.assertEqual(self.service.status()['fp'], 'BUSY')

    def test_real_pty_handshake_and_registered_fp_nfc_attendance(self):
        self.assertTrue(self.service.status()["connected"])
        self.assertEqual(self.service.status()["fp"], "READY")
        self.assertEqual(self.service.status()["nfc"], "READY")
        user = self.make_user(credentials=[("fingerprint", "template:41"), ("nfc", "00112233")])
        self.set_mode("POLL")

        self.emulator.send("EVT FP MATCH id=41")
        self.wait_for(lambda: db.is_user_inside(user["id"]))
        self.emulator.send("EVT NFC UID uid=00112233")
        self.wait_for(lambda: any(row["outcome"] == "cooldown" for row in self.attempt_rows()))
        self.assertEqual(self.presence_count(), 1)

        # Once the shared user cooldown has elapsed, the second reader checks out.
        time.sleep(3.05)
        self.emulator.send("EVT NFC UID uid=00112233")
        self.wait_for(lambda: not db.is_user_inside(user["id"]))
        self.assertEqual(self.presence_count(), 2)

    def test_unknown_fp_nfc_events_and_check_mode_do_not_change_attendance(self):
        known = self.make_user(credentials=[("fingerprint", "template:41")])
        self.set_mode("CHECK")
        self.emulator.send("EVT FP MATCH id=41")
        self.wait_for(lambda: bool(self.service.events()["events"]))
        self.assertEqual(self.presence_count(), 0)

        self.set_mode("POLL")
        self.emulator.send("EVT FP MATCH id=42")
        self.emulator.send("EVT NFC UID uid=ABCDEF12")
        self.wait_for(lambda: len(self.attempt_rows()) >= 3)
        self.assertEqual(self.presence_count(), 0)
        events = self.service.events()["events"]
        self.assertTrue(any(e.get("type") == "ERROR" and e.get("source") == "fingerprint" for e in events))
        self.assertTrue(any(e.get("type") == "ERROR" and e.get("source") == "nfc" for e in events))
        self.assertIsNotNone(db.get_user(known["id"]))

    def test_draft_owns_readers_and_owner_or_browser_cannot_supply_credentials(self):
        draft = self.service.call("begin", owner="owner")
        session = draft["id"]
        self.assertEqual(self.service.status()["mode"], "IDLE")
        self.assertTrue(self.service.status()["enrollment"])
        with self.assertRaises(ReaderError):
            self.service.call("action", owner="intruder", session=session, operation="skip_nfc")
        with self.assertRaises(ReaderError):
            self.service.call("control", owner="owner", mode="POLL")
        with self.assertRaises(ReaderError):
            self.service.call("action", owner="owner", session=session,
                              operation="inject_credential", uid="DEADBEEF")

        before = len(self.attempt_rows())
        self.emulator.send("EVT FP MATCH id=41")
        time.sleep(.1)
        self.assertEqual(len(self.attempt_rows()), before)
        # A forged browser UID is ignored; the only credential comes from the
        # emulated reader's UID line if/when the NFC operation is requested.
        self.service.call("action", owner="owner", session=session,
                          operation="nfc", uid="DEADBEEF")
        self.wait_for(lambda: db.get_draft(session)["nfc_uid"] == "00112233")
        self.assertNotEqual(db.get_draft(session)["nfc_uid"], "DEADBEEF")

    def test_fingerprint_enrollment_uses_hardware_event_and_cancel_deletes_template(self):
        draft = self.service.call("begin", owner="owner")
        self.service.call("action", owner="owner", session=draft["id"], operation="fingerprint")
        self.wait_for(lambda: db.get_draft(draft["id"])["stage"] == "learning")
        self.service.call("action", owner="owner", session=draft["id"], operation="finish")
        self.wait_for(lambda: db.get_draft(draft["id"])["fp_template"] == 41)

        created = self.service.call("save", owner="owner", session=draft["id"],
                                    save=lambda creds: db.create_enrolment("Hardware User", credentials=creds))
        self.assertEqual([(c["credential_type"], c["identifier"]) for c in created["credentials"]],
                         [("fingerprint", "template:41")])
        with db.get_db() as conn:
            row = conn.execute("SELECT template FROM credentials WHERE identifier='template:41'").fetchone()
        self.assertIsNone(row["template"])

    def test_nfc_enrollment_and_reader_disable_policy(self):
        draft = self.service.call("begin", owner="owner")
        result = self.service.call("action", owner="owner", session=draft["id"], operation="nfc")
        self.wait_for(lambda: db.get_draft(draft["id"])["nfc_uid"] == "00112233")
        created = self.service.call("save", owner="owner", session=draft["id"],
                                    save=lambda creds: db.create_enrolment("NFC User", credentials=creds))
        self.assertEqual(created["credentials"][0]["identifier"], "00112233")

        self.service.call("control", owner="admin", reader="fingerprint", enabled=False)
        self.assertFalse(self.service.status()["fp_enabled"])
        next_draft = self.service.call("begin", owner="owner")
        with self.assertRaises(ReaderError):
            self.service.call("action", owner="owner", session=next_draft["id"], operation="fingerprint")
        self.service.call("action", owner="owner", session=next_draft["id"], operation="cancel")

    def test_cancelled_draft_persists_after_template_cleanup(self):
        draft = self.service.call("begin", owner="owner")
        self.service.call("action", owner="owner", session=draft["id"], operation="fingerprint")
        self.wait_for(lambda: db.get_draft(draft["id"])["stage"] == "learning")
        self.service.call("action", owner="owner", session=draft["id"], operation="finish")
        self.wait_for(lambda: db.get_draft(draft["id"])["fp_template"] == 41)
        self.emulator.restart_after_enable = True
        self.service.call("action", owner="owner", session=draft["id"], operation="cancel")
        saved_draft = db.get_draft(draft["id"])
        self.assertEqual(saved_draft["status"], "cancelled")
        self.assertIsNone(saved_draft["fp_template"])
        self.assertIn("FP DELETE 41", self.emulator.commands)
        self.assertFalse(self.service.status()["enrollment"])
        self.assertEqual(db.list_pending_drafts(), [])
        delete_index = self.emulator.commands.index("FP DELETE 41")
        self.assertIn("STATUS", self.emulator.commands[delete_index - 2:delete_index])

    def test_cancel_is_idempotent_when_firmware_already_cleaned_candidate(self):
        draft = self.service.call("begin", owner="owner")
        self.service.call("action", owner="owner", session=draft["id"], operation="fingerprint")
        self.wait_for(lambda: db.get_draft(draft["id"])["stage"] == "learning")
        self.emulator.cleanup_on_cancel = True
        self.service.call("action", owner="owner", session=draft["id"], operation="cancel")
        saved_draft = db.get_draft(draft["id"])
        self.assertEqual(saved_draft["status"], "cancelled")
        self.assertIsNone(db.get_setting("reader_candidate_" + draft["id"]))
        self.assertIn("EVT FP ENROLL_CLEANED id=41", self.emulator.lines)
        self.assertNotIn("FP DELETE 41", self.emulator.commands)

    def test_missing_template_delete_ack_is_confirmed_by_async_no_template(self):
        draft = self.service.call("begin", owner="owner")
        self.service.call("action", owner="owner", session=draft["id"], operation="fingerprint")
        self.wait_for(lambda: db.get_draft(draft["id"])["stage"] == "learning")
        self.service.call("action", owner="owner", session=draft["id"], operation="cancel")
        saved_draft = db.get_draft(draft["id"])
        self.assertEqual(saved_draft["status"], "cancelled")
        self.assertIn("FP DELETE 41", self.emulator.commands)
        self.assertIn("ERR FP 0x12 NO_TEMPLATE", self.emulator.lines)
        self.assertIsNone(db.get_setting("reader_candidate_" + draft["id"]))

    def test_async_firmware_error_does_not_fail_pending_control_ack(self):
        draft = self.service.call("begin", owner="owner")
        self.emulator.async_error_before_next_ack = "ERR FP ENROLL_CLEANUP id=41 code=0x12"
        result = self.service.call("control", owner="admin", reader="fingerprint", enabled=False)
        self.assertFalse(result["fp_enabled"])
        self.assertIn("FP DISABLE", self.emulator.commands)
        self.assertEqual(db.get_draft(draft["id"])["owner"], "owner")

    def test_reconnect_reconciles_save_committed_before_draft_marker(self):
        draft = self.service.call("begin", owner="owner")
        self.service.call("action", owner="owner", session=draft["id"], operation="fingerprint")
        self.wait_for(lambda: db.get_draft(draft["id"])["stage"] == "learning")
        self.service.call("action", owner="owner", session=draft["id"], operation="finish")
        self.wait_for(lambda: db.get_draft(draft["id"])["fp_template"] == 41)

        def committed_then_crashed(credentials):
            db.create_enrolment("Saved Before Crash", credentials=credentials)
            raise RuntimeError("simulated process loss after commit")

        with self.assertRaises(ReaderError):
            self.service.call("save", owner="owner", session=draft["id"], save=committed_then_crashed)
        delete_count = self.emulator.commands.count("FP DELETE 41")
        self.service.stop()
        self.service = PicoService(port=self.port, command_timeout=.5)
        self.service.start()
        self.wait_for(lambda: self.service.status()["ready"], timeout=4)
        repaired = db.get_draft(draft["id"])
        self.assertEqual(repaired["status"], "committed")
        self.assertEqual(self.emulator.commands.count("FP DELETE 41"), delete_count)

    def test_queued_begin_stays_paused_behind_inflight_probe(self):
        user = self.make_user(credentials=[("fingerprint", "template:41")])
        self.set_mode("POLL")
        self.emulator.block_command = "STATUS"
        self.emulator.command_release.clear()
        self.service._enqueue("probe")
        self.assertTrue(self.emulator.command_entered.wait(timeout=2))

        begin_entered = threading.Event()
        begin_release = threading.Event()
        original_execute = self.service._execute

        def hold_begin(action, owner, data):
            if action == "begin":
                begin_entered.set()
                if not begin_release.wait(timeout=3):
                    raise AssertionError("test did not release begin barrier")
            return original_execute(action, owner, data)

        self.service._execute = hold_begin
        result = {}

        def begin_call():
            try:
                result["draft"] = self.service.call("begin", owner="owner")
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc

        caller = threading.Thread(target=begin_call, daemon=True)
        caller.start()
        try:
            self.emulator.command_release.set()
            self.assertTrue(begin_entered.wait(timeout=2))
            self.emulator.send("EVT FP MATCH id=41")
            time.sleep(.1)
            self.assertFalse(db.is_user_inside(user["id"]))
            self.assertEqual(self.presence_count(), 0)
        finally:
            begin_release.set()
            self.emulator.command_release.set()
            caller.join(timeout=3)
        self.assertFalse(caller.is_alive())
        self.assertNotIn("error", result)
        self.assertTrue(self.service.status()["enrollment"])

    def test_stop_resolves_future_for_mutation_queued_behind_blocked_command(self):
        self.emulator.block_command = "STATUS"
        self.emulator.command_release.clear()
        self.service._enqueue("probe")
        self.assertTrue(self.emulator.command_entered.wait(timeout=2))
        result = {}

        def begin_call():
            try:
                result["draft"] = self.service.call("begin", owner="owner")
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc

        caller = threading.Thread(target=begin_call, daemon=True)
        caller.start()
        try:
            self.wait_for(lambda: self.service._jobs.qsize() == 1)
            self.service.stop()
            caller.join(timeout=2)
            self.assertFalse(caller.is_alive(), "queued call remained unresolved after stop")
            self.assertIsInstance(result.get("error"), ReaderError)
        finally:
            self.emulator.command_release.set()


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PicoServiceTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
