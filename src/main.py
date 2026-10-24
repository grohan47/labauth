import json
import asyncio
import hashlib
import sys
import time
from datetime import datetime
from pathlib import Path

from nicegui import app, ui
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse

import database as db
from presence import store
from ui.admin_display import (
    admin_password_is_valid,
    build_admin_display,
    build_admin_panel,
    create_admin_session,
    destroy_admin_session,
    is_admin_session_valid,
)
from ui.display import build_display, presence_signature, render_presence_html
from ui.display_settings import build_display_settings_page
from ui.enrolment import build_enrolment_page
from ui.logs import build_logs_page
from ui.search import build_search_page
from ui.credentials import build_credentials_page
from services.user_queries import search_users, user_details
from services.people import edit_person, delete_people, MissingPerson
from services.log_queries import query_visits, query_sql, database_schema
from services.pico import PicoService, ReaderError
from ui.lyne import asset_url, button, container, element, form_field, lyne_assets

SESSION_COOKIE_NAME = "labauth_admin_session"
readers = PicoService()
app.on_startup(readers.start)
app.on_shutdown(readers.stop)


def request_has_valid_admin_session(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return is_admin_session_valid(token)


def reader_owner(request: Request) -> str:
    return hashlib.sha256(request.cookies.get(SESSION_COOKIE_NAME, '').encode()).hexdigest()


def reader_guard(request: Request):
    if not request_has_valid_admin_session(request):
        return JSONResponse({'detail': 'Admin session required'}, status_code=401)
    origin = request.headers.get('origin')
    if request.method != 'GET' and origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail': 'Same-origin request required'}, status_code=403)
    return None


@app.get('/api/readers/events')
def api_reader_events(request: Request):
    try:
        since = max(0, int(request.query_params.get('since', '0')))
    except ValueError:
        since = 0
    return JSONResponse(readers.events(since), headers={'Cache-Control': 'no-store'})


@app.get('/api/readers/status')
def api_reader_status(request: Request):
    return reader_guard(request) or JSONResponse(readers.status(), headers={'Cache-Control': 'no-store'})


@app.post('/api/readers/control')
async def api_reader_control(request: Request):
    if denied := reader_guard(request):
        return denied
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) not in ({'mode'}, {'reader', 'enabled'}):
            raise ReaderError('Choose a reader switch or mode')
        result = await asyncio.to_thread(readers.call, 'control', **body)
        return JSONResponse(result)
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({'detail': str(exc)}, status_code=409)


@app.post('/api/readers/enrolments')
async def api_reader_enrolment_start(request: Request):
    if denied := reader_guard(request):
        return denied
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) - {'user_id'}:
            raise ReaderError('Invalid enrollment request')
        result = await asyncio.to_thread(readers.call, 'begin', owner=reader_owner(request), **body)
        return JSONResponse(result)
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({'detail': str(exc)}, status_code=409)


@app.get('/api/readers/enrolments/{session_id}')
def api_reader_enrolment_state(session_id: str, request: Request):
    if denied := reader_guard(request):
        return denied
    try:
        return JSONResponse(readers.draft(session_id, reader_owner(request)), headers={'Cache-Control': 'no-store'})
    except ReaderError as exc:
        return JSONResponse({'detail': str(exc)}, status_code=404)


@app.post('/api/readers/enrolments/{session_id}')
async def api_reader_enrolment_action(session_id: str, request: Request):
    if denied := reader_guard(request):
        return denied
    if db.get_draft(session_id, reader_owner(request)) is None:
        return JSONResponse({'detail': 'Enrollment session not found'}, status_code=404)
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {'action'} or not isinstance(body['action'], str):
            raise ReaderError('Invalid enrollment action')
        result = await asyncio.to_thread(readers.call, 'action', owner=reader_owner(request),
                                         session=session_id, operation=body['action'])
        return JSONResponse(result)
    except (ValueError, RuntimeError) as exc:
        return JSONResponse({'detail': str(exc)}, status_code=409)


if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
else:
    BASE_DIR = Path(__file__).resolve().parent

STATIC_ROOT = BASE_DIR / "static" if (BASE_DIR / "static").exists() else BASE_DIR / "src" / "static"
if not STATIC_ROOT.exists():
    STATIC_ROOT = Path(__file__).resolve().parent / "static"

