"""Validated, audited People mutations; history remains append-only."""
from __future__ import annotations

import base64
import binascii
import io
import json
import re
import uuid

from PIL import Image, UnidentifiedImageError
import database as db


class MissingPerson(ValueError):
    pass


def _photo(value):
    if value in (None, '', db.DEFAULT_PHOTO):
        return db.DEFAULT_PHOTO, None
    if not isinstance(value, str) or not value.startswith('data:image/png;base64,') or len(value) > 12 * 1024 * 1024:
        raise ValueError('Choose a PNG photo under 8 MB')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'PNG' or max(image.size) > 2048:
                raise ValueError('Choose a PNG photo up to 2048 pixels')
            image.load()
            output = io.BytesIO()
            image.convert('RGB').save(output, format='PNG')
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Choose a valid photo') from exc
    path = db.project_root() / 'src' / 'static' / 'portraits' / f'portrait_{uuid.uuid4().hex}.png'
    return f'/static/portraits/{path.name}', (path, output.getvalue())


def _audit(conn, action, kind, record_id, before, after):
    conn.execute('''INSERT INTO admin_audit_log
        (occurred_at,actor,action,entity_type,entity_id,before,after)
        VALUES (?,'admin',?,?,?,?,?)''',
        (db.utcnow_iso(), action, kind, str(record_id), json.dumps(before), json.dumps(after)))


def _person(conn, user_id):
    user = conn.execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL', (user_id,)).fetchone()
    if user is None:
        raise MissingPerson('User not found')
    return dict(user)


def edit_person(user_id, changes, cleanup=lambda identifiers: None):
    if not isinstance(changes, dict) or len(changes) != 1:
        raise ValueError('Edit one entry at a time')
    key, value = next(iter(changes.items()))
    file = None
    if key in ('name', 'plaksha_id', 'email', 'phone'):
        limit = {'name': 200, 'plaksha_id': 100, 'email': 254, 'phone': 100}[key]
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f'Check {key.replace("_", " ")}')
        value = value.strip() if value else None
        if key == 'name' and not value:
            raise ValueError('Name is required')
        if key == 'email' and value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email')
    elif key == 'status':
        if value not in ('active', 'inactive'):
            raise ValueError('Choose Active or Inactive')
    elif key == 'is_temp':
        if type(value) is not bool:
            raise ValueError('Choose Member or Visitor')
    elif key == 'photo':
        value, file = _photo(value)
    elif key not in ('access_area_ids', 'credential', 'add_credential', 'ban'):
        raise ValueError('This entry is read-only')
    try:
        with db.get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            user = _person(conn, user_id)
            now = db.utcnow_iso()
            if key == 'access_area_ids':
                if not isinstance(value, list) or len(value) > 100 or any(type(i) is not int for i in value):
                    raise ValueError('Check authorised areas')
                areas = {r[0] for r in conn.execute('SELECT id FROM access_areas')}
                if not set(value) <= areas:
                    raise ValueError('Unknown access area')
                before = [r[0] for r in conn.execute('SELECT area_id FROM user_access_areas WHERE user_id=?', (user_id,))]
                conn.execute('DELETE FROM user_access_areas WHERE user_id=?', (user_id,))
                conn.executemany('INSERT INTO user_access_areas (user_id,area_id,granted_at,granted_by) VALUES (?,?,?,\'admin\')',
                                 [(user_id, i, now) for i in dict.fromkeys(value)])
                _audit(conn, 'edit_access', 'user', user_id, before, value)
            elif key == 'credential':
                if not isinstance(value, dict) or set(value) - {'id', 'identifier', 'is_active', 'delete'} or type(value.get('id')) is not int:
                    raise ValueError('Check credential')
                row = conn.execute('SELECT id,identifier,credential_type,is_active FROM credentials WHERE id=? AND user_id=? AND deleted_at IS NULL', (value['id'], user_id)).fetchone()
                if row is None:
                    raise MissingPerson('Credential not found')
                before = dict(row)
                if value.get('delete') is True:
                    if set(value) != {'id', 'delete'}:
                        raise ValueError('Check credential deletion')
                    cleanup([row['identifier']] if row['credential_type'] == 'fingerprint' else [])
                    conn.execute('UPDATE credentials SET deleted_at=?,is_active=0 WHERE id=?', (now, row['id']))
                    _audit(conn, 'delete_credential', 'credential', row['id'], before, None)
                else:
                    identifier = value.get('identifier', row['identifier'])
                    identifier = db.normalize_credential(row['credential_type'], identifier)
                    if row['credential_type'] == 'nfc' and not re.fullmatch(r'(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})', identifier):
                        raise ValueError('Enter a 4, 7 or 10 byte NFC UID')
                    if row['credential_type'] == 'fingerprint' and not re.fullmatch(r'template:[0-9]+', identifier):
                        raise ValueError('Enter a fingerprint template ID between 1 and 1000')
                    active = value.get('is_active', bool(row['is_active']))
                    if type(active) is not bool:
                        raise ValueError('Check credential status')
                    conn.execute('UPDATE credentials SET identifier=?,is_active=? WHERE id=?', (identifier, int(active), row['id']))
                    _audit(conn, 'edit_credential', 'credential', row['id'], before, {'identifier': identifier, 'is_active': active})
            elif key == 'add_credential':
                if not isinstance(value, dict) or set(value) - {'credential_type', 'identifier', 'is_active'}:
                    raise ValueError('Check credential')
                cred_type = value.get('credential_type', 'fingerprint')
                if cred_type not in ('nfc', 'fingerprint'):
                    raise ValueError('Choose NFC or fingerprint')
                identifier = db.normalize_credential(cred_type, value.get('identifier', ''))
                if cred_type == 'nfc' and not re.fullmatch(r'(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})', identifier):
                    raise ValueError('Enter a 4, 7 or 10 byte NFC UID')
                if cred_type == 'fingerprint' and not re.fullmatch(r'template:[0-9]+', identifier):
                    raise ValueError('Enter a fingerprint template ID between 1 and 1000')
                active = bool(value.get('is_active', True))
                dup = conn.execute(
                    'SELECT u.name, u.id FROM credentials c JOIN users u ON u.id = c.user_id WHERE c.deleted_at IS NULL AND c.credential_type=? AND c.identifier=?',
                    (cred_type, identifier)
                ).fetchone()
                if dup:
                    raise ValueError(f'This {cred_type} credential is already assigned to {dup["name"]} (ID {dup["id"]}).')
                cur = conn.execute(
                    'INSERT INTO credentials (user_id, credential_type, identifier, template, is_active, enrolled_at) VALUES (?, ?, ?, NULL, ?, ?)',
                    (user_id, cred_type, identifier, int(active), now)
                )
                _audit(conn, 'add_credential', 'credential', cur.lastrowid, None, {'user_id': user_id, 'identifier': identifier, 'type': cred_type})
            elif key == 'ban':
                if not isinstance(value, dict) or type(value.get('id')) is not int or set(value) - {'id', 'reason', 'banned_by', 'lift'}:
                    raise ValueError('Check ban')
                row = conn.execute('SELECT * FROM bans WHERE id=? AND user_id=?', (value['id'], user_id)).fetchone()
                if row is None:
                    raise MissingPerson('Ban not found')
                for field in ('reason', 'banned_by'):
                    if field in value and (not isinstance(value[field], str) or len(value[field]) > 1000):
                        raise ValueError('Check ban details')
                if value.get('lift') is True:
                    conn.execute('UPDATE bans SET unbanned_at=COALESCE(unbanned_at,?) WHERE id=?', (now, row['id']))
                else:
                    conn.execute('UPDATE bans SET reason=?,banned_by=? WHERE id=?', (value.get('reason', row['reason']), value.get('banned_by', row['banned_by']), row['id']))
                _audit(conn, 'edit_ban', 'ban', row['id'], dict(row), value)
            else:
                conn.execute(f'UPDATE users SET {key}=? WHERE id=?', (value, user_id))
                if key == 'status' and value == 'inactive':
                    _checkout(conn, user_id, now)
                _audit(conn, 'edit_user', 'user', user_id, {key: user[key]}, {key: value})
            conn.execute('UPDATE users SET updated_at=? WHERE id=?', (now, user_id))
            if file:
                file[0].parent.mkdir(parents=True, exist_ok=True)
                file[0].write_bytes(file[1])
    except Exception:
        if file:
            file[0].unlink(missing_ok=True)
        raise


