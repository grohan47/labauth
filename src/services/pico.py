"""Pico USB line protocol, reader ownership and database-backed decisions.

The reader thread owns input framing. A single control thread serializes commands
and waits for their acknowledgements, keeping serial waits off NiceGUI's loop.
No browser is allowed to supply a credential observation.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import copy
import logging
import os
import queue
import re
import sqlite3
import threading
import time

import serial
from serial.tools import list_ports

import database as db
from services.reader_records import process_credential

log = logging.getLogger(__name__)


class ReaderError(ValueError):
    pass


def template_id(value):
    if not isinstance(value, (str, int)) or not str(value).isdigit() or not 1 <= int(value) <= 1000:
        raise ReaderError('Invalid fingerprint template ID')
    return int(value)


def card_uid(value):
    if not isinstance(value, str) or len(value) not in (8, 14, 20) or not re.fullmatch(r'[0-9A-Fa-f]+', value):
        raise ReaderError('Invalid NFC UID')
    return value.upper()


def packet(line):
    """Parse printable bounded ASCII; never interpret the line as code/JSON."""
    if not line or len(line) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in line):
        raise ReaderError('Invalid Pico line')
    words, fields = [], {}
    for token in line.split():
        if '=' in token:
            key, value = token.split('=', 1)
            if not re.fullmatch(r'[a-z_]+', key) or key in fields:
                raise ReaderError('Invalid Pico fields')
            fields[key] = value
        else:
            words.append(token)
    return words, fields


class PicoService:
    def __init__(self, port=None, *, command_timeout=5.0):
        self.port = port if port is not None else os.environ.get('LABAUTH_PICO_PORT', '')
        self.command_timeout = command_timeout
        self.device_id = os.environ.get('LABAUTH_PICO_DEVICE_ID', 'pico')
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._jobs = queue.Queue(maxsize=64)
        self._mutation_count = 0
        self._serial = None
        self._threads = []
        self._pending = None
        self._inventory = None
        self._inventory_at = None
        self._inventory_slots = None
        self._epoch = 0
        self._paused = True
        self._draft_id = None
        self._candidate_id = None
        self._finish_requested = False
        self._deleted_id = None
        self._deleting_id = None
        self._cleanup_confirmed = set()
        self._progress = {}
        self._events = deque(maxlen=100)
        self._cursor = time.time_ns() // 1000
        self._last_feedback = {}
        self._status = dict(connected=False, ready=False, configured=bool(self.port),
                            error='' if self.port else 'Pico port not configured', mode='IDLE',
                            fp='ABSENT', nfc='ABSENT', fp_enabled=True, nfc_enabled=True)
        self._desired = {'fingerprint': db.get_setting('reader_fp_enabled', 'ON') != 'OFF',
                         'nfc': db.get_setting('reader_nfc_enabled', 'ON') != 'OFF'}

    def start(self):
        if self._threads:
            return
        self._stop.clear()
        for target in ([self._control_loop, self._read_loop] if self.port else [self._control_loop]):
            thread = threading.Thread(target=target, daemon=True, name=f'pico-{target.__name__}')
            self._threads.append(thread)
            thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            if self._pending:
                self._pending['error'] = 'Reader service stopped'
                self._pending['event'].set()
            if self._serial:
                self._serial.close()
            while True:
                try:
                    action, _, _, future = self._jobs.get_nowait()
                except queue.Empty:
                    break
                if action in ('begin', 'control', 'action', 'save', 'manage', 'inventory'):
                    self._mutation_count = max(0, self._mutation_count - 1)
                if future and not future.done():
                    future.set_exception(ReaderError('Reader service stopped'))
            self._paused = True
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def status(self):
        with self._lock:
            status = {**self._status, 'fp_enabled': self._desired['fingerprint'],
                      'nfc_enabled': self._desired['nfc'], 'enrollment': self._draft_id is not None}
            status.setdefault('fp_state', status['fp'])
            # Older firmware reports ordinary polling work as BUSY. New firmware
            # supplies fp_state separately and already reports availability in fp.
            if ('fp_state' not in self._status and status['fp'] == 'BUSY'
                    and status['mode'] == 'POLL' and status['connected'] and status['ready']
                    and status['fp_enabled'] and not status['enrollment']
                    and status.get('cleanup') != 'ON' and status.get('learning') != 'ON'):
                status['fp'] = 'READY'
            return status

    def events(self, since=0):
        with self._lock:
            # A timestamp-derived cursor prevents old browser cursors hiding a new process.
            return {'events': [copy.deepcopy(e) for e in self._events
                               if e['id'] > since and time.time() - e['timestamp'] < 20],
                    'cursor': self._cursor}

    def _publish(self, **data):
        with self._lock:
            self._cursor += 1
            self._events.append({**data, 'id': self._cursor, 'timestamp': time.time()})

    def _feedback(self, source, title, message, outcome='reader_error', identifier=''):
        key = (source, title, identifier)
        now = time.monotonic()
        if now - self._last_feedback.get(key, -10) < 1.5:
            return
        self._last_feedback = {k: t for k, t in self._last_feedback.items() if now - t < 20}
        self._last_feedback[key] = now
        db.log_credential_attempt(source, identifier, outcome, message=message, device_id=self.device_id)
        self._publish(type='ERROR', source=source, title=title, message=message)

    def call(self, action, *, owner='', **data):
        future = Future()
        mutation = action in ('begin', 'control', 'action', 'save', 'manage', 'inventory')
        with self._lock:
            if not self._threads or self._stop.is_set():
                raise ReaderError('Reader service is unavailable')
            # Pause and count every queued mutation. A prior job's finally block
            # cannot reopen attendance while a later mutation still waits.
            if mutation:
                self._paused = True
                self._mutation_count += 1
            try:
                self._jobs.put_nowait((action, owner, data, future))
            except queue.Full as exc:
                if mutation:
                    self._mutation_count = max(0, self._mutation_count - 1)
                    self._paused = bool(self._draft_id) or self._mutation_count > 0 or not self._status['ready']
                raise ReaderError('Reader is busy') from exc
        # Returning a timeout while the queued operation later executes is unsafe.
        # Bounded serial operations resolve this future; the web event loop is not blocked.
        return future.result()

    def _enqueue(self, action, **data):
        with self._lock:
            if self._stop.is_set():
                return
            try:
                self._jobs.put_nowait((action, '', data, None))
            except queue.Full:
                log.error('Pico control queue is full')

    def _command(self, text, expected=None, *, timeout=None):
        expected = expected or 'OK ' + text
        pending = {'event': threading.Event(), 'expected': expected, 'error': '', 'line': ''}
        with self._lock:
            if not self._serial or not self._status['connected']:
                raise ReaderError('Pico disconnected')
            self._pending = pending
            try:
                payload = (text + '\n').encode('ascii')
                if self._serial.write(payload) != len(payload):
                    raise ReaderError('Incomplete Pico command write')
            except Exception:
                self._pending = None
                raise
        try:
            if not pending['event'].wait(self.command_timeout if timeout is None else timeout):
                # No command IDs exist in firmware: reconnect rather than accept a late ACK.
                with self._lock:
                    self._status['ready'] = False
                    self._paused = True
                    if self._serial:
                        self._serial.close()
                raise ReaderError('Pico command acknowledgement timed out')
            if pending['error']:
                raise ReaderError(pending['error'])
            return pending['line']
        finally:
            with self._lock:
                if self._pending is pending:
                    self._pending = None

    def _resolve_port(self):
        if self.port != 'auto':
            return self.port
        devices = [p.device for p in list_ports.comports() if p.vid == 0x2E8A]
        if len(devices) != 1:
            raise ReaderError('Select one Pico using LABAUTH_PICO_PORT')
        return devices[0]

    def _read_loop(self):
        while not self._stop.is_set():
            connection = None
            try:
                kwargs = dict(baudrate=115200, timeout=.1, write_timeout=1)
                if os.name == 'posix':
                    kwargs['exclusive'] = True
                connection = serial.Serial(self._resolve_port(), **kwargs)
                connection.reset_input_buffer()
                with self._lock:
                    self._serial = connection
                    self._epoch += 1
                    self._status.update(connected=True, ready=False, error='', mode='IDLE')
                    self._paused = True
                self._enqueue('sync')
                heartbeat = time.monotonic() + 5
                buffer = bytearray()
                overflow = False
                while not self._stop.is_set():
                    chunk = connection.read(max(1, min(connection.in_waiting, 2048)))
                    for byte in chunk:
                        if byte == 10:
                            if not overflow:
                                try:
                                    self.handle_line(buffer.decode('ascii').rstrip('\r'))
                                except (UnicodeError, ReaderError):
                                    log.warning('Discarded malformed Pico line')
                            buffer.clear()
                            overflow = False
                        elif len(buffer) < 512:
                            buffer.append(byte)
                        else:
                            overflow = True
                    self._expire_draft()
                    if time.monotonic() >= heartbeat:
                        heartbeat = time.monotonic() + 5
                        self._enqueue('probe')
            except (serial.SerialException, OSError, ReaderError):
                if not self._stop.is_set():
                    log.info('Pico unavailable; reconnecting', exc_info=False)
            except Exception:
                if not self._stop.is_set():
                    log.exception('Pico event processing failed')
            finally:
                with self._lock:
                    self._status.update(connected=False, ready=False, error='Pico disconnected')
                    self._paused = True
                    if self._pending:
                        self._pending['error'] = 'Pico disconnected'
                        self._pending['event'].set()
                    self._serial = None
                if connection:
                    connection.close()
            self._stop.wait(1)

    def _control_loop(self):
        while not self._stop.is_set():
            try:
                action, owner, data, future = self._jobs.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                if self._stop.is_set():
                    raise ReaderError('Reader service stopped')
                result = self._execute(action, owner, data)
                if future:
                    future.set_result(result)
            except Exception as exc:
                log.debug('Reader operation failed: %s', exc)
                if future:
                    future.set_exception(exc if isinstance(exc, (ReaderError, ValueError, sqlite3.IntegrityError))
                                         else ReaderError('Reader operation failed'))
                else:
                    with self._lock:
                        self._status['error'] = str(exc)
                        if action == 'sync' and self._serial:
                            self._serial.close()
            finally:
                with self._lock:
                    if action in ('begin', 'control', 'action', 'save', 'manage', 'inventory'):
                        self._mutation_count = max(0, self._mutation_count - 1)
                    self._paused = bool(self._draft_id) or self._mutation_count > 0 or not self._status['ready']

    def _available(self):
        if not self._status['ready']:
            raise ReaderError(self._status['error'] or 'Pico is not ready')

    @staticmethod
    def _is_async_error(words):
        """Recognize firmware errors emitted by reader work, not a host command."""
        if words[:3] == ['ERR', 'FP', 'ENROLL_CLEANUP']:
            return True
        if words[:2] == ['ERR', 'FP'] and len(words) > 2:
            return words[2] in {'PING', 'TIMEOUT', 'BADFRAME'} or words[2].startswith('0x')
        return False

    def _wait_cleanup(self):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            _, fields = packet(self._command('STATUS', 'STATUS '))
            if fields.get('cleanup') == 'OFF' and fields.get('learning') == 'OFF':
                return
            if self._stop.wait(.1):
                break
        raise ReaderError('Waiting for fingerprint cleanup; keep the Pico connected')

    def _registered(self, kind, identifier):
        with db.get_db() as conn:
            return conn.execute('SELECT 1 FROM credentials WHERE deleted_at IS NULL AND credential_type=? AND identifier=?',
                                (kind, identifier)).fetchone() is not None

    def _draft_credentials_saved(self, draft):
        credentials = self._credentials(draft)
        if not credentials:
            return False
        with db.get_db() as conn:
            for kind, identifier in credentials:
                query = 'SELECT user_id FROM credentials WHERE deleted_at IS NULL AND credential_type=? AND identifier=?'
                params = [kind, identifier]
                if draft['user_id'] is not None:
                    query += ' AND user_id=?'
                    params.append(draft['user_id'])
                if conn.execute(query, params).fetchone() is None:
                    return False
        return True

    def _wait_fingerprint_ready(self):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            fields = packet(self._command('STATUS', 'STATUS '))[1]
            if (fields.get('fp_state', fields.get('fp')) == 'READY'
                    and fields.get('cleanup') == 'OFF' and fields.get('learning') == 'OFF'):
                return
            if self._stop.wait(.1):
                break
        raise ReaderError('Fingerprint link must recover before maintenance')

    def _delete_template(self, value, *, allow_registered=False):
        value = template_id(value)
        if not allow_registered and value in self._cleanup_confirmed:
            return
        if not allow_registered and self._registered('fingerprint', f'template:{value}'):
            return  # DB commit may have succeeded before a process interruption.
        self._command('MODE MAINT')
        self._command('FP ENABLE')
        # Enabling/releasing a polling operation can leave a command in flight.
        self._wait_fingerprint_ready()
        self._deleting_id = value
        self._deleted_id = None
        try:
            self._command(f'FP DELETE {value}', f'OK FP DELETE id={value}')
        except ReaderError:
            # Firmware CANCEL/recovery may already have removed a provisional
            # ID; an explicit cleanup event or NO_TEMPLATE confirms that state.
            if value not in self._cleanup_confirmed:
                self._deleting_id = None
                raise
        # OK is acceptance; the asynchronous DELETE event confirms the result.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            with self._lock:
                if self._deleted_id == value or value in self._cleanup_confirmed:
                    self._cleanup_confirmed.add(value)
                    self._deleting_id = None
                    return
            self._stop.wait(.05)
        self._deleting_id = None
        raise ReaderError('Template cleanup was not confirmed')

    def fingerprint_inventory(self):
        with self._lock:
            return {'templates': None if self._inventory is None else sorted(self._inventory),
                    'checked_at': self._inventory_at,
                    'available': self._status['ready'] and self._status['connected']}

    def _list_templates(self):
        self._available()
        self._command('MODE MAINT')
        self._command('FP ENABLE')
        self._wait_fingerprint_ready()
        with self._lock:
            self._inventory_slots = set()
        try:
            # OK FP LIST only accepts the operation. LIST_END completes all 1000 slots.
            self._command('FP LIST', 'EVT FP LIST_END', timeout=120)
            with self._lock:
                self._inventory = set(self._inventory_slots)
                self._inventory_at = db.utcnow_iso()
                return sorted(self._inventory)
        finally:
            with self._lock:
                self._inventory_slots = None

    def _sync(self):
        self._command('PING', 'OK PONG')
        _, fields = packet(self._command('STATUS', 'STATUS '))
        if fields.get('fw') != '1' or 'fp_enabled' not in fields or 'cleanup' not in fields:
            raise ReaderError('Unsupported Pico firmware; flash firmware/labauth_pico')
        self._command('CANCEL')
        self._wait_cleanup()
        self._command('MODE IDLE')
        for draft in db.list_pending_drafts():
            if self._draft_credentials_saved(draft):
                # The enrollment transaction can commit just before process
                # shutdown, leaving the durable draft status one write behind.
                db.update_draft(draft['id'], status='committed', stage='ready', message='')
                db.set_setting('reader_candidate_' + draft['id'], None)
                continue
            candidate = draft['fp_template'] or db.get_setting('reader_candidate_' + draft['id'])
            if candidate:
                self._deleted_id = None
                self._delete_template(candidate)
            db.update_draft(draft['id'], status='cancelled', stage='error', message='Reader reconnected; start enrollment again')
            db.set_setting('reader_candidate_' + draft['id'], None)
        with self._lock:
            self._draft_id = None
            self._progress = {}
        self._restore_switches()
        self._command('MODE POLL')
        with self._lock:
            self._status.update(ready=True, error='')

    def _restore_switches(self):
        for kind, prefix in (('fingerprint', 'FP'), ('nfc', 'NFC')):
            self._command(prefix + (' ENABLE' if self._desired[kind] else ' DISABLE'))

    def _owned(self, draft_id, owner):
        draft = db.get_draft(draft_id, owner)
        if draft is None:
            raise ReaderError('Enrollment session not found')
        return draft

    def _view(self, draft):
        return {key: draft.get(key) for key in
                ('id', 'status', 'stage', 'fp_template', 'nfc_uid', 'user_id', 'message')} | {
                    'progress': copy.deepcopy(self._progress) if draft['id'] == self._draft_id else {},
                    'readers': self.status()}

    def draft(self, draft_id, owner):
        with self._lock:
            draft = self._owned(draft_id, owner)
            if draft['id'] == self._draft_id:
                expires = datetime.now(timezone.utc) + timedelta(minutes=30)
                draft = db.update_draft(draft_id, expires_at=db._iso_from_dt(expires))
            return self._view(draft)

    def _discard_fingerprint(self, draft):
        self._command('CANCEL')
        self._wait_cleanup()
        self._command('MODE IDLE')
        candidate = draft['fp_template'] or db.get_setting('reader_candidate_' + draft['id'])
        if candidate:
            self._deleted_id = None
            self._delete_template(candidate)
        db.set_setting('reader_candidate_' + draft['id'], None)
        self._restore_switches()
        self._command('MODE IDLE')
        db.update_draft(draft['id'], fp_template=None, stage='ready', status='active', message='')

    def _credentials(self, draft):
        result = []
        if draft['fp_template'] is not None:
            result.append(('fingerprint', f"template:{draft['fp_template']}"))
        if draft['nfc_uid']:
            result.append(('nfc', draft['nfc_uid']))
        return result

    def _execute(self, action, owner, data):
        if action == 'sync':
            return self._sync()
        if action == 'probe':
            if self._status['connected']:
                self._command('STATUS', 'STATUS ')
            return
        if action == 'expire':
            draft = db.get_draft(data['session'])
            if draft and self._draft_id == draft['id']:
                self._discard_fingerprint(draft)
                db.update_draft(draft['id'], status='cancelled', stage='error', message='Enrollment expired')
                self._draft_id = None
                self._command('MODE POLL')
            return
        if action in ('manage', 'inventory'):
            if self._draft_id:
                raise ReaderError('Finish or cancel enrollment before editing people')
            previous_mode = self._status.get('mode', 'POLL')
            switched = False
            def cleanup(identifiers):
                nonlocal switched
                if not identifiers:
                    return
                self._available()
                self._command('MODE IDLE')
                switched = True
                for identifier in identifiers:
                    value = template_id(identifier.removeprefix('template:'))
                    self._cleanup_confirmed.discard(value)
                    self._delete_template(value, allow_registered=True)
            try:
                if action == 'inventory' or data.get('verify_template') is not None:
                    switched = True
                    slots = self._list_templates()
                    if action == 'inventory':
                        return self.fingerprint_inventory()
                    if template_id(data['verify_template']) not in slots:
                        raise ReaderError('Template is not on the sensor. Refresh credentials and try again.')
                return data['change'](cleanup)
            finally:
                if switched and self._status['ready']:
                    try:
                        self._restore_switches()
                        self._command('MODE ' + previous_mode)
                    except ReaderError:
                        # Do not misreport an already committed change as failed.
                        # Reconnect/sync will restore the desired reader switches.
                        with self._lock:
                            self._status.update(ready=False, error='Reader reconnect required after maintenance')
                            if self._serial:
                                self._serial.close()
                        log.warning('People change completed; reader reconnect required')
        self._available()
        if action == 'control':
            mode = data.get('mode')
            if mode is not None:
                if mode not in ('POLL', 'CHECK', 'IDLE'):
                    raise ReaderError('Choose POLL, CHECK or IDLE')
                if self._draft_id:
                    raise ReaderError('Enrollment owns the readers')
                self._command('MODE ' + mode)
            else:
                kind, enabled = data.get('reader'), data.get('enabled')
                if kind not in self._desired or type(enabled) is not bool:
                    raise ReaderError('Choose a reader and enable state')
                self._desired[kind] = enabled
                db.set_setting('reader_fp_enabled' if kind == 'fingerprint' else 'reader_nfc_enabled',
                               'ON' if enabled else 'OFF')
                self._command(('FP' if kind == 'fingerprint' else 'NFC') + (' ENABLE' if enabled else ' DISABLE'))
                if self._draft_id and kind == 'fingerprint' and not enabled:
                    self._wait_cleanup()
                    draft = db.get_draft(self._draft_id)
                    if draft['stage'] in ('fingerprint', 'learning'):
                        db.update_draft(draft['id'], stage='error', message='Fingerprint reader disabled')
            db.log_audit('admin', 'reader_control', 'reader', after=data)
            self._command('STATUS', 'STATUS ')
            return self.status()
        if action == 'begin':
            user_id = data.get('user_id')
            if user_id is not None and (type(user_id) is not int or not db.get_user(user_id) or db.get_user(user_id).status != 'active'):
                raise ReaderError('Choose an active user')
            draft_id = db.create_draft(owner, user_id=user_id)
            self._draft_id = draft_id
            self._candidate_id = None
            self._finish_requested = False
            self._progress = {}
            try:
                self._command('MODE IDLE')
            except Exception:
                db.update_draft(draft_id, status='cancelled', stage='error', message='Could not acquire readers')
                self._draft_id = None
                raise
            return self._view(db.get_draft(draft_id))
        draft = self._owned(data.get('session', ''), owner)
        if draft['id'] != self._draft_id or draft['status'] in ('committed', 'cancelled'):
            raise ReaderError('Enrollment is no longer active')
        if action == 'save':
            if draft['stage'] not in ('idle', 'ready', 'error') or self._status.get('cleanup') == 'ON':
                raise ReaderError('Finish or skip the reader operation before saving')
            credentials = self._credentials(draft)
            result = data['save'](credentials)
            db.update_draft(draft['id'], status='committed', stage='ready')
            db.set_setting('reader_candidate_' + draft['id'], None)
            self._draft_id = None
            try:
                self._command('MODE POLL')
            except ReaderError:
                # The durable user/credential transaction is already committed.
                log.warning('Enrollment saved; Pico reconnect required to resume attendance')
            return result
        op = data.get('operation')
        if op == 'fingerprint':
            if not self._desired['fingerprint'] or self._status['fp'] not in ('READY', 'BUSY'):
                raise ReaderError('Fingerprint reader unavailable or disabled')
            if draft['stage'] in ('fingerprint', 'learning', 'cleanup') or draft['fp_template'] is not None:
                raise ReaderError('Fingerprint enrollment already started')
            if draft['stage'] == 'error':
                self._discard_fingerprint(draft)
            self._candidate_id = None
            self._finish_requested = False
            self._command('MODE ENROLL')
            db.update_draft(draft['id'], status='active', stage='fingerprint', message='Place finger on sensor')
            self._command('ENROLL')
        elif op == 'finish':
            if draft['stage'] != 'learning':
                raise ReaderError('Fingerprint is not in guided learning')
            self._finish_requested = True
            self._command('ENROLL FINISH')
        elif op == 'nfc':
            if not self._desired['nfc'] or self._status['nfc'] != 'READY':
                raise ReaderError('NFC reader unavailable or disabled')
            if draft['stage'] in ('fingerprint', 'learning', 'cleanup'):
                raise ReaderError('Finish or skip fingerprint enrollment first')
            self._command('MODE IDLE')
            db.update_draft(draft['id'], stage='nfc', status='active', message='Hold card to reader')
            self._command('NFC READ')
        elif op in ('cancel', 'skip_fingerprint'):
            self._discard_fingerprint(draft)
            if op == 'cancel':
                db.update_draft(draft['id'], status='cancelled', stage='error', message='Enrollment cancelled')
                self._draft_id = None
                self._command('MODE POLL')
        elif op == 'skip_nfc':
            if draft['stage'] in ('fingerprint', 'learning', 'cleanup'):
                raise ReaderError('Finish fingerprint enrollment first')
            self._command('CANCEL')
            self._command('MODE IDLE')
            db.update_draft(draft['id'], nfc_uid=None, stage='ready', message='')
        elif op == 'commit' and draft['user_id'] is not None:
            return self._execute('save', owner, dict(session=draft['id'], save=lambda values:
                {'credentials': db.attach_credentials(draft['user_id'], values)}))
        else:
            raise ReaderError('Unknown enrollment action')
        return self._view(db.get_draft(draft['id']))

    def _expire_draft(self):
        if not self._draft_id:
            return
        draft = db.get_draft(self._draft_id)
        if draft and db.iso_to_epoch(draft['expires_at']) < time.time():
            # Move expiry forward to avoid queuing the same cleanup every read tick.
            db.update_draft(draft['id'], expires_at=db._iso_from_dt(datetime.now(timezone.utc) + timedelta(minutes=1)))
            self._enqueue('expire', session=draft['id'])

    def handle_line(self, line):
        words, fields = packet(line)
        with self._lock:
            pending = self._pending
            if self._inventory_slots is not None:
                if words[:3] == ['EVT', 'FP', 'SLOT']:
                    self._inventory_slots.add(template_id(fields.get('id', '')))
                elif words[:1] == ['ERR'] or words[:3] in (['EVT', 'FP', 'CANCELLED'], ['EVT', 'FP', 'FAULT']):
                    if pending:
                        pending['error'] = line
                        pending['event'].set()
            if words[:1] == ['STATUS']:
                if 'fp' in fields and 'fp_state' not in fields:
                    self._status.pop('fp_state', None)
                for key in ('mode', 'fp', 'fp_state', 'nfc', 'cleanup', 'learning', 'led'):
                    if key in fields:
                        self._status[key] = fields[key]
            if words[:2] == ['OK', 'MODE'] and len(words) == 3:
                self._status['mode'] = words[2]
            if pending and (line == pending['expected'] or line.startswith(pending['expected'] + ' ')
                            or (pending['expected'].endswith(' ') and line.startswith(pending['expected']))):
                pending['line'] = line
                pending['event'].set()
            elif pending and words[:1] == ['ERR'] and not self._is_async_error(words):
                pending['error'] = line
                pending['event'].set()
            if words[:3] == ['ERR', 'FP', 'ENROLL_CLEANUP']:
                self._status['cleanup'] = 'ON'
            if (words[:4] == ['ERR', 'FP', '0x12', 'NO_TEMPLATE']
                    and self._deleting_id is not None):
                self._deleted_id = self._deleting_id
                self._cleanup_confirmed.add(self._deleting_id)
                if self._inventory is not None:
                    self._inventory.discard(self._deleting_id)
            if words[:1] == ['READY'] and self._status['ready']:
                self._status['ready'] = False
                self._paused = True
                self._enqueue('sync')
            if words[:3] == ['EVT', 'FP', 'DELETED']:
                self._deleted_id = template_id(fields.get('id', ''))
                self._cleanup_confirmed.add(self._deleted_id)
                if self._inventory is not None:
                    self._inventory.discard(self._deleted_id)
            if words[:3] == ['EVT', 'FP', 'ENROLL_CLEANED']:
                cleaned = template_id(fields.get('id', ''))
                self._cleanup_confirmed.add(cleaned)
                if self._deleting_id == cleaned:
                    self._deleted_id = cleaned
                self._status['cleanup'] = 'OFF'
            if words[:2] == ['EVT', 'FP'] and words[2:3] in (['READY'], ['FAULT']):
                self._status['fp'] = words[2]
                if 'fp_state' in self._status:
                    self._status['fp_state'] = words[2]
            if words[:2] == ['EVT', 'NFC'] and words[2:3] in (['READY'], ['ABSENT'], ['FAULT']):
                self._status['nfc'] = words[2]
            if self._draft_id and words[:1] in (['EVT'], ['ERR']):
                draft = db.get_draft(self._draft_id)
                if words[:3] == ['EVT', 'FP', 'PROGRESS'] and draft['stage'] in ('fingerprint', 'learning'):
                    self._progress = fields
                    if fields.get('phase') == 'FREE_ID':
                        value = template_id(fields.get('id', ''))
                        self._candidate_id = value
                        self._cleanup_confirmed.discard(value)
                        db.set_setting('reader_candidate_' + draft['id'], str(value))
                        if self._registered('fingerprint', f'template:{value}'):
                            db.update_draft(draft['id'], stage='error', message='Template ID already mapped; reconcile sensor and database')
                            self._enqueue('expire', session=draft['id'])
                    if fields.get('phase') == 'LEARN_READY':
                        if template_id(fields.get('id', '')) != self._candidate_id:
                            raise ReaderError('Enrollment template ID changed unexpectedly')
                        db.update_draft(draft['id'], stage='learning', message='Vary placement, then finish learning')
                elif words[:3] == ['EVT', 'FP', 'LEARN'] and draft['stage'] == 'learning':
                    self._progress = fields
                elif words[:3] == ['EVT', 'FP', 'ENROLLED'] and draft['stage'] == 'learning':
                    value = template_id(fields.get('id', ''))
                    if not self._finish_requested or value != self._candidate_id:
                        raise ReaderError('Unexpected enrollment completion')
                    if self._registered('fingerprint', f'template:{value}'):
                        db.update_draft(draft['id'], stage='error', message='Fingerprint ID already registered')
                    else:
                        db.update_draft(draft['id'], fp_template=value, stage='ready', status='complete', message='Fingerprint enrolled')
                elif words[:3] == ['EVT', 'NFC', 'UID'] and draft['stage'] == 'nfc':
                    value = card_uid(fields.get('uid', ''))
                    if self._registered('nfc', value):
                        db.update_draft(draft['id'], stage='error', message='Card is already enrolled')
                    else:
                        db.update_draft(draft['id'], nfc_uid=value, stage='ready', status='complete', message='Card registered')
                elif words[:3] == ['EVT', 'FP', 'DUPLICATE']:
                    db.update_draft(draft['id'], stage='error', message='This fingerprint is already enrolled. Use a different finger.')
                elif words[:1] == ['ERR'] and draft['stage'] in ('fingerprint', 'learning', 'nfc'):
                    db.update_draft(draft['id'], stage='error', message='Reader could not complete enrollment. Retry or skip.')
                return  # No enrollment traffic may become an attendance event.
            if self._paused or not self._status['ready']:
                return
            kind, identifier = None, None
            if words[:3] == ['EVT', 'FP', 'MATCH'] and self._desired['fingerprint']:
                kind, identifier = 'fingerprint', f"template:{template_id(fields.get('id', ''))}"
            elif words[:3] == ['EVT', 'NFC', 'UID'] and self._desired['nfc'] and self._status['mode'] == 'POLL':
                kind, identifier = 'nfc', card_uid(fields.get('uid', ''))
            elif words[:3] == ['EVT', 'FP', 'NOMATCH'] and self._desired['fingerprint']:
                self._feedback('fingerprint', 'Fingerprint not found', 'Please try again.', 'read_failure')
            elif words[:3] == ['EVT', 'FP', 'FAULT']:
                self._feedback('fingerprint', 'Fingerprint reader unavailable', 'Please contact an administrator.')
            elif words[:2] == ['ERR', 'NFC']:
                self._feedback('nfc', 'Card reader unavailable', 'Please try again or contact an administrator.')
            elif words[:2] == ['ERR', 'FP']:
                self._feedback('fingerprint', 'Fingerprint could not be read', 'Please try again.', 'read_failure')
            if kind and self._status['mode'] in ('POLL', 'CHECK'):
                result = process_credential(kind, identifier, self._status['mode'], self.device_id)
                if result['outcome'] == 'success':
                    if result['event']['type'] == 'CHECK':
                        self._publish(source=kind, **result['event'])
                    # IN/OUT are read directly from immutable DB history by both displays.
                elif result['outcome'] != 'cooldown':
                    title = 'Fingerprint not found' if kind == 'fingerprint' else 'Card UID not found'
                    message = 'Please try again.' if kind == 'fingerprint' else 'Please contact admin for enrollment.'
                    if result['outcome'] == 'denied':
                        title, message = 'Access not authorised', 'Please contact an administrator.'
                    self._publish(type='ERROR', source=kind, title=title, message=message)


service = None  # Constructed after database initialization by main.py.