# Portrait paths in the shared database must also work on the main display.
shared_root = db.shared_project_root()
PORTRAIT_ROOT = STATIC_ROOT / "portraits"
if not getattr(sys, "frozen", False) and db.db_path().resolve() == (shared_root / "data" / "labauth.db").resolve():
    PORTRAIT_ROOT = shared_root / "src" / "static" / "portraits"
app.add_static_files("/static/portraits", PORTRAIT_ROOT, max_cache_age=0)
app.add_static_files("/static", STATIC_ROOT, max_cache_age=0)


@app.get("/api/presence")
def api_get_presence() -> JSONResponse:
    people = store.get_people()
    return JSONResponse({
        "count": len(people),
        "people": [p.to_dict() for p in people],
    })


@app.get("/api/presence/render")
def api_render_presence(request: Request) -> JSONResponse:
    """Server-rendered card markup plus a signature, for in-place client sync.

    The requesting display passes its ``screen`` target so the cards keep the
    persisted visibility settings instead of reverting to defaults.
    """
    screen = request.query_params.get("screen", "display")
    if screen not in db.SCREEN_TARGETS:
        screen = "display"
    people = store.get_people()
    settings = db.get_screen_settings(screen)
    return JSONResponse({
        "signature": presence_signature(people) + json.dumps(settings, sort_keys=True),
        "settings": settings,
        "html": render_presence_html(people, settings=settings),
    })


@app.get("/api/presence/events")
def api_get_presence_events(request: Request) -> JSONResponse:
    try:
        since = int(request.query_params.get("since", 0))
    except (ValueError, TypeError):
        since = 0
    events = store.get_events(since_id=since, max_age_seconds=20.0)
    return JSONResponse({"events": events})


@app.post("/api/presence/check-in")
async def api_check_in(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = str(data.get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "Missing 'name' in request body"}, status_code=400)

    photo = str(data.get("photo", "/static/portraits/default.svg"))
    access = tuple(data.get("access", ["Indoor lab", "Tool Area"]))
    checked_in = data.get("checked_in")
    if checked_in:
        checked_in = str(checked_in).strip()
    plaksha_id = data.get("plaksha_id")
    if plaksha_id:
        plaksha_id = str(plaksha_id).strip()
    phone = data.get("phone")
    if phone:
        phone = str(phone).strip()
    person = store.check_in(
        name=name,
        photo=photo,
        access=access,
        checked_in=checked_in,
        is_temp=bool(data.get("is_temp", False)),
        plaksha_id=plaksha_id,
        phone=phone,
    )
    return JSONResponse({
        "status": "ok",
        "person": person.to_dict(),
        "total_count": len(store.get_people()),
    })


