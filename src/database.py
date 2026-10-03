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

#: Canonical, pre-defined access areas. Insert-only seed; never overwritten.
DEFAULT_ACCESS_AREAS: tuple[tuple[str, str, int], ...] = (
    ("indoor_lab", "Indoor lab", 10),
    ("tool_area", "Tool area", 20),
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
    "backup_runs",
    "current_presence",
)

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        plaksha_id  TEXT,
        name        TEXT NOT NULL,
        photo       TEXT NOT NULL DEFAULT '/static/portraits/default.svg',
        is_temp     INTEGER NOT NULL DEFAULT 0 CHECK (is_temp IN (0, 1)),
        status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_plaksha_id ON users (plaksha_id) WHERE plaksha_id IS NOT NULL",
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
    "CREATE UNIQUE INDEX IF NOT EXISTS uniq_credential_identifier ON credentials (credential_type, identifier)",
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
)


# ---------------------------------------------------------------------------
# Paths, connections and time helpers
# ---------------------------------------------------------------------------


def project_root() -> Path:
    """Return the repository/source root regardless of how the app was launched."""
    if getattr(sys, "frozen", False):  # PyInstaller onefile
        return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return Path(__file__).resolve().parent.parent


def db_path() -> Path:
    """Resolve the SQLite database path.

    Overridable with ``LABAUTH_DB_PATH`` (required by the test-suite so it never
    touches the real database).
    """
    override = os.environ.get("LABAUTH_DB_PATH")
    if override:
        return Path(override).expanduser()
    return project_root() / "data" / "labauth.db"


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


def iso_to_local_hhmm(value: str) -> str:
    """Format a stored ISO timestamp as a local ``HH:MM`` display string."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        return "--:--"


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
    seed_default_access_areas()


def seed_default_access_areas() -> None:
    """Insert the canonical access areas if they are not already present."""
    with get_db() as db:
        for code, label, order in DEFAULT_ACCESS_AREAS:
            db.execute(
                "INSERT OR IGNORE INTO access_areas (code, label, sort_order) VALUES (?, ?, ?)",
                (code, label, order),
            )


# ---------------------------------------------------------------------------
# Row mapping helpers
# ---------------------------------------------------------------------------


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        name=row["name"],
        plaksha_id=row["plaksha_id"],
        photo=row["photo"],
        is_temp=bool(row["is_temp"]),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
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

    Known aliases (``indoor_lab`` / ``tool_area`` and their spellings) always map
    to the canonical rows. Unknown values are only inserted when
    ``allow_create`` is true; the enrollment UI is expected to pass false and
    offer only the pre-defined checkboxes.
    """
    key = (name or "").strip()
    if not key:
        raise ValueError("Access area name must not be empty")

    code = ACCESS_AREA_ALIASES.get(key.lower(), _slugify(key))
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
    is_temp: bool = False,
    status: str = "active",
) -> User:
    now = utcnow_iso()
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO users (plaksha_id, name, photo, is_temp, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_clean(plaksha_id), name.strip(), photo or DEFAULT_PHOTO, int(bool(is_temp)), status, now, now),
        )
        user_id = cur.lastrowid
    user = get_user(user_id)
    assert user is not None
    return user


def get_user(user_id: int) -> Optional[User]:
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_from_row(row) if row else None


def get_user_by_plaksha_id(plaksha_id: str) -> Optional[User]:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM users WHERE plaksha_id = ?", (_clean(plaksha_id),)
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
    clauses, params = [], []
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
            "SELECT * FROM users WHERE is_temp = 1 ORDER BY created_at DESC, id DESC"
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
    allowed = {"name", "plaksha_id", "photo", "is_temp", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user(user_id)
    if "is_temp" in updates:
        updates["is_temp"] = int(bool(updates["is_temp"]))
    if "plaksha_id" in updates:
        updates["plaksha_id"] = _clean(updates["plaksha_id"])
    updates["updated_at"] = utcnow_iso()
    assignments = ", ".join(f"{column} = ?" for column in updates)
    with get_db() as db:
        db.execute(
            f"UPDATE users SET {assignments} WHERE id = ?",
            (*updates.values(), user_id),
        )
    return get_user(user_id)


def set_user_status(user_id: int, status: str) -> Optional[User]:
    return update_user(user_id, status=status)


def delete_user(user_id: int) -> bool:
    with get_db() as db:
        cur = db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


def count_users() -> int:
    with get_db() as db:
        return int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def set_user_access_areas(
    user_id: int,
    names: Sequence[str],
    *,
    granted_by: Optional[str] = None,
    allow_create: bool = True,
) -> None:
    """Replace a user's granted access areas with ``names``."""
    area_ids: list[int] = []
    for name in names:
        if name and name.strip():
            area_ids.append(ensure_access_area(name, allow_create=allow_create).id)
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
        row = db.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
    return _credential_from_row(row) if row else None


def resolve_user_by_credential(credential_type: str, identifier: str) -> Optional[User]:
    with get_db() as db:
        row = db.execute(
            """
            SELECT u.* FROM credentials c
            JOIN users u ON u.id = c.user_id
            WHERE c.credential_type = ? AND c.identifier = ? AND c.is_active = 1
            LIMIT 1
            """,
            (credential_type, identifier),
        ).fetchone()
    return _user_from_row(row) if row else None


def list_credentials(*, user_id: Optional[int] = None) -> list[Credential]:
    if user_id is None:
        with get_db() as db:
            rows = db.execute("SELECT * FROM credentials ORDER BY enrolled_at DESC").fetchall()
    else:
        with get_db() as db:
            rows = db.execute(
                "SELECT * FROM credentials WHERE user_id = ? ORDER BY enrolled_at DESC",
                (user_id,),
            ).fetchall()
    return [_credential_from_row(row) for row in rows]


def set_credential_active(credential_id: int, is_active: bool) -> None:
    with get_db() as db:
        db.execute(
            "UPDATE credentials SET is_active = ? WHERE id = ?",
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


def current_occupants() -> list[CurrentOccupant]:
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
                checked_in=iso_to_local_hhmm(row["presence_checked_in_at"]),
            )
            for row in rows
        ]
    return occupants


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
