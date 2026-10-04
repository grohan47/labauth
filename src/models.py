"""Domain models for the LabAuth datastore.

These are plain, immutable value objects. They intentionally contain no
persistence logic; the mapping to and from SQLite lives in ``database.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AccessArea:
    """A pre-defined area a user may be authorised for (e.g. Indoor lab)."""

    id: int
    code: str
    label: str
    sort_order: Optional[int] = None


@dataclass(frozen=True)
class User:
    """A person known to the system. May be a student, staff or temporary."""

    id: int
    name: str
    plaksha_id: Optional[str]
    photo: str
    is_temp: bool
    status: str
    created_at: str
    updated_at: str
    email: Optional[str] = None
    phone: Optional[str] = None


@dataclass(frozen=True)
class Credential:
    """An authentication credential (NFC UID or fingerprint template)."""

    id: int
    user_id: int
    credential_type: str
    identifier: str
    is_active: bool
    enrolled_at: str
    template: Optional[bytes] = None


@dataclass(frozen=True)
class Ban:
    """A ban timeline entry. ``unbanned_at is None`` means the ban is open."""

    id: int
    user_id: int
    reason: Optional[str]
    banned_at: str
    unbanned_at: Optional[str]
    banned_by: Optional[str]


@dataclass(frozen=True)
class PresenceLogEntry:
    """A single immutable in/out log entry."""

    id: int
    user_id: int
    event_type: str  # 'check_in' | 'check_out'
    entry_method: str  # 'nfc' | 'fingerprint' | 'manual'
    credential_id: Optional[int]
    occurred_at: str
    device_id: Optional[str]
    metadata: Optional[str]


@dataclass(frozen=True)
class CredentialAttempt:
    """A logged authentication attempt, successful or otherwise."""

    id: int
    occurred_at: str
    credential_type: str
    identifier: str
    user_id: Optional[int]
    outcome: str
    message: Optional[str]
    device_id: Optional[str]


@dataclass(frozen=True)
class AdminAuditLogEntry:
    """A record of a consequential administrative action."""

    id: int
    occurred_at: str
    actor: str
    action: str
    entity_type: str
    entity_id: Optional[str]
    before: Optional[str]
    after: Optional[str]


@dataclass(frozen=True)
class BackupRun:
    """Outcome record for a single backup attempt."""

    id: int
    started_at: str
    finished_at: Optional[str]
    status: str  # 'in_progress' | 'success' | 'failed'
    destination: str
    size_bytes: Optional[int]
    error: Optional[str]


@dataclass(frozen=True)
class CurrentOccupant:
    """A user currently inside, assembled for the live display."""

    user: User
    access: tuple[str, ...]
    checked_in: str  # display time, HH:MM


@dataclass(frozen=True)
class PresenceEvent:
    """A presence log entry joined with the acting user and their access."""

    entry: PresenceLogEntry
    user: User
    access: tuple[str, ...]