@app.post("/api/presence/check-out")
async def api_check_out(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = str(data.get("name", "")).strip()
    if not name:
        return JSONResponse({"error": "Missing 'name' in request body"}, status_code=400)

    check_out_time = data.get("check_out") or data.get("time")
    if check_out_time:
        check_out_time = str(check_out_time).strip()

    removed, person, out_time = store.check_out(name, check_out_time=check_out_time)
    return JSONResponse({
        "status": "ok",
        "removed": removed,
        "name": name,
        "person": person.to_dict() if person else None,
        "check_out": out_time,
        "total_count": len(store.get_people()),
    })


@app.post("/api/presence/reset")
def api_presence_reset() -> JSONResponse:
    store.reset()
    return JSONResponse({
        "status": "ok",
        "total_count": len(store.get_people()),
    })


@app.post("/api/presence/populate")
async def api_presence_populate(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        count = int(data.get("count", 8))
    except (ValueError, TypeError):
        count = 8
    count = max(0, min(count, 48))
    people = store.populate(count)
    return JSONResponse({
        "status": "ok",
        "count": count,
        "total_count": len(people),
    })


@app.post("/api/admin/login")
async def api_admin_login(request: Request) -> JSONResponse:
    """Check the admin password (labauth@2026) and issue session cookie."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    password = str(data.get("password", ""))
    if not admin_password_is_valid(password):
        return JSONResponse({"error": "Incorrect password."}, status_code=401)
    token = create_admin_session()
    db.log_audit("admin", "admin_login", "session")
    resp = JSONResponse({"status": "ok", "redirect": "/admin"})
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=3600,
    )
    return resp


@app.post("/api/admin/logout")
def api_admin_logout_post(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    destroy_admin_session(token)
    resp = JSONResponse({"status": "ok", "redirect": "/admin-display"})
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp


@app.get("/api/admin/logout")
def api_admin_logout_get(request: Request) -> RedirectResponse:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    destroy_admin_session(token)
    resp = RedirectResponse("/admin-display")
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp


@app.get("/api/alerts")
def api_get_alerts() -> JSONResponse:
    """Active alerts for the displays and the admin pane (public read)."""
    return JSONResponse({
        "status": "ok",
        "alerts": store.get_alerts(),
    })


def _alert_payload(data: dict) -> dict:
    """Extract and validate alert fields for create/update requests."""
    fields: dict = {}
    if "message" in data:
        message = str(data.get("message") or "").strip()
        if not message:
            raise ValueError("Enter an alert message.")
        if len(message) > db.ALERT_MAX_LENGTH:
            raise ValueError(f"Keep the message under {db.ALERT_MAX_LENGTH} characters.")
        fields["message"] = message
    if "severity" in data:
        severity = str(data.get("severity") or "").strip().lower()
        if severity not in db.ALERT_SEVERITIES:
            raise ValueError("Choose a valid severity.")
        fields["severity"] = severity
    update_ttl = "ttl_seconds" in data
    ttl = data.get("ttl_seconds")
    if update_ttl and ttl not in (None, "", "none"):
        try:
            ttl = int(ttl)
        except (TypeError, ValueError):
            raise ValueError("Choose a valid expiry.")
        if ttl < 0:
            raise ValueError("Choose a valid expiry.")
    else:
        ttl = None
    return {"fields": fields, "ttl": ttl, "update_ttl": update_ttl}


@app.post("/api/alerts")
async def api_post_alerts(request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    try:
        payload = _alert_payload(data)
        message = payload["fields"].get("message")
        severity = payload["fields"].get("severity", "info")
        alert = store.add_alert(message, severity, ttl_seconds=payload["ttl"])
    except ValueError as err:
        return JSONResponse({"error": str(err)}, status_code=422)
    db.log_audit(
        "admin",
        "alert_created",
        "alert",
        entity_id=str(alert["id"]),
        after={"message": alert["message"], "severity": alert["severity"]},
    )
    return JSONResponse({"status": "ok", "alert": alert})


@app.put("/api/alerts/{alert_id}")
async def api_put_alert(alert_id: int, request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    if db.get_alert(alert_id) is None:
        return JSONResponse({"error": "Alert not found"}, status_code=404)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    try:
        payload = _alert_payload(data)
    except ValueError as err:
        return JSONResponse({"error": str(err)}, status_code=422)
    fields = payload["fields"]
    if not fields and not payload["update_ttl"]:
        return JSONResponse({"error": "Nothing to update"}, status_code=422)
    alert = store.update_alert(
        alert_id,
        message=fields.get("message"),
        severity=fields.get("severity"),
        ttl_seconds=payload["ttl"],
        update_ttl=payload["update_ttl"],
    )
    db.log_audit(
        "admin",
        "alert_updated",
        "alert",
        entity_id=str(alert_id),
        after={"message": fields.get("message"), "severity": fields.get("severity"),
               "ttl_seconds": payload["ttl"] if payload["update_ttl"] else None},
    )
    return JSONResponse({"status": "ok", "alert": alert})


@app.delete("/api/alerts/{alert_id}")
def api_delete_alert(alert_id: int, request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    previous = db.get_alert(alert_id)
    if previous is None:
        return JSONResponse({"error": "Alert not found"}, status_code=404)
    store.delete_alert(alert_id)
    db.log_audit(
        "admin",
        "alert_deleted",
        "alert",
        entity_id=str(alert_id),
        before={"message": previous.message, "severity": previous.severity},
    )
    return JSONResponse({"status": "ok", "alerts": store.get_alerts()})


@app.get("/api/access-areas")
def api_list_access_areas() -> JSONResponse:
    db.init_db()
    areas = db.list_access_areas()
    return JSONResponse({
        "status": "ok",
        "access_areas": [
            {"id": a.id, "code": a.code, "label": a.label, "sort_order": a.sort_order}
            for a in areas
        ],
    })


@app.post("/api/enrolment/complete")
async def api_enrolment_complete(request: Request) -> JSONResponse:
    if denied := reader_guard(request):
        return denied
    import base64
    import binascii
    import io
    import re
    import sqlite3
    import uuid
    from PIL import Image, UnidentifiedImageError

    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid enrolment")
        fields = {}
        for field, limit in (("name", 200), ("plaksha_id", 100), ("phone", 100), ("email", 254)):
            value = data.get(field) or ""
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f"Check {field.replace('_', ' ')}")
            fields[field] = value.strip()
        if not fields["name"]:
            raise ValueError("Enter your full name")
        if fields["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["email"]):
            raise ValueError("Enter a valid email")
        area_ids = data.get("access_area_ids", [])
        if not isinstance(area_ids, list) or len(area_ids) > 100 or any(type(i) is not int for i in area_ids):
            raise ValueError("Check authorised areas")
        # The browser cannot assert reader success or supply invented credentials.
        if data.get("fingerprint_enrolled") or data.get("nfc_uid") or data.get("credentials"):
            raise ValueError("Reader credentials must come from an enrollment session")
        reader_session = data.get('reader_session')
        if reader_session is not None and (not isinstance(reader_session, str) or len(reader_session) > 100):
            raise ValueError('Invalid reader session')
        if data.get("access") or data.get("is_temp"):
            raise ValueError("Reload enrolment to use the current fields")
        photo = data.get("photo") or db.DEFAULT_PHOTO
        if not isinstance(photo, str):
            raise ValueError("Choose a valid photo")
        image_bytes = None
        if photo != db.DEFAULT_PHOTO:
            if not photo.startswith("data:image/png;base64,") or len(photo) > 12 * 1024 * 1024:
                raise ValueError("Choose a valid photo under 8 MB")
            try:
                decoded = base64.b64decode(photo.split(",", 1)[1], validate=True)
                with Image.open(io.BytesIO(decoded)) as image:
                    if image.format != "PNG" or image.width > 2048 or image.height > 2048:
                        raise ValueError("Choose a valid photo")
                    image.load()
                    output = io.BytesIO()
                    image.convert("RGB").save(output, format="PNG")
                    image_bytes = output.getvalue()
            except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as err:
                raise ValueError("Choose a valid photo") from err
    except (ValueError, TypeError) as err:
        return JSONResponse({"detail": str(err)}, status_code=422)

    destination = None
    try:
        if image_bytes is not None:
            destination = PORTRAIT_ROOT / f"portrait_{uuid.uuid4().hex}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(image_bytes)
            photo = f"/static/portraits/{destination.name}"
        if reader_session:
            record = await asyncio.to_thread(
                readers.call, 'save', owner=reader_owner(request), session=reader_session,
                save=lambda credentials: db.create_enrolment(
                    **fields, photo=photo, access_area_ids=area_ids, credentials=credentials))
        else:
            record = db.create_enrolment(**fields, photo=photo, access_area_ids=area_ids)
    except (ValueError, sqlite3.IntegrityError) as err:
        if destination:
            destination.unlink(missing_ok=True)
        detail = str(err) if isinstance(err, ValueError) else db.duplicate_error(err)
        return JSONResponse({"detail": detail}, status_code=409)
    except Exception:
        if destination:
            destination.unlink(missing_ok=True)
        return JSONResponse({"detail": "Could not save. Try again."}, status_code=500)
    return JSONResponse({"status": "ok", "user": record})



@app.get('/api/credentials')
def api_list_credentials(request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({'error': 'Admin session required'}, status_code=401)
    cred_type = request.query_params.get('type')
    q = request.query_params.get('q')
    try:
        limit = min(100, max(1, int(request.query_params.get('limit', 100))))
        offset = max(0, int(request.query_params.get('offset', 0)))
    except (ValueError, TypeError):
        limit, offset = 100, 0
    inventory = readers.fingerprint_inventory()
    creds, total = db.list_credentials_with_users(credential_type=cred_type or None, query=q or None,
        limit=limit, offset=offset, sensor_templates=inventory['templates'])
    return JSONResponse({'credentials': creds, 'total': total, 'limit': limit, 'offset': offset,
                         'sensor': {k: v for k, v in inventory.items() if k != 'templates'}})


@app.post('/api/credentials/refresh')
async def api_refresh_credentials(request: Request) -> JSONResponse:
    if denied := reader_guard(request):
        return denied
    try:
        inventory = await asyncio.to_thread(readers.call, 'inventory')
        return JSONResponse(inventory)
    except ValueError as err:
        return JSONResponse({'error': str(err)}, status_code=409)


@app.delete('/api/credentials/sensor/{slot}')
async def api_delete_sensor_credential(slot: int, request: Request) -> JSONResponse:
    if denied := reader_guard(request):
        return denied
    try:
        from services.pico import template_id
        slot = template_id(slot)
        def remove(cleanup):
            identifier = f'template:{slot}'
            with db.get_db() as conn:
                if conn.execute("SELECT 1 FROM credentials WHERE deleted_at IS NULL AND credential_type='fingerprint' AND identifier=?", (identifier,)).fetchone():
                    raise ValueError('Template has been assigned. Refresh credentials before deleting.')
                cleanup([identifier])
                db.log_audit('admin', 'delete_sensor_template', 'credential', entity_id=identifier,
                             before={'identifier': identifier})
        await asyncio.to_thread(readers.call, 'manage', change=remove)
        return JSONResponse({'status': 'ok'})
    except ValueError as err:
        return JSONResponse({'error': str(err)}, status_code=409)


@app.post('/api/credentials')
async def api_create_credential(request: Request) -> JSONResponse:
    if denied := reader_guard(request):
        return denied
    import re, sqlite3
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        cred_type = str(data.get('credential_type', 'fingerprint')).strip()
        identifier = str(data.get('identifier', '')).strip()
        is_active = bool(data.get('is_active', True))
        if cred_type not in ('nfc', 'fingerprint'):
            raise ValueError('Invalid credential type')
        identifier = db.normalize_credential(cred_type, identifier)
        if cred_type == 'nfc' and not re.fullmatch(r'(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})', identifier):
            raise ValueError('Enter a 4, 7 or 10 byte NFC UID')
        if cred_type == 'fingerprint' and not re.fullmatch(r'template:[0-9]+', identifier):
            raise ValueError('Enter a fingerprint template ID between 1 and 1000')
        def create(cleanup):
            now = db.utcnow_iso()
            with db.get_db() as conn:
                user = conn.execute('SELECT id, name FROM users WHERE id=? AND deleted_at IS NULL', (user_id,)).fetchone()
                if not user:
                    raise ValueError('User not found')
                dup = conn.execute('SELECT u.name FROM credentials c JOIN users u ON u.id=c.user_id WHERE c.deleted_at IS NULL AND c.credential_type=? AND c.identifier=?', (cred_type, identifier)).fetchone()
                if dup:
                    raise ValueError(f'Credential already assigned to {dup["name"]}')
                cur = conn.execute('INSERT INTO credentials (user_id, credential_type, identifier, is_active, enrolled_at) VALUES (?, ?, ?, ?, ?)', (user_id, cred_type, identifier, int(is_active), now))
                cred_id = cur.lastrowid
                conn.execute("INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after) VALUES (?, 'admin', 'create_credential', 'credential', ?, NULL, ?)",
                             (now, str(cred_id), json.dumps({'user_id': user_id, 'identifier': identifier, 'type': cred_type})))
            return cred_id
        verify = int(identifier.split(':')[1]) if cred_type == 'fingerprint' else None
        cred_id = await asyncio.to_thread(readers.call, 'manage', change=create, verify_template=verify)
        return JSONResponse({'status': 'ok', 'id': cred_id})
    except (ValueError, TypeError) as err:
        return JSONResponse({'error': str(err)}, status_code=422)
    except sqlite3.IntegrityError as err:
        return JSONResponse({'error': db.duplicate_error(err)}, status_code=409)


@app.patch('/api/credentials/{credential_id}')
async def api_patch_credential(credential_id: int, request: Request) -> JSONResponse:
    if denied := reader_guard(request):
        return denied
    import re, sqlite3
    try:
        data = await request.json()
        def change(cleanup):
            now = db.utcnow_iso()
            with db.get_db() as conn:
                row = conn.execute('SELECT * FROM credentials WHERE id=? AND deleted_at IS NULL', (credential_id,)).fetchone()
                if not row:
                    raise ValueError('Credential not found')
                before = dict(row)
                updates = {}
                if 'identifier' in data:
                    ident = db.normalize_credential(row['credential_type'], data['identifier'])
                    if row['credential_type'] == 'fingerprint' and ident != row['identifier']:
                        raise ValueError('Assign an existing sensor template instead of changing its ID')
                    if row['credential_type'] == 'nfc' and not re.fullmatch(r'(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})', ident):
                        raise ValueError('Enter a 4, 7 or 10 byte NFC UID')
                    if row['credential_type'] == 'fingerprint' and not re.fullmatch(r'template:[0-9]+', ident):
                        raise ValueError('Enter a fingerprint template ID between 1 and 1000')
                    dup = conn.execute('SELECT u.name FROM credentials c JOIN users u ON u.id=c.user_id WHERE c.deleted_at IS NULL AND c.credential_type=? AND c.identifier=? AND c.id!=?', (row['credential_type'], ident, credential_id)).fetchone()
                    if dup:
                        raise ValueError(f'Credential already assigned to {dup["name"]}')
                    updates['identifier'] = ident
                if 'is_active' in data:
                    updates['is_active'] = int(bool(data['is_active']))
                if 'user_id' in data:
                    new_uid = int(data['user_id'])
                    if not conn.execute('SELECT id FROM users WHERE id=? AND deleted_at IS NULL', (new_uid,)).fetchone():
                        raise ValueError('Target user not found')
                    updates['user_id'] = new_uid
                if updates:
                    set_clauses = ', '.join(f'{k}=?' for k in updates)
                    conn.execute(f'UPDATE credentials SET {set_clauses} WHERE id=?', (*updates.values(), credential_id))
                    conn.execute("INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after) VALUES (?, 'admin', 'update_credential', 'credential', ?, ?, ?)",
                                 (now, str(credential_id), json.dumps({k: before[k] for k in updates if k in before}), json.dumps(updates)))
        await asyncio.to_thread(readers.call, 'manage', change=change)
        return JSONResponse({'status': 'ok'})
    except (ValueError, TypeError) as err:
        return JSONResponse({'error': str(err)}, status_code=422)
    except sqlite3.IntegrityError as err:
        return JSONResponse({'error': db.duplicate_error(err)}, status_code=409)


@app.delete('/api/credentials/{credential_id}')
async def api_delete_credential(credential_id: int, request: Request) -> JSONResponse:
    if denied := reader_guard(request):
        return denied
    try:
        def do_delete(cleanup):
            now = db.utcnow_iso()
            with db.get_db() as conn:
                row = conn.execute('SELECT * FROM credentials WHERE id=? AND deleted_at IS NULL', (credential_id,)).fetchone()
                if not row:
                    raise ValueError('Credential not found')
                if row['credential_type'] == 'fingerprint':
                    cleanup([row['identifier']])
                conn.execute('UPDATE credentials SET deleted_at=?, is_active=0 WHERE id=?', (now, credential_id))
                conn.execute("INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after) VALUES (?, 'admin', 'delete_credential', 'credential', ?, ?, NULL)",
                             (now, str(credential_id), json.dumps({'identifier': row['identifier'], 'type': row['credential_type']})))
        await asyncio.to_thread(readers.call, 'manage', change=do_delete)
        return JSONResponse({'status': 'ok'})
    except ValueError as err:
        return JSONResponse({'error': str(err)}, status_code=404 if 'not found' in str(err).lower() else 409)


@app.get("/api/users/search")
def api_user_search(request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    try:
        return JSONResponse(search_users(request.query_params.get("q", ""),
            limit=int(request.query_params.get("limit", 50)),
            offset=int(request.query_params.get("offset", 0))))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=422)


@app.get("/api/users/{user_id}")
def api_user_details(user_id: int, request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    user = user_details(user_id)
    if user is None:
        return JSONResponse({"error": "User not found"}, status_code=404)
    return JSONResponse({"user": user})


@app.patch('/api/users/{user_id}')
async def api_edit_person(user_id: int, request: Request):
    if denied := reader_guard(request):
        return denied
    import sqlite3
    try:
        changes = await request.json()
        await asyncio.to_thread(readers.call, 'manage', change=lambda cleanup: edit_person(user_id, changes, cleanup))
    except MissingPerson as exc:
        return JSONResponse({'error': str(exc)}, status_code=404)
    except sqlite3.IntegrityError as exc:
        return JSONResponse({'error': db.duplicate_error(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)
    store._notify()
    return JSONResponse({'user': user_details(user_id)})


@app.post('/api/users/delete')
async def api_delete_people(request: Request):
    if denied := reader_guard(request):
        return denied
    try:
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {'user_ids'}:
            raise ValueError('Select people to delete')
        ids = await asyncio.to_thread(readers.call, 'manage', change=lambda cleanup: delete_people(body['user_ids'], cleanup))
    except MissingPerson as exc:
        return JSONResponse({'error': str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)
    store._notify()
    return JSONResponse({'deleted': ids})


@app.delete('/api/users/{user_id}')
async def api_delete_person(user_id: int, request: Request):
    if denied := reader_guard(request):
        return denied
    try:
        await asyncio.to_thread(readers.call, 'manage', change=lambda cleanup: delete_people([user_id], cleanup))
    except MissingPerson as exc:
        return JSONResponse({'error': str(exc)}, status_code=404)
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=409)
    store._notify()
    return JSONResponse({'deleted': [user_id]})


@app.get("/api/logs")
def api_logs(request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    try:
        limit = int(request.query_params.get("limit", 50))
        offset = int(request.query_params.get("offset", 0))
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Choose a valid page.")
        result = query_visits(dict(request.query_params), limit=limit, offset=offset)
        result["timezone"] = datetime.now().astimezone().strftime('%Z · UTC%z')
        return JSONResponse(result)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=422)
    except Exception:
        return JSONResponse({"error": "Could not load logs. Try again."}, status_code=503)


@app.get("/api/logs/export")
def api_logs_export(request: Request):
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    import csv
    import io
    from starlette.responses import Response
    try:
        result = query_visits(dict(request.query_params), limit=10000)
        if result["total"] > 10000:
            raise ValueError("Narrow the filters to 10000 visits before exporting.")
        output = io.StringIO()
        writer = csv.writer(output)
        columns = ("visit_id", "user_id", "name", "plaksha_id", "check_in", "check_out", "state", "source", "method", "out_method", "device", "out_device", "duration_seconds")
        writer.writerow(columns)
        for row in result["rows"]:
            # Prevent spreadsheet formula execution when opening an export.
            values = [row.get(key) for key in columns]
            writer.writerow(["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value for value in values])
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="labauth-visits.csv"'})
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=422)
    except Exception:
        return JSONResponse({"error": "Could not export logs. Try again."}, status_code=503)


@app.get("/api/logs/schema")
def api_logs_schema(request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    return JSONResponse({"tables": database_schema()})


@app.post("/api/logs/sql")
async def api_logs_sql(request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError("Enter a query.")
        # Run bounded SQLite work outside the event loop.
        from starlette.concurrency import run_in_threadpool
        return JSONResponse(await run_in_threadpool(query_sql, data.get("sql")))
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=422)
    except Exception:
        return JSONResponse({"error": "Could not run query. Try again."}, status_code=503)


@app.get("/api/time")
def api_get_time() -> JSONResponse:
    now = datetime.now()
    mock_t = store.get_mock_time()
    mock_d = store.get_mock_date()
    return JSONResponse({
        "status": "ok",
        "timestamp": time.time(),
        "iso": now.isoformat(),
        "time": now.strftime("%H:%M"),
        "time_seconds": now.strftime("%H:%M:%S"),
        "date": now.strftime("%B %d, %Y"),
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "mock_time": mock_t,
        "mock_date": mock_d,
    })


@app.get("/api/time/mock")
def api_get_mock_time() -> JSONResponse:
    return JSONResponse({
        "mock_time": store.get_mock_time(),
        "mock_date": store.get_mock_date(),
    })


@app.post("/api/time/mock")
async def api_set_mock_time(request: Request) -> JSONResponse:
    try:
        data = await request.json()
    except Exception:
        data = {}
    if data.get("reset"):
        store.set_mock_time(None, None)
    else:
        time_val = data.get("time")
        date_val = data.get("date")
        store.set_mock_time(time_val, date_val)
    return JSONResponse({
        "status": "ok",
        "mock_time": store.get_mock_time(),
        "mock_date": store.get_mock_date(),
    })


@app.get("/api/settings/display/{screen}")
def api_get_display_settings(screen: str) -> JSONResponse:
    if screen not in db.SCREEN_TARGETS:
        return JSONResponse({"error": "Unknown screen target"}, status_code=400)
    return JSONResponse({"status": "ok", "screen": screen, "settings": db.get_screen_settings(screen)})


@app.post("/api/settings/display/{screen}")
async def api_set_display_settings(screen: str, request: Request) -> JSONResponse:
    if not request_has_valid_admin_session(request):
        return JSONResponse({"error": "Admin session required"}, status_code=401)
    if screen not in db.SCREEN_TARGETS:
        return JSONResponse({"error": "Unknown screen target"}, status_code=400)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    try:
        settings = db.set_screen_settings(screen, data)
    except ValueError as err:
        return JSONResponse({'error': str(err)}, status_code=422)
    db.log_audit(
        "admin",
        "settings_changed",
        screen,
        entity_id="display_settings",
        before=None,
        after=json.dumps(settings, sort_keys=True),
    )
    store.notify_settings_changed(screen)
    return JSONResponse({"status": "ok", "screen": screen, "settings": settings})


FAVICON_PATH = STATIC_ROOT / "favicon.svg"


@app.get("/favicon.ico")
def favicon_ico() -> FileResponse:
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


@app.get("/favicon.svg")
def favicon_svg() -> FileResponse:
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


@ui.page("/", dark=None, favicon=FAVICON_PATH)
def index() -> RedirectResponse:
    return RedirectResponse("/display")


@ui.page(
    "/display",
    title="LabAuth",
    dark=None,
    viewport="width=device-width, initial-scale=1, viewport-fit=cover",
    favicon=FAVICON_PATH,
)
def display() -> None:
    build_display()


@ui.page(
    "/admin-display",
    title="LabAuth \u2013 Admin",
    dark=None,
    viewport="width=device-width, initial-scale=1, viewport-fit=cover",
    favicon=FAVICON_PATH,
)
def admin_display() -> None:
    build_admin_display()


@ui.page("/admin", title="LabAuth \u2013 Administration", dark=None, favicon=FAVICON_PATH)
def admin_panel(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display?login=1")
    build_admin_panel()
    return None


@ui.page("/enrollment", title="LabAuth – Enrollment", dark=None, favicon=FAVICON_PATH)
def enrollment_page(request: Request) -> RedirectResponse | None:
    """Sequential Swiss-style enrollment workflow bound by SBB Lyne guidelines."""
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display?login=1")
    build_enrolment_page()
    return None


@ui.page(
    "/admin/display-settings",
    title="LabAuth \u2013 Display Settings",
    dark=None,
    viewport="width=device-width, initial-scale=1, viewport-fit=cover",
    favicon=FAVICON_PATH,
)
def display_settings_page(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display?login=1")
    build_display_settings_page()
    return None


@ui.page("/logs", title="LabAuth \u2013 Logs", dark=None, favicon=FAVICON_PATH)
def logs_page(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display?login=1")
    build_logs_page()
    return None


@ui.page("/people", title="LabAuth \u2013 People", dark=None, favicon=FAVICON_PATH)
@ui.page("/search", title="LabAuth \u2013 People", dark=None, favicon=FAVICON_PATH)
def search_page(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display?login=1")
    build_search_page()
    return None


@ui.page("/credentials", title="LabAuth – Credentials", dark=None, favicon=FAVICON_PATH)
@ui.page("/admin/credentials", title="LabAuth – Credentials", dark=None, favicon=FAVICON_PATH)
def credentials_page(request: Request) -> RedirectResponse | None:
    if not request_has_valid_admin_session(request):
        return RedirectResponse("/admin-display?login=1")
    build_credentials_page()
    return None


import os

def run() -> None:
    port = int(os.environ.get("PORT", 8080))
    ui.run(
        host="127.0.0.1",
        port=port,
        title="LabAuth",
        dark=None,
        favicon=FAVICON_PATH,
        show=False,
        reload=False,
        show_welcome_message=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
