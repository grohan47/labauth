"""Presence state for LabAuth.

The store keeps the small amount of ephemeral app state (mock clock, active
alert, websocket listeners) in memory, but all durable state — users, access
areas, in/out logs and the realtime presence cache — lives in SQLite via
:mod:`database`.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

import database as db


@dataclass(frozen=True)
class PersonInside:
    name: str
    photo: str
    checked_in: str
    access: tuple[str, ...]
    user_id: int | None = None
    is_temp: bool = False

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "photo": self.photo,
            "checked_in": self.checked_in,
            "access": list(self.access),
            "is_temp": self.is_temp,
        }


SAMPLE_NAMES = (
    "Aisha Khan",
    "Rohan Gupta",
    "Meera Nair",
    "David Kim",
    "Elena Rossi",
    "Lucas Silva",
    "Priya Patel",
    "Marcus Chen",
    "Sofia Alvarez",
    "Alexander Mueller",
    "Fatima Al-Mansoor",
    "Lars Lindqvist",
    "Chloe Dubois",
    "Hiroshi Tanaka",
    "Emma Watson",
    "Carlos Mendez",
    "Ananya Sharma",
    "James Wilson",
)

DEFAULT_PORTRAIT = db.DEFAULT_PHOTO

SAMPLE_PORTRAITS = (DEFAULT_PORTRAIT,)

# Canonical, pre-defined access areas (see database.DEFAULT_ACCESS_AREAS).
SAMPLE_ACCESS_LISTS: tuple[tuple[str, ...], ...] = (
    ("Indoor lab",),
    ("Tool area",),
    ("Indoor lab", "Tool area"),
)

DEFAULT_PEOPLE = (
    PersonInside(
        name="Aisha Khan",
        photo=DEFAULT_PORTRAIT,
        checked_in="08:42",
        access=("Indoor lab",),
    ),
    PersonInside(
        name="Rohan Gupta",
        photo=DEFAULT_PORTRAIT,
        checked_in="09:16",
        access=("Indoor lab", "Tool area"),
    ),
    PersonInside(
        name="Meera Nair",
        photo=DEFAULT_PORTRAIT,
        checked_in="10:03",
        access=("Tool area",),
    ),
)


class PresenceStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listeners: list[Callable[..., None]] = []
        self._mock_time: str | None = None
        self._mock_date: str | None = None
        self._alert: str | None = None
        db.init_db()
        self._seed_if_empty()

    # -- seeding -----------------------------------------------------------

    def _seed_if_empty(self) -> None:
        if db.count_users() == 0 and db.count_presence() == 0:
            self.reset()

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _person(user: db.User, checked_in: str, access: Iterable[str]) -> PersonInside:
        return PersonInside(
            user_id=user.id,
            name=user.name,
            photo=user.photo,
            checked_in=checked_in,
            access=tuple(access),
            is_temp=user.is_temp,
        )

    @staticmethod
    def _display_of(entry) -> str:
        if entry is not None and entry.metadata:
            try:
                value = json.loads(entry.metadata).get("display_time")
                if value:
                    return value
            except (ValueError, TypeError):
                pass
        if entry is None:
            return "--:--"
        return db.iso_to_local_hhmm(entry.occurred_at)

    @staticmethod
    def _build_event(entry, person: PersonInside, *, check_in: str, check_out: str | None) -> dict:
        return {
            "id": entry.id,
            "type": "IN" if entry.event_type == "check_in" else "OUT",
            "person": person.to_dict(),
            "check_in": check_in,
            "check_out": check_out,
            "timestamp": db.iso_to_epoch(entry.occurred_at),
        }

    def _event_from_presence(self, presence: db.PresenceEvent) -> dict:
        entry = presence.entry
        user = presence.user
        if entry.event_type == "check_in":
            display = self._display_of(entry)
            person = self._person(user, display, presence.access)
            return self._build_event(entry, person, check_in=display, check_out=None)
        display = self._display_of(entry)
        last_in = db.latest_check_in_entry(user.id)
        checked_in = self._display_of(last_in) if last_in else "--:--"
        person = self._person(user, checked_in, presence.access)
        return self._build_event(entry, person, check_in=checked_in, check_out=display)

    # -- reads -------------------------------------------------------------

    def get_people(self) -> tuple[PersonInside, ...]:
        return tuple(
            PersonInside(
                user_id=occupant.user.id,
                name=occupant.user.name,
                photo=occupant.user.photo,
                checked_in=occupant.checked_in,
                access=occupant.access,
                is_temp=occupant.user.is_temp,
            )
            for occupant in db.current_occupants()
        )

    # -- mutations ---------------------------------------------------------

    def check_in(
        self,
        name: str,
        photo: str = DEFAULT_PORTRAIT,
        access: tuple[str, ...] = ("Indoor lab", "Tool area"),
        checked_in: str | None = None,
        *,
        is_temp: bool = False,
        plaksha_id: str | None = None,
    ) -> PersonInside:
        name = (name or "").strip()
        access = tuple(item.strip() for item in access if item and item.strip())
        with self._lock:
            user = db.get_active_user_by_name(name)
            if user is None and plaksha_id:
                user = db.get_user_by_plaksha_id(plaksha_id)
            if user is None:
                user = db.create_user(
                    name,
                    plaksha_id=plaksha_id,
                    photo=photo or DEFAULT_PORTRAIT,
                    is_temp=is_temp,
                )
            else:
                updates: dict[str, object] = {}
                if photo and photo != user.photo:
                    updates["photo"] = photo
                if plaksha_id and not user.plaksha_id:
                    updates["plaksha_id"] = plaksha_id
                if updates:
                    db.update_user(user.id, **updates)
                    user = db.get_user(user.id)

            db.set_user_access_areas(user.id, access, allow_create=True)
            labels = tuple(db.get_user_access_area_labels(user.id))
            occurred_at = db.utcnow_iso()
            presence_at = db.local_hhmm_to_iso(checked_in) if checked_in else occurred_at
            display_time = db.iso_to_local_hhmm(presence_at)
            entry = db.log_presence(
                user.id,
                "check_in",
                "manual",
                occurred_at=occurred_at,
                metadata={"display_time": display_time},
            )
            db.upsert_current_presence(user.id, presence_at)
            person = self._person(user, display_time, labels)

        self._notify(self._build_event(entry, person, check_in=display_time, check_out=None))
        return person

    def check_out(
        self,
        name: str,
        check_out_time: str | None = None,
    ) -> tuple[bool, PersonInside | None, str]:
        name = (name or "").strip()
        out_display = check_out_time or db.iso_to_local_hhmm(db.utcnow_iso())
        with self._lock:
            user = db.get_active_user_by_name(name)
            if user is None or not db.is_user_inside(user.id):
                return False, None, out_display

            occurred_at = db.utcnow_iso()
            entry = db.log_presence(
                user.id,
                "check_out",
                "manual",
                occurred_at=occurred_at,
                metadata={"display_time": out_display},
            )
            db.remove_current_presence(user.id)
            access = tuple(db.get_user_access_area_labels(user.id))
            last_in = db.latest_check_in_entry(user.id)
            checked_in = self._display_of(last_in) if last_in else "--:--"
            person = self._person(user, checked_in, access)

        self._notify(self._build_event(entry, person, check_in=checked_in, check_out=out_display))
        return True, person, out_display

    def reset(self) -> None:
        with self._lock:
            db.clear_current_presence()
            for person in DEFAULT_PEOPLE:
                user = db.get_active_user_by_name(person.name)
                if user is None:
                    user = db.create_user(person.name, photo=person.photo)
                db.set_user_access_areas(user.id, person.access, allow_create=True)
                db.upsert_current_presence(user.id, db.local_hhmm_to_iso(person.checked_in))
        self._notify()

    def set_people(self, people: Iterable[PersonInside]) -> None:
        with self._lock:
            db.clear_current_presence()
            for person in people:
                user = db.get_active_user_by_name(person.name)
                if user is None:
                    user = db.create_user(person.name, photo=person.photo)
                db.set_user_access_areas(user.id, person.access, allow_create=True)
                db.upsert_current_presence(user.id, db.local_hhmm_to_iso(person.checked_in))
        self._notify()

    def populate(self, count: int) -> list[PersonInside]:
        count = max(0, min(int(count), 48))
        created: list[PersonInside] = []
        with self._lock:
            db.clear_current_presence()
            for i in range(count):
                name = SAMPLE_NAMES[i % len(SAMPLE_NAMES)]
                if i >= len(SAMPLE_NAMES):
                    name = f"{name} {i // len(SAMPLE_NAMES) + 1}"
                user = db.get_active_user_by_name(name)
                if user is None:
                    user = db.create_user(name, photo=SAMPLE_PORTRAITS[i % len(SAMPLE_PORTRAITS)])
                access = SAMPLE_ACCESS_LISTS[i % len(SAMPLE_ACCESS_LISTS)]
                db.set_user_access_areas(user.id, access, allow_create=True)
                hour = 8 + (i * 17) // 60
                minute = (i * 17) % 60
                checked_in = f"{hour:02d}:{minute:02d}"
                db.upsert_current_presence(user.id, db.local_hhmm_to_iso(checked_in))
                created.append(self._person(user, checked_in, access))
        self._notify()
        return created

    # -- realtime event feed ----------------------------------------------

    def get_recent_event(self, max_age_seconds: float = 5.0) -> dict | None:
        events = db.presence_events_since(0, max_age_seconds)
        if not events:
            return None
        return self._event_from_presence(events[-1])

    def get_events(self, since_id: int = 0, max_age_seconds: float = 30.0) -> list[dict]:
        return [
            self._event_from_presence(presence)
            for presence in db.presence_events_since(since_id, max_age_seconds)
        ]

    # -- listeners ---------------------------------------------------------

    def add_listener(self, listener: Callable[..., None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[..., None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self, event: dict | None = None) -> None:
        for listener in list(self._listeners):
            try:
                import inspect

                signature = inspect.signature(listener)
                if len(signature.parameters) > 0:
                    listener(event)
                else:
                    listener()
            except Exception:
                pass

    # -- ephemeral mock state ---------------------------------------------

    def set_mock_time(self, mock_time: str | None, mock_date: str | None = None) -> None:
        self._mock_time = mock_time
        self._mock_date = mock_date
        self._notify()

    def get_mock_time(self) -> str | None:
        return self._mock_time

    def get_mock_date(self) -> str | None:
        return self._mock_date

    def set_alert(self, text: str | None) -> None:
        with self._lock:
            self._alert = text.strip() if text and text.strip() else None
        self._notify({"type": "alert", "alert": self._alert})

    def get_alert(self) -> str | None:
        with self._lock:
            return self._alert


# ``PersonInside`` remains the display-facing projection of a user.
store = PresenceStore()
