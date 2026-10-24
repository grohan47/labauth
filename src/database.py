"""SQLite persistence layer for LabAuth.

This module is the single source of truth for the schema and provides all
repository functions used by the rest of the application. It keeps the rest of
the codebase free of raw SQL.

Conventions
-----------
* All timestamps are stored as ISO-8601 UTC strings, e.g. ``2026-10-04T12:00:00.000Z``.
* Connections are short-lived and opened per operation. The database runs in
  WAL mode so concurrent readers are never blocked by a writer.
* The immutable ``presence_log`` is the authoritative record of real in/out
  events. ``current_presence`` is a rebuildable realtime cache for the display
  and for development tooling (seed/reset/populate) that must not pollute the
  audit log or raise operator alerts.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from models import (
    AccessArea,
    AdminAuditLogEntry,
    Alert,
    BackupRun,
    Ban,
    Credential,
    CredentialAttempt,
    CurrentOccupant,
    PresenceEvent,
    PresenceLogEntry,
    User,
)

DEFAULT_PHOTO = "/static/portraits/default.svg"

#: Alert severities, highest priority first. The order is authoritative.
ALERT_SEVERITIES: tuple[str, ...] = ("critical", "caution", "info")

#: Longest accepted alert message. The display scrolls anything up to this.
ALERT_MAX_LENGTH = 500

#: Sentinel meaning "leave this field unchanged" in partial updates.
_KEEP = object()

#: The only physical access areas in this installation.
DEFAULT_ACCESS_AREAS: tuple[tuple[str, str, int], ...] = (
    ("indoor_lab", "Indoor lab", 10),
    ("tool_area", "Tool Area", 20),
)

#: Human spellings accepted from the API / tooling, resolved to a stable code.
ACCESS_AREA_ALIASES: dict[str, str] = {
    "indoor_lab": "indoor_lab",
    "indoor lab": "indoor_lab",
    "lab interior": "indoor_lab",
    "tool_area": "tool_area",
    "tool area": "tool_area",
}

#: Table load order for full backups (respects foreign-key dependencies).
BACKUP_TABLE_ORDER: tuple[str, ...] = (
    "users",
    "access_areas",
    "credentials",
    "user_access_areas",
    "bans",
    "presence_log",
    "credential_attempts",
    "admin_audit_log",
    "settings",
    "alerts",
    "backup_runs",
    "current_presence",
    "reader_drafts",
)

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        plaksha_id  TEXT,
        name        TEXT NOT NULL,
        photo       TEXT NOT NULL DEFAULT '/static/portraits/default.svg',
        email       TEXT,
        phone       TEXT,
        is_temp     INTEGER NOT NULL DEFAULT 0 CHECK (is_temp IN (0, 1)),
        status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_name ON users (name)",
    "CREATE INDEX IF NOT EXISTS idx_users_is_temp ON users (is_temp)",
    """
    CREATE TABLE IF NOT EXISTS access_areas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        code        TEXT NOT NULL UNIQUE,
        label       TEXT NOT NULL,
        sort_order  INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_access_areas (
        user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        area_id     INTEGER NOT NULL REFERENCES access_areas (id) ON DELETE CASCADE,
        granted_at  TEXT NOT NULL,
        granted_by  TEXT,
        PRIMARY KEY (user_id, area_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bans (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        reason       TEXT,
        banned_at    TEXT NOT NULL,
        unbanned_at  TEXT,
        banned_by    TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_open_ban_per_user ON bans (user_id) WHERE unbanned_at IS NULL",
    """
    CREATE TABLE IF NOT EXISTS credentials (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        credential_type  TEXT NOT NULL CHECK (credential_type IN ('nfc', 'fingerprint')),
        identifier       TEXT NOT NULL,
        template         BLOB,
        is_active        INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        enrolled_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_credentials_user ON credentials (user_id)",
    """
    CREATE TABLE IF NOT EXISTS presence_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER NOT NULL REFERENCES users (id),
        event_type     TEXT NOT NULL CHECK (event_type IN ('check_in', 'check_out')),
        entry_method   TEXT NOT NULL CHECK (entry_method IN ('nfc', 'fingerprint', 'manual')),
        credential_id  INTEGER REFERENCES credentials (id),
        occurred_at    TEXT NOT NULL,
        device_id      TEXT,
        metadata       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_presence_user_time ON presence_log (user_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_presence_time ON presence_log (occurred_at)",
    """
    CREATE TABLE IF NOT EXISTS credential_attempts (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at      TEXT NOT NULL,
        credential_type  TEXT NOT NULL,
        identifier       TEXT NOT NULL,
        user_id          INTEGER REFERENCES users (id) ON DELETE SET NULL,
        outcome          TEXT NOT NULL CHECK (outcome IN (
            'success', 'unknown_credential', 'read_failure',
            'low_confidence', 'cooldown', 'reader_error'
        )),
        message          TEXT,
        device_id        TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_attempts_time ON credential_attempts (occurred_at)",
    """
    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at  TEXT NOT NULL,
        actor        TEXT NOT NULL,
        action       TEXT NOT NULL,
        entity_type  TEXT NOT NULL,
        entity_id    TEXT,
        before       TEXT,
        after        TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_time ON admin_audit_log (occurred_at)",
    """
    CREATE TABLE IF NOT EXISTS settings (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        message     TEXT NOT NULL,
        severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('critical', 'caution', 'info')),
        expires_at  TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts (created_at)",
    """
    CREATE TABLE IF NOT EXISTS backup_runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at   TEXT NOT NULL,
        finished_at  TEXT,
        status       TEXT NOT NULL CHECK (status IN ('in_progress', 'success', 'failed')),
        destination  TEXT NOT NULL,
        size_bytes   INTEGER,
        error        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS current_presence (
        user_id        INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
        checked_in_at  TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reader_drafts (
        id           TEXT PRIMARY KEY,
        owner        TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'active',
        stage        TEXT NOT NULL DEFAULT 'idle',
        fp_template  INTEGER,
        nfc_uid      TEXT,
        user_id      INTEGER REFERENCES users (id),
        message      TEXT NOT NULL DEFAULT '',
        updated_at   TEXT NOT NULL,
        expires_at   TEXT NOT NULL
    )
    """,
)


# ---------------------------------------------------------------------------
# Paths, connections and time helpers
# ---------------------------------------------------------------------------


def project_root() -> Path:
    """Return the repository/source root regardless of how the app was launched."""
    if getattr(sys, "frozen", False):  # PyInstaller onefile
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return Path(__file__).resolve().parent.parent


def shared_project_root() -> Path:
    """Resolve the root of the primary checkout even when running in a worktree."""
    root = project_root()
    git_file = root / ".git"
    if git_file.is_file():
        try:
            content = git_file.read_text().strip()
            if content.startswith("gitdir:"):
                git_dir_str = content.split(":", 1)[1].strip()
                git_dir = Path(git_dir_str)
                if not git_dir.is_absolute():
                    git_dir = (root / git_dir).resolve()
                commondir_file = git_dir / "commondir"
                if commondir_file.is_file():
                    common = commondir_file.read_text().strip()
                    common_path = (git_dir / common).resolve()
                    if common_path.name == ".git":
                        return common_path.parent
                    return common_path
        except Exception:
            pass
    return root


def db_path() -> Path:
    """Resolve the SQLite database path.

    Overridable with ``LABAUTH_DB_PATH`` (required by the test-suite so it never
    touches the real database).
    """
    override = os.environ.get("LABAUTH_DB_PATH")
    if override:
        return Path(override).expanduser()
    return shared_project_root() / "data" / "labauth.db"


def _iso_from_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string with millisecond precision."""
    return _iso_from_dt(datetime.now(timezone.utc))


def iso_to_epoch(value: str) -> float:
    """Best-effort conversion of a stored ISO timestamp to a Unix epoch float."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return time.time()


def local_hhmm_to_iso(value: str) -> str:
    """Convert a local ``HH:MM`` / ``HH:MM:SS`` clock time (today) to UTC ISO."""
    parts = (value or "").split(":")
    now = datetime.now().astimezone()
    try:
        local = now.replace(
            hour=int(parts[0]),
            minute=int(parts[1]) if len(parts) > 1 else 0,
            second=int(parts[2]) if len(parts) > 2 else 0,
            microsecond=0,
        )
    except (ValueError, IndexError):
        return utcnow_iso()
    return _iso_from_dt(local.astimezone(timezone.utc))


def iso_to_local_hhmm(value: str, reference_time: datetime | str | None = None) -> str:
    """Format a stored ISO timestamp as a local HH:MM display string.
    If duration is 24+ hours, denotes with +1, +2 etc.
    """
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        time_str = dt.astimezone().strftime("%H:%M")
        ref_dt = None
        if reference_time is not None:
            if isinstance(reference_time, str):
                try:
                    ref_dt = datetime.fromisoformat(reference_time.replace("Z", "+00:00"))
                except Exception:
                    pass
            elif isinstance(reference_time, datetime):
                ref_dt = reference_time
        if ref_dt is None:
            try:
                import sys
                presence_mod = sys.modules.get("presence")
                if presence_mod and hasattr(presence_mod, "store"):
                    mock_t = presence_mod.store.get_mock_time()
                    mock_d = presence_mod.store.get_mock_date()
                    if mock_t or mock_d:
                        base_d = datetime.now().date()
                        if mock_d:
                            for fmt in ("%B %d, %Y", "%B %-d, %Y", "%b %d, %Y", "%Y-%m-%d"):
                                try:
                                    base_d = datetime.strptime(mock_d, fmt).date()
                                    break
                                except ValueError:
                                    pass
                        hour, minute = 0, 0
                        if mock_t and ":" in mock_t:
                            parts = mock_t.split(":")
                            hour, minute = int(parts[0]), int(parts[1])
                        local_mock = datetime.combine(base_d, datetime.min.time()).replace(hour=hour, minute=minute)
                        ref_dt = local_mock.astimezone(timezone.utc)
            except Exception:
                pass
        if ref_dt is None:
            ref_dt = datetime.now(timezone.utc)
        elif ref_dt.tzinfo is None:
            ref_dt = ref_dt.astimezone(timezone.utc)
        duration_sec = (ref_dt - dt).total_seconds()
        if duration_sec >= 86400:
            days = int(duration_sec // 86400)
            return f"{time_str} +{days}"
        return time_str
    except (ValueError, TypeError, AttributeError):
        return value if (isinstance(value, str) and ":" in value) else "--:--"
def connect() -> sqlite3.Connection:
    """Open a new SQLite connection with sane defaults."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a connection, committing on success."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create every table/index if missing and seed the access areas."""
    with get_db() as db:
        db.execute("PRAGMA journal_mode = WAL")
        for statement in _SCHEMA:
            db.execute(statement)
        cols = [r["name"] for r in db.execute("PRAGMA table_info(users)").fetchall()]
        if cols:
            if "email" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN email TEXT")
            if "phone" not in cols:
                db.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        for table in ('users', 'credentials'):
            if 'deleted_at' not in {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN deleted_at TEXT')
        # Keep retired identities/registrations for immutable attendance history.
        db.execute('DROP INDEX IF EXISTS uniq_plaksha_id')
        db.execute('DROP INDEX IF EXISTS uniq_credential_identifier')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS uniq_live_plaksha_id ON users (lower(trim(plaksha_id))) WHERE plaksha_id IS NOT NULL AND deleted_at IS NULL')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS uniq_live_credential ON credentials (credential_type, identifier COLLATE NOCASE) WHERE deleted_at IS NULL')
    seed_default_access_areas()


def seed_default_access_areas() -> None:
    """Keep the two real access areas, auditing removal of legacy demo areas."""
    with get_db() as db:
        unsupported = db.execute("SELECT * FROM access_areas WHERE code NOT IN ('indoor_lab', 'tool_area')").fetchall()
        for area in unsupported:
            grants = [dict(row) for row in db.execute('SELECT * FROM user_access_areas WHERE area_id=?', (area['id'],))]
            db.execute("INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after) VALUES (?, 'system', 'remove_demo_area', 'access_area', ?, ?, NULL)",
                       (utcnow_iso(), str(area['id']), json.dumps({'area': dict(area), 'grants': grants})))
            db.execute('DELETE FROM user_access_areas WHERE area_id=?', (area['id'],))
            db.execute('DELETE FROM access_areas WHERE id=?', (area['id'],))
        for code, label, order in DEFAULT_ACCESS_AREAS:
            db.execute(
                "INSERT INTO access_areas (code, label, sort_order) VALUES (?, ?, ?) ON CONFLICT(code) DO UPDATE SET label=excluded.label, sort_order=excluded.sort_order",
                (code, label, order),
            )


# ---------------------------------------------------------------------------
# Row mapping helpers
# ---------------------------------------------------------------------------


def _user_from_row(row: sqlite3.Row) -> User:
    keys = row.keys()
    return User(
        id=row["id"],
        name=row["name"],
        plaksha_id=row["plaksha_id"],
        photo=row["photo"],
        is_temp=bool(row["is_temp"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        email=row["email"] if "email" in keys else None,
        phone=row["phone"] if "phone" in keys else None,
    )


def _area_from_row(row: sqlite3.Row) -> AccessArea:
    return AccessArea(
        id=row["id"],
        code=row["code"],
        label=row["label"],
        sort_order=row["sort_order"],
    )


def _credential_from_row(row: sqlite3.Row) -> Credential:
    return Credential(
        id=row["id"],
        user_id=row["user_id"],
        credential_type=row["credential_type"],
        identifier=row["identifier"],
        template=row["template"],
        is_active=bool(row["is_active"]),
        enrolled_at=row["enrolled_at"],
    )


def _ban_from_row(row: sqlite3.Row) -> Ban:
    return Ban(
        id=row["id"],
        user_id=row["user_id"],
        reason=row["reason"],
        banned_at=row["banned_at"],
        unbanned_at=row["unbanned_at"],
        banned_by=row["banned_by"],
    )


def _presence_from_row(row: sqlite3.Row) -> PresenceLogEntry:
    return PresenceLogEntry(
        id=row["id"],
        user_id=row["user_id"],
        event_type=row["event_type"],
        entry_method=row["entry_method"],
        credential_id=row["credential_id"],
        occurred_at=row["occurred_at"],
        device_id=row["device_id"],
        metadata=row["metadata"],
    )


def _attempt_from_row(row: sqlite3.Row) -> CredentialAttempt:
    return CredentialAttempt(
        id=row["id"],
        occurred_at=row["occurred_at"],
        credential_type=row["credential_type"],
        identifier=row["identifier"],
        user_id=row["user_id"],
        outcome=row["outcome"],
        message=row["message"],
        device_id=row["device_id"],
    )


def _audit_from_row(row: sqlite3.Row) -> AdminAuditLogEntry:
    return AdminAuditLogEntry(
        id=row["id"],
        occurred_at=row["occurred_at"],
        actor=row["actor"],
        action=row["action"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        before=row["before"],
        after=row["after"],
    )


def _backup_from_row(row: sqlite3.Row) -> BackupRun:
    return BackupRun(
        id=row["id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        destination=row["destination"],
        size_bytes=row["size_bytes"],
        error=row["error"],
    )


def _alert_from_row(row: sqlite3.Row) -> Alert:
    return Alert(
        id=row["id"],
        message=row["message"],
        severity=row["severity"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _slugify(value: str) -> str:
    cleaned = [ch.lower() if ch.isalnum() else "_" for ch in (value or "").strip()]
    slug = "".join(cleaned).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "area"


# ---------------------------------------------------------------------------
# Access areas
# ---------------------------------------------------------------------------


def get_access_area(area_id: int) -> Optional[AccessArea]:
    with get_db() as db:
        row = db.execute("SELECT * FROM access_areas WHERE id = ?", (area_id,)).fetchone()
    return _area_from_row(row) if row else None


def get_access_area_by_code(code: str) -> Optional[AccessArea]:
    with get_db() as db:
        row = db.execute("SELECT * FROM access_areas WHERE code = ?", (code,)).fetchone()
    return _area_from_row(row) if row else None


def list_access_areas() -> list[AccessArea]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM access_areas ORDER BY sort_order IS NULL, sort_order, label"
        ).fetchall()
    return [_area_from_row(row) for row in rows]


def ensure_access_area(
    name: str, *, label: Optional[str] = None, allow_create: bool = True
) -> AccessArea:
    """Resolve a user-supplied area name to a stored ``AccessArea``.

    Known aliases map to the two canonical rows. Unknown areas are rejected,
    including legacy callers passing ``allow_create=True``.
    """
    key = (name or "").strip()
    if not key:
        raise ValueError("Access area name must not be empty")

    code = ACCESS_AREA_ALIASES.get(key.lower())
    if code is None:
        raise KeyError(f"Unknown access area: {key!r}")
    with get_db() as db:
        row = db.execute("SELECT * FROM access_areas WHERE code = ?", (code,)).fetchone()
        if row:
            return _area_from_row(row)
        row = db.execute(
            "SELECT * FROM access_areas WHERE lower(label) = ?", (key.lower(),)
        ).fetchone()
        if row:
            return _area_from_row(row)
        if not allow_create:
            raise KeyError(f"Unknown access area: {key!r}")
        cur = db.execute(
            "INSERT INTO access_areas (code, label, sort_order) VALUES (?, ?, ?)",
            (code, label or key, None),
        )
        area_id = cur.lastrowid
    area = get_access_area(area_id)
    assert area is not None
    return area


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def create_user(
    name: str,
    *,
    plaksha_id: Optional[str] = None,
    photo: str = DEFAULT_PHOTO,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    is_temp: bool = False,
    status: str = "active",
) -> User:
    now = utcnow_iso()
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO users (plaksha_id, name, photo, email, phone, is_temp, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _clean(plaksha_id),
                name.strip(),
                photo or DEFAULT_PHOTO,
                _clean(email),
                _clean(phone),
                int(bool(is_temp)),
                status,
                now,
                now,
            ),
        )
        user_id = cur.lastrowid
    user = get_user(user_id)
    assert user is not None
    return user


def get_user(user_id: int) -> Optional[User]:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE deleted_at IS NULL AND id = ?", (user_id,)).fetchone()
    return _user_from_row(row) if row else None


def get_user_by_plaksha_id(plaksha_id: str) -> Optional[User]:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM users WHERE deleted_at IS NULL AND plaksha_id = ?", (_clean(plaksha_id),)
        ).fetchone()
    return _user_from_row(row) if row else None


def get_active_user_by_name(name: str) -> Optional[User]:
    """Return the most recently created active user with the given name."""
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM users
            WHERE lower(name) = lower(?) AND status = 'active'
            ORDER BY id DESC LIMIT 1
            """,
            ((name or "").strip(),),
        ).fetchone()
    return _user_from_row(row) if row else None


def list_users(*, include_inactive: bool = True, include_temp: bool = True) -> list[User]:
    clauses, params = ["deleted_at IS NULL"], []
    if not include_inactive:
        clauses.append("status = 'active'")
    if not include_temp:
        clauses.append("is_temp = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM users {where} ORDER BY name COLLATE NOCASE ASC", params
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def list_temp_users() -> list[User]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM users WHERE deleted_at IS NULL AND is_temp = 1 ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def search_users(query: str, *, limit: int = 50) -> list[User]:
    """Search active users by name or Plaksha ID (case-insensitive, partial)."""
    term = (query or "").strip()
    if not term:
        return []
    like = f"%{term}%"
    with get_db() as db:
        rows = db.execute(
            """
            SELECT * FROM users
            WHERE status = 'active'
              AND (name LIKE ? COLLATE NOCASE OR plaksha_id LIKE ? COLLATE NOCASE)
            ORDER BY name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def update_user(user_id: int, **fields: Any) -> Optional[User]:
    allowed = {"name", "plaksha_id", "photo", "email", "phone", "is_temp", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user(user_id)
    if "is_temp" in updates:
        updates["is_temp"] = int(bool(updates["is_temp"]))
    if "plaksha_id" in updates:
        updates["plaksha_id"] = _clean(updates["plaksha_id"])
    if "email" in updates:
        updates["email"] = _clean(updates["email"])
    if "phone" in updates:
        updates["phone"] = _clean(updates["phone"])
    updates["updated_at"] = utcnow_iso()
    assignments = ", ".join(f"{column} = ?" for column in updates)
    with get_db() as db:
        db.execute(
            f"UPDATE users SET {assignments} WHERE deleted_at IS NULL AND id = ?",
            (*updates.values(), user_id),
        )
    return get_user(user_id)


def create_enrolment(
    name: str,
    *,
    plaksha_id: Optional[str] = None,
    photo: str = DEFAULT_PHOTO,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    access_area_ids: Sequence[int] = (),
    is_temp: bool = False,
    credentials: Sequence[tuple[str, str]] = (),
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Name is required")

    area_ids = list(dict.fromkeys(access_area_ids))
    now = utcnow_iso()
    with get_db() as conn:
        if area_ids:
            placeholders = ",".join("?" for _ in area_ids)
            rows = conn.execute(
                f"SELECT id FROM access_areas WHERE id IN ({placeholders})", area_ids
            ).fetchall()
            found_ids = {r["id"] for r in rows}
            for aid in area_ids:
                if aid not in found_ids:
                    raise ValueError(f"Unknown access area id: {aid}")

        cur = conn.execute(
            """
            INSERT INTO users (plaksha_id, name, photo, email, phone, is_temp, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                _clean(plaksha_id),
                clean_name,
                photo or DEFAULT_PHOTO,
                _clean(email),
                _clean(phone),
                int(bool(is_temp)),
                now,
                now,
            ),
        )
        user_id = cur.lastrowid

        credential_records: list[dict[str, Any]] = []
        for credential_type, identifier in credentials:
            identifier = normalize_credential(credential_type, identifier)
            cred_cur = conn.execute(
                """INSERT INTO credentials
                   (user_id, credential_type, identifier, template, is_active, enrolled_at)
                   VALUES (?, ?, ?, NULL, 1, ?)""",
                (user_id, credential_type, identifier, now),
            )
            credential_records.append({
                "id": cred_cur.lastrowid, "user_id": user_id,
                "credential_type": credential_type, "identifier": identifier,
                "is_active": True, "enrolled_at": now,
            })

        for aid in area_ids:
            conn.execute(
                """
                INSERT INTO user_access_areas (user_id, area_id, granted_at, granted_by)
                VALUES (?, ?, ?, 'admin')
                """,
                (user_id, aid, now),
            )

        conn.execute(
            """
            INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after)
            VALUES (?, 'admin', 'enrol_user', 'user', ?, NULL, ?)
            """,
            (now, str(user_id), clean_name),
        )

        if credential_records:
            conn.execute(
                """INSERT INTO admin_audit_log
                   (occurred_at, actor, action, entity_type, entity_id, before, after)
                   VALUES (?, 'admin', 'enrol_credentials', 'user', ?, NULL, ?)""",
                (now, str(user_id), json.dumps([
                    {"credential_type": c["credential_type"], "identifier": c["identifier"]}
                    for c in credential_records
                ])),
            )

        row = conn.execute("SELECT * FROM users WHERE deleted_at IS NULL AND id = ?", (user_id,)).fetchone()
        labels = _labels_for(conn, user_id)

    return {
        "id": row["id"],
        "name": row["name"],
        "plaksha_id": row["plaksha_id"],
        "photo": row["photo"],
        "email": row["email"],
        "phone": row["phone"],
        "is_temp": bool(row["is_temp"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "access": labels,
        "credentials": credential_records,
        "is_inside": False,
        "is_banned": False,
    }


def set_user_status(user_id: int, status: str) -> Optional[User]:
    return update_user(user_id, status=status)


def deactivate_user(user_id: int) -> bool:
    """Retain identity, credentials and history when removing account access.

    People management separately retires accounts and credentials while keeping
    immutable attendance history.
    """
    return set_user_status(user_id, "inactive") is not None


def count_users() -> int:
    with get_db() as db:
        return int(db.execute("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL").fetchone()[0])


def list_users_detailed(
    *, include_inactive: bool = True, include_temp: bool = True, limit: int = 200
) -> list[dict]:
    """Users with their granted areas, live presence and ban state."""
    clauses, params = ["deleted_at IS NULL"], []
    if not include_inactive:
        clauses.append("status = 'active'")
    if not include_temp:
        clauses.append("is_temp = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT u.*,
                   EXISTS (SELECT 1 FROM current_presence cp WHERE cp.user_id = u.id) AS is_inside,
                   EXISTS (SELECT 1 FROM bans b WHERE b.user_id = u.id AND b.unbanned_at IS NULL) AS is_banned
            FROM users u
            {where}
            ORDER BY u.name COLLATE NOCASE ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_user_detail(conn, row) for row in rows]


def search_users_detailed(query: str, *, limit: int = 50) -> list[dict]:
    """Search users by name or Plaksha ID, returning full detail rows."""
    term = (query or "").strip()
    if not term:
        return list_users_detailed(limit=limit)
    like = f"%{term}%"
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT u.*,
                   EXISTS (SELECT 1 FROM current_presence cp WHERE cp.user_id = u.id) AS is_inside,
                   EXISTS (SELECT 1 FROM bans b WHERE b.user_id = u.id AND b.unbanned_at IS NULL) AS is_banned
            FROM users u
            WHERE status = 'active'
              AND (name LIKE ? COLLATE NOCASE OR plaksha_id LIKE ? COLLATE NOCASE)
            ORDER BY u.name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        return [_user_detail(conn, row) for row in rows]


def _user_detail(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "plaksha_id": row["plaksha_id"],
        "photo": row["photo"],
        "is_temp": bool(row["is_temp"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "access": _labels_for(conn, row["id"]),
        "is_inside": bool(row["is_inside"]),
        "is_banned": bool(row["is_banned"]),
    }


def list_presence_log(*, limit: int = 100, user_id: Optional[int] = None) -> list[dict]:
    """The in/out log joined with the acting user, newest first."""
    params: list[Any] = []
    where = ""
    if user_id is not None:
        where = "WHERE p.user_id = ?"
        params.append(user_id)
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.event_type, p.entry_method, p.occurred_at, p.device_id,
                   u.id AS user_id, u.name AS user_name, u.is_temp AS user_is_temp
            FROM presence_log p
            JOIN users u ON u.id = p.user_id
            {where}
            ORDER BY p.occurred_at DESC, p.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "user_name": row["user_name"],
            "is_temp": bool(row["user_is_temp"]),
            "event_type": row["event_type"],
            "entry_method": row["entry_method"],
            "occurred_at": row["occurred_at"],
            "device_id": row["device_id"],
        }
        for row in rows
    ]


def clear_all_data() -> None:
    """Delete every row from every table, keeping the schema intact."""
    with get_db() as conn:
        for table in reversed(BACKUP_TABLE_ORDER):
            conn.execute(f"DELETE FROM {table}")


def set_user_access_areas(
    user_id: int,
    names: Sequence[str],
    *,
    granted_by: Optional[str] = None,
    allow_create: bool = False,
) -> None:
    """Replace a user's granted access areas with ``names``."""
    area_ids: list[int] = []
    for name in names:
        if name and name.strip():
            try:
                area = ensure_access_area(name, allow_create=allow_create)
                area_ids.append(area.id)
            except KeyError:
                continue
    now = utcnow_iso()
    with get_db() as db:
        db.execute("DELETE FROM user_access_areas WHERE user_id = ?", (user_id,))
        for area_id in dict.fromkeys(area_ids):
            db.execute(
                """
                INSERT INTO user_access_areas (user_id, area_id, granted_at, granted_by)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, area_id, now, granted_by),
            )


def get_user_access_areas(user_id: int) -> list[AccessArea]:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT aa.* FROM user_access_areas uaa
            JOIN access_areas aa ON aa.id = uaa.area_id
            WHERE uaa.user_id = ?
            ORDER BY aa.sort_order IS NULL, aa.sort_order, aa.label
            """,
            (user_id,),
        ).fetchall()
    return [_area_from_row(row) for row in rows]


def get_user_access_area_labels(user_id: int) -> list[str]:
    return [area.label for area in get_user_access_areas(user_id)]


# ---------------------------------------------------------------------------
# Bans
# ---------------------------------------------------------------------------


def create_ban(user_id: int, *, reason: Optional[str] = None, banned_by: Optional[str] = None) -> Ban:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO bans (user_id, reason, banned_at, unbanned_at, banned_by) VALUES (?, ?, ?, NULL, ?)",
            (user_id, reason, utcnow_iso(), banned_by),
        )
        ban_id = cur.lastrowid
    ban = get_ban(ban_id)
    assert ban is not None
    return ban


def get_ban(ban_id: int) -> Optional[Ban]:
    with get_db() as db:
        row = db.execute("SELECT * FROM bans WHERE id = ?", (ban_id,)).fetchone()
    return _ban_from_row(row) if row else None


def lift_ban(user_id: int) -> bool:
    with get_db() as db:
        cur = db.execute(
            "UPDATE bans SET unbanned_at = ? WHERE user_id = ? AND unbanned_at IS NULL",
            (utcnow_iso(), user_id),
        )
        return cur.rowcount > 0


def is_user_banned(user_id: int) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM bans WHERE user_id = ? AND unbanned_at IS NULL LIMIT 1",
            (user_id,),
        ).fetchone()
    return row is not None


def list_bans(*, user_id: Optional[int] = None, open_only: bool = False) -> list[Ban]:
    clauses, params = [], []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if open_only:
        clauses.append("unbanned_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM bans {where} ORDER BY banned_at DESC", params
        ).fetchall()
    return [_ban_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def enroll_credential(
    user_id: int,
    credential_type: str,
    identifier: str,
    *,
    template: Optional[bytes] = None,
) -> Credential:
    """Register an NFC/fingerprint credential, rejecting duplicates."""
    identifier = normalize_credential(credential_type, identifier)
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO credentials (user_id, credential_type, identifier, template, is_active, enrolled_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (user_id, credential_type, identifier, template, utcnow_iso()),
        )
        credential_id = cur.lastrowid
    credential = get_credential(credential_id)
    assert credential is not None
    return credential


def get_credential(credential_id: int) -> Optional[Credential]:
    with get_db() as db:
        row = db.execute("SELECT * FROM credentials WHERE deleted_at IS NULL AND id = ?", (credential_id,)).fetchone()
    return _credential_from_row(row) if row else None


def resolve_user_by_credential(credential_type: str, identifier: str) -> Optional[User]:
    with get_db() as db:
        row = db.execute(
            """
            SELECT u.* FROM credentials c
            JOIN users u ON u.id = c.user_id
            WHERE c.deleted_at IS NULL AND c.credential_type = ? AND c.identifier = ? AND c.is_active = 1
            LIMIT 1
            """,
            (credential_type, identifier),
        ).fetchone()
    return _user_from_row(row) if row else None


def list_credentials(*, user_id: Optional[int] = None) -> list[Credential]:
    if user_id is None:
        with get_db() as db:
            rows = db.execute("SELECT * FROM credentials WHERE deleted_at IS NULL ORDER BY enrolled_at DESC").fetchall()
    else:
        with get_db() as db:
            rows = db.execute(
                "SELECT * FROM credentials WHERE deleted_at IS NULL AND user_id = ? ORDER BY enrolled_at DESC",
                (user_id,),
            ).fetchall()
    return [_credential_from_row(row) for row in rows]


def set_credential_active(credential_id: int, is_active: bool) -> None:
    with get_db() as db:
        db.execute(
            "UPDATE credentials SET is_active = ? WHERE deleted_at IS NULL AND id = ?",
            (int(bool(is_active)), credential_id),
        )


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


def log_presence(
    user_id: int,
    event_type: str,
    entry_method: str = "manual",
    *,
    credential_id: Optional[int] = None,
    occurred_at: Optional[str] = None,
    device_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> PresenceLogEntry:
    """Append an immutable in/out log entry."""
    if event_type not in ("check_in", "check_out"):
        raise ValueError(f"Invalid event_type: {event_type!r}")
    if entry_method not in ("nfc", "fingerprint", "manual"):
        raise ValueError(f"Invalid entry_method: {entry_method!r}")
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO presence_log (user_id, event_type, entry_method, credential_id, occurred_at, device_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                event_type,
                entry_method,
                credential_id,
                occurred_at or utcnow_iso(),
                device_id,
                json.dumps(metadata) if metadata else None,
            ),
        )
        entry_id = cur.lastrowid
    entry = get_presence_entry(entry_id)
    assert entry is not None
    return entry


def get_presence_entry(entry_id: int) -> Optional[PresenceLogEntry]:
    with get_db() as db:
        row = db.execute("SELECT * FROM presence_log WHERE id = ?", (entry_id,)).fetchone()
    return _presence_from_row(row) if row else None


def latest_presence_entry(user_id: int) -> Optional[PresenceLogEntry]:
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM presence_log WHERE user_id = ?
            ORDER BY occurred_at DESC, id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return _presence_from_row(row) if row else None


def latest_check_in_entry(user_id: int) -> Optional[PresenceLogEntry]:
    with get_db() as db:
        row = db.execute(
            """
            SELECT * FROM presence_log WHERE user_id = ? AND event_type = 'check_in'
            ORDER BY occurred_at DESC, id DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return _presence_from_row(row) if row else None


def is_user_inside(user_id: int) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM current_presence WHERE user_id = ? LIMIT 1", (user_id,)
        ).fetchone()
    return row is not None


def upsert_current_presence(user_id: int, checked_in_at: Optional[str] = None) -> None:
    now = utcnow_iso()
    with get_db() as db:
        db.execute(
            """
            INSERT INTO current_presence (user_id, checked_in_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                checked_in_at = excluded.checked_in_at,
                updated_at = excluded.updated_at
            """,
            (user_id, checked_in_at or now, now),
        )


def remove_current_presence(user_id: int) -> bool:
    with get_db() as db:
        cur = db.execute("DELETE FROM current_presence WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0


def clear_current_presence() -> None:
    with get_db() as db:
        db.execute("DELETE FROM current_presence")


def current_occupants(reference_time: datetime | str | None = None) -> list[CurrentOccupant]:
    """Return everyone currently inside, newest check-in ordered last."""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT u.*, cp.checked_in_at AS presence_checked_in_at
            FROM current_presence cp
            JOIN users u ON u.id = cp.user_id
            WHERE u.status = 'active'
            ORDER BY cp.checked_in_at ASC, u.name COLLATE NOCASE ASC
            """
        ).fetchall()
        occupants = [
            CurrentOccupant(
                user=_user_from_row(row),
                access=tuple(_labels_for(db, row["id"])),
                checked_in=iso_to_local_hhmm(row["presence_checked_in_at"], reference_time=reference_time),
            )
            for row in rows
        ]
    return occupants




def list_credentials_with_users(
    *, credential_type: Optional[str] = None, query: Optional[str] = None,
    limit: int = 100, offset: int = 0, sensor_templates: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.user_id, u.name AS user_name, u.plaksha_id, u.photo AS user_photo,
                   c.credential_type, c.identifier, c.is_active, c.enrolled_at,
                   LENGTH(c.template) AS template_bytes
            FROM credentials c JOIN users u ON u.id = c.user_id
            WHERE c.deleted_at IS NULL AND u.deleted_at IS NULL
            ORDER BY c.enrolled_at DESC, c.id DESC
        """).fetchall()
    records = [dict(row) for row in rows]
    assigned = {row['identifier'] for row in records if row['credential_type'] == 'fingerprint'}
    slots = None if sensor_templates is None else set(sensor_templates)
    for row in records:
        row['on_sensor'] = (int(row['identifier'].split(':')[1]) in slots
                            if slots is not None and row['credential_type'] == 'fingerprint'
                            and row['identifier'].startswith('template:')
                            and row['identifier'].split(':')[1].isdigit() else None)
    for slot in sorted(slots or ()):
        identifier = f'template:{slot}'
        if identifier not in assigned:
            records.append(dict(id=f'sensor:{slot}', user_id=None, user_name=None, plaksha_id=None,
                                user_photo=None, credential_type='fingerprint', identifier=identifier,
                                is_active=False, enrolled_at=None, template_bytes=None, on_sensor=True))
    query = (query or '').strip().casefold()
    records = [row for row in records if (not credential_type or row['credential_type'] == credential_type)
               and (not query or any(query in str(row.get(key) or '').casefold()
                                     for key in ('identifier', 'user_name', 'plaksha_id')))]
    return records[offset:offset + limit], len(records)

def presence_events_since(
    since_id: int = 0, max_age_seconds: float = 30.0
) -> list[PresenceEvent]:
    """Return in/out events newer than ``since_id`` and within ``max_age_seconds``."""
    threshold = _iso_from_dt(datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds))
    with get_db() as db:
        rows = db.execute(
            """
            SELECT
                p.id AS p_id, p.user_id AS p_user_id, p.event_type AS p_event_type,
                p.entry_method AS p_entry_method, p.credential_id AS p_credential_id,
                p.occurred_at AS p_occurred_at, p.device_id AS p_device_id,
                p.metadata AS p_metadata,
                u.id AS u_id, u.name AS u_name, u.plaksha_id AS u_plaksha_id,
                u.photo AS u_photo, u.is_temp AS u_is_temp, u.status AS u_status,
                u.created_at AS u_created_at, u.updated_at AS u_updated_at
            FROM presence_log p
            JOIN users u ON u.id = p.user_id
            WHERE p.id > ? AND p.occurred_at >= ?
            ORDER BY p.id ASC
            """,
            (since_id, threshold),
        ).fetchall()
        events = [
            PresenceEvent(
                entry=PresenceLogEntry(
                    id=row["p_id"],
                    user_id=row["p_user_id"],
                    event_type=row["p_event_type"],
                    entry_method=row["p_entry_method"],
                    credential_id=row["p_credential_id"],
                    occurred_at=row["p_occurred_at"],
                    device_id=row["p_device_id"],
                    metadata=row["p_metadata"],
                ),
                user=User(
                    id=row["u_id"],
                    name=row["u_name"],
                    plaksha_id=row["u_plaksha_id"],
                    photo=row["u_photo"],
                    is_temp=bool(row["u_is_temp"]),
                    status=row["u_status"],
                    created_at=row["u_created_at"],
                    updated_at=row["u_updated_at"],
                ),
                access=tuple(_labels_for(db, row["u_id"])),
            )
            for row in rows
        ]
    return events


def count_presence() -> int:
    with get_db() as db:
        return int(db.execute("SELECT COUNT(*) FROM presence_log").fetchone()[0])


def _labels_for(db: sqlite3.Connection, user_id: int) -> list[str]:
    rows = db.execute(
        """
        SELECT aa.label FROM user_access_areas uaa
        JOIN access_areas aa ON aa.id = uaa.area_id
        WHERE uaa.user_id = ?
        ORDER BY aa.sort_order IS NULL, aa.sort_order, aa.label
        """,
        (user_id,),
    ).fetchall()
    return [row["label"] for row in rows]


# ---------------------------------------------------------------------------
# Credential attempts
# ---------------------------------------------------------------------------


def log_credential_attempt(
    credential_type: str,
    identifier: str,
    outcome: str,
    *,
    user_id: Optional[int] = None,
    message: Optional[str] = None,
    device_id: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> CredentialAttempt:
    """Record an authentication attempt and whatever the reader reported."""
    allowed = {
        "success",
        "unknown_credential",
        "read_failure",
        "low_confidence",
        "cooldown",
        "reader_error",
    }
    if outcome not in allowed:
        raise ValueError(f"Invalid outcome: {outcome!r}")
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO credential_attempts
                (occurred_at, credential_type, identifier, user_id, outcome, message, device_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                occurred_at or utcnow_iso(),
                credential_type,
                identifier,
                user_id,
                outcome,
                message,
                device_id,
            ),
        )
        attempt_id = cur.lastrowid
    attempt = get_credential_attempt(attempt_id)
    assert attempt is not None
    return attempt


def get_credential_attempt(attempt_id: int) -> Optional[CredentialAttempt]:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM credential_attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
    return _attempt_from_row(row) if row else None


def attach_credentials(user_id: int, credentials: Sequence[tuple[str, str]], *, actor: str = "admin") -> list[dict[str, Any]]:
    """Atomically attach credential identifiers to an active user and audit it."""
    now = utcnow_iso()
    records: list[dict[str, Any]] = []
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute("SELECT id FROM users WHERE id=? AND status='active'", (user_id,)).fetchone()
        if user is None:
            raise ValueError("User is missing or inactive")
        for kind, identifier in credentials:
            if kind not in ("nfc", "fingerprint") or not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("Credential type and identifier are required")
            value = normalize_credential(kind, identifier)
            cur = conn.execute(
                "INSERT INTO credentials (user_id, credential_type, identifier, template, is_active, enrolled_at) VALUES (?, ?, ?, NULL, 1, ?)",
                (user_id, kind, value, now),
            )
            records.append({"id": cur.lastrowid, "user_id": user_id, "credential_type": kind,
                            "identifier": value, "is_active": True, "enrolled_at": now})
        conn.execute(
            "INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after) VALUES (?, ?, 'attach_credentials', 'user', ?, NULL, ?)",
            (now, actor, str(user_id), json.dumps([{"credential_type": r["credential_type"], "identifier": r["identifier"]} for r in records])),
        )
    return records


def create_draft(owner: str, user_id: Optional[int] = None, ttl: int = 1800) -> str:
    """Create the single durable reader-enrolment lease and return its token."""
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute("SELECT id FROM reader_drafts WHERE status IN ('active','complete','cleanup') LIMIT 1").fetchone()
        if active:
            raise RuntimeError("A reader draft lease already exists")
        if user_id is not None and not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise ValueError("Unknown user_id")
        conn.execute(
            "INSERT INTO reader_drafts (id, owner, user_id, updated_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token, owner, user_id, _iso_from_dt(now), _iso_from_dt(now + timedelta(seconds=max(1, int(ttl))))),
        )
    return token


def get_draft(draft_id: str, owner: Optional[str] = None) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        if owner is None:
            row = conn.execute("SELECT * FROM reader_drafts WHERE id=?", (draft_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM reader_drafts WHERE id=? AND owner=?", (draft_id, owner)).fetchone()
    return dict(row) if row else None


def update_draft(draft_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    allowed = {"status", "stage", "fp_template", "nfc_uid", "user_id", "message", "expires_at"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    updates["updated_at"] = utcnow_iso()
    assignments = ", ".join(f"{key}=?" for key in updates)
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"UPDATE reader_drafts SET {assignments} WHERE id=?", (*updates.values(), draft_id))
    return get_draft(draft_id)


def list_pending_drafts() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM reader_drafts WHERE status NOT IN ('committed','cancelled') ORDER BY updated_at").fetchall()
    return [dict(row) for row in rows]


def list_credential_attempts(*, limit: int = 100) -> list[CredentialAttempt]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM credential_attempts ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_attempt_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Admin audit log
# ---------------------------------------------------------------------------


def log_audit(
    actor: str,
    action: str,
    entity_type: str,
    *,
    entity_id: Optional[str] = None,
    before: Optional[Any] = None,
    after: Optional[Any] = None,
) -> AdminAuditLogEntry:
    """Record a consequential administrative action."""
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO admin_audit_log (occurred_at, actor, action, entity_type, entity_id, before, after)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utcnow_iso(),
                actor,
                action,
                entity_type,
                None if entity_id is None else str(entity_id),
                None if before is None else json.dumps(before, default=str),
                None if after is None else json.dumps(after, default=str),
            ),
        )
        audit_id = cur.lastrowid
    entry = get_audit_entry(audit_id)
    assert entry is not None
    return entry


def get_audit_entry(audit_id: int) -> Optional[AdminAuditLogEntry]:
    with get_db() as db:
        row = db.execute("SELECT * FROM admin_audit_log WHERE id = ?", (audit_id,)).fetchone()
    return _audit_from_row(row) if row else None


def list_audit_log(*, limit: int = 100) -> list[AdminAuditLogEntry]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM admin_audit_log ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_audit_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Backup runs
# ---------------------------------------------------------------------------


def create_backup_run(destination: str) -> BackupRun:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO backup_runs (started_at, status, destination) VALUES (?, 'in_progress', ?)",
            (utcnow_iso(), destination),
        )
        run_id = cur.lastrowid
    run = get_backup_run(run_id)
    assert run is not None
    return run


def get_backup_run(run_id: int) -> Optional[BackupRun]:
    with get_db() as db:
        row = db.execute("SELECT * FROM backup_runs WHERE id = ?", (run_id,)).fetchone()
    return _backup_from_row(row) if row else None


def finish_backup_run(
    run_id: int, status: str, *, size_bytes: Optional[int] = None, error: Optional[str] = None
) -> Optional[BackupRun]:
    with get_db() as db:
        db.execute(
            "UPDATE backup_runs SET finished_at = ?, status = ?, size_bytes = ?, error = ? WHERE id = ?",
            (utcnow_iso(), status, size_bytes, error, run_id),
        )
    return get_backup_run(run_id)


def list_backup_runs(*, limit: int = 20) -> list[BackupRun]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM backup_runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_backup_from_row(row) for row in rows]


def latest_backup_run() -> Optional[BackupRun]:
    runs = list_backup_runs(limit=1)
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# Alerts (operator announcements shown on the displays)
# ---------------------------------------------------------------------------

_ALERT_ORDER = (
    "CASE severity WHEN 'critical' THEN 0 WHEN 'caution' THEN 1 ELSE 2 END, "
    "created_at ASC, id ASC"
)


def _clean_alert_message(message: str) -> str:
    cleaned = str(message or "").strip()
    if not cleaned:
        raise ValueError("Alert message must not be empty")
    if len(cleaned) > ALERT_MAX_LENGTH:
        raise ValueError(f"Alert message must be at most {ALERT_MAX_LENGTH} characters")
    return cleaned


def _validate_severity(severity: str) -> str:
    value = str(severity or "").strip().lower()
    if value not in ALERT_SEVERITIES:
        raise ValueError(f"Unknown alert severity: {severity!r}")
    return value


def expires_in(ttl_seconds: Optional[int]) -> Optional[str]:
    """Translate a lifetime in seconds to an ISO expiry, or ``None`` for never."""
    if ttl_seconds is None:
        return None
    try:
        seconds = int(ttl_seconds)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return _iso_from_dt(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def list_alerts(*, include_expired: bool = False) -> list[Alert]:
    """Active alerts, ordered by severity (critical first) then oldest first."""
    now = utcnow_iso()
    where = "" if include_expired else "WHERE expires_at IS NULL OR expires_at > ?"
    params: tuple[Any, ...] = () if include_expired else (now,)
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM alerts {where} ORDER BY {_ALERT_ORDER}", params
        ).fetchall()
    return [_alert_from_row(row) for row in rows]


def get_alert(alert_id: int) -> Optional[Alert]:
    with get_db() as db:
        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return _alert_from_row(row) if row else None


def create_alert(
    message: str, severity: str, *, ttl_seconds: Optional[int] = None
) -> Alert:
    cleaned = _clean_alert_message(message)
    level = _validate_severity(severity)
    now = utcnow_iso()
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO alerts (message, severity, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cleaned, level, expires_in(ttl_seconds), now, now),
        )
        alert_id = cur.lastrowid
    alert = get_alert(alert_id)
    assert alert is not None
    return alert


def update_alert(
    alert_id: int,
    *,
    message: Optional[str] = None,
    severity: Optional[str] = None,
    expires_at: Any = _KEEP,
) -> Optional[Alert]:
    """Patch an alert. Pass ``expires_at=None`` to remove its expiry."""
    fields: dict[str, Any] = {}
    if message is not None:
        fields["message"] = _clean_alert_message(message)
    if severity is not None:
        fields["severity"] = _validate_severity(severity)
    if expires_at is not _KEEP:
        fields["expires_at"] = expires_at
    if not fields:
        return get_alert(alert_id)
    fields["updated_at"] = utcnow_iso()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    with get_db() as db:
        db.execute(
            f"UPDATE alerts SET {assignments} WHERE id = ?",
            (*fields.values(), alert_id),
        )
    return get_alert(alert_id)


def delete_alert(alert_id: int) -> bool:
    with get_db() as db:
        cur = db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        return cur.rowcount > 0


def purge_expired_alerts() -> int:
    """Physically drop alerts whose lifetime has elapsed."""
    with get_db() as db:
        cur = db.execute(
            "DELETE FROM alerts WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (utcnow_iso(),),
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# Settings (persisted display configuration)
# ---------------------------------------------------------------------------


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None or row["value"] is None:
        return default
    return row["value"]


def set_setting(key: str, value: Optional[str]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, utcnow_iso()),
        )


def all_settings() -> dict[str, Optional[str]]:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return {row["key"]: row["value"] for row in rows}


# ---------------------------------------------------------------------------
# Screen settings
# ---------------------------------------------------------------------------

SCREEN_TARGETS = ("display", "admin-display")

_SCREEN_FLAGS = ("show_greeter", "show_clock", "show_date", "show_photos", "show_tools",
                 "show_digital_time", "show_summary", "show_check_in", "show_names", "show_feedback")

DEFAULT_SCREEN_SETTINGS: dict[str, Any] = {
    "show_greeter": True,
    "show_clock": True,
    "show_date": True,
    "show_photos": True,
    "show_tools": True,
    "show_digital_time": True,
    "show_summary": True,
    "show_check_in": True,
    "show_names": True,
    "show_feedback": True,
    "date_size": 18,
}


def get_screen_settings(screen: str = "display") -> dict[str, Any]:
    """Persisted layout for ``display`` or ``admin-display``, defaults filled in."""
    raw = get_setting(f"display_settings_{screen}")
    settings = dict(DEFAULT_SCREEN_SETTINGS)
    if raw:
        try:
            stored = json.loads(raw)
        except ValueError:
            stored = {}
        if isinstance(stored, dict):
            settings.update({key: value for key, value in stored.items() if key in DEFAULT_SCREEN_SETTINGS})
    result = {flag: bool(settings[flag]) for flag in _SCREEN_FLAGS}
    value = settings.get('date_size')
    result['date_size'] = max(14, min(32, value)) if type(value) is int else 18
    return result


def set_screen_settings(screen: str, settings: dict[str, Any]) -> dict[str, Any]:
    """Merge ``settings`` into the stored layout for one screen target."""
    merged = get_screen_settings(screen)
    if isinstance(settings, dict):
        merged.update({key: settings[key] for key in _SCREEN_FLAGS if key in settings})
    if isinstance(settings, dict) and 'date_size' in settings:
        value = settings['date_size']
        if type(value) is not int or not 14 <= value <= 32:
            raise ValueError('Date size must be between 14 and 32 pixels')
        merged['date_size'] = value
    for flag in _SCREEN_FLAGS:
        merged[flag] = bool(merged[flag])
    set_setting(f"display_settings_{screen}", json.dumps(merged))
    return merged


# ---------------------------------------------------------------------------
# Introspection (used by the backup service)
# ---------------------------------------------------------------------------


def table_columns(table: str) -> list[str]:
    with get_db() as db:
        rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return [row["name"] for row in rows]


def table_rows(table: str, columns: Sequence[str]) -> tuple[list[str], list[tuple]]:
    """Return ``(columns, rows)`` for a whole table in backup load order."""
    cols = ", ".join(columns)
    with get_db() as db:
        rows = db.execute(f"SELECT {cols} FROM {table}").fetchall()
    return list(columns), [tuple(row) for row in rows]


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_credential(kind: str, identifier: str) -> str:
    """Canonicalize physical UIDs/template references, retaining legacy IDs."""
    import re
    if kind not in ('nfc', 'fingerprint') or not isinstance(identifier, str) or not identifier.strip():
        raise ValueError('Credential type and identifier are required')
    value = identifier.strip()
    if kind == 'nfc':
        compact = re.sub(r'[:\s-]', '', value)
        if len(compact) in (8, 14, 20) and re.fullmatch(r'[a-fA-F0-9]+', compact):
            return compact.upper()
    if kind == 'fingerprint' and re.fullmatch(r'(?:template:)?[0-9]+', value, re.I):
        number = int(value.split(':')[-1])
        if not 1 <= number <= 1000:
            raise ValueError('Fingerprint template ID must be between 1 and 1000')
        return f'template:{number}'
    return value


def duplicate_error(error: Exception) -> str:
    message = str(error)
    if 'credential' in message:
        return 'This NFC UID or fingerprint is already enrolled'
    if 'plaksha' in message:
        return 'This Plaksha ID is already enrolled'
    return 'This record conflicts with an existing entry'