def _checkout(conn, user_id, now):
    if conn.execute('SELECT 1 FROM current_presence WHERE user_id=?', (user_id,)).fetchone():
        conn.execute("INSERT INTO presence_log (user_id,event_type,entry_method,occurred_at,metadata) VALUES (?,'check_out','manual',?,?)",
                     (user_id, now, json.dumps({'reason': 'admin removed access'})))
        conn.execute('DELETE FROM current_presence WHERE user_id=?', (user_id,))


def delete_people(ids, cleanup=lambda identifiers: None):
    if not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or any(type(i) is not int or i < 1 for i in ids):
        raise ValueError('Select between 1 and 1000 people')
    ids = list(dict.fromkeys(ids))
    with db.get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        users = [_person(conn, i) for i in ids]
        placeholders = ','.join('?' for _ in ids)
        fingerprints = [r[0] for r in conn.execute(f"SELECT identifier FROM credentials WHERE user_id IN ({placeholders}) AND credential_type='fingerprint' AND deleted_at IS NULL", ids)]
        cleanup(fingerprints)
        now = db.utcnow_iso()
        for user in users:
            _checkout(conn, user['id'], now)
            conn.execute("UPDATE users SET deleted_at=?,status='inactive',updated_at=? WHERE id=?", (now, now, user['id']))
            conn.execute('UPDATE credentials SET deleted_at=?,is_active=0 WHERE user_id=? AND deleted_at IS NULL', (now, user['id']))
            conn.execute('DELETE FROM user_access_areas WHERE user_id=?', (user['id'],))
            _audit(conn, 'delete_user', 'user', user['id'], {'name': user['name'], 'plaksha_id': user['plaksha_id']}, None)
    return ids
