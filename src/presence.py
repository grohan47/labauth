from dataclasses import dataclass
from datetime import datetime
from typing import Callable
import threading


@dataclass(frozen=True)
class PersonInside:
    name: str
    photo: str
    checked_in: str
    access: tuple[str, ...]


    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "photo": self.photo,
            "checked_in": self.checked_in,
            "access": list(self.access),
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

DEFAULT_PORTRAIT = "/static/portraits/default.svg"

SAMPLE_PORTRAITS = (
    DEFAULT_PORTRAIT,
)

SAMPLE_ACCESS_LISTS = (
    ("Lab interior", "Tool area"),
    ("Lab interior", "3D printers"),
    ("Lab interior", "Soldering bench"),
    ("Lab interior", "Laser cutter"),
    ("Lab interior", "CNC mill"),
    ("Lab interior", "Electronics bench"),
)

DEFAULT_PEOPLE = (
    PersonInside(
        name="Aisha Khan",
        photo=DEFAULT_PORTRAIT,
        checked_in="08:42",
        access=("Lab interior", "Tool area"),
    ),
    PersonInside(
        name="Rohan Gupta",
        photo=DEFAULT_PORTRAIT,
        checked_in="09:16",
        access=("Lab interior", "3D printers"),
    ),
    PersonInside(
        name="Meera Nair",
        photo=DEFAULT_PORTRAIT,
        checked_in="10:03",
        access=("Lab interior", "Soldering bench"),
    ),
)


class PresenceStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._people: list[PersonInside] = list(DEFAULT_PEOPLE)
        self._listeners: list[Callable[..., None]] = []
        self._mock_time: str | None = None
        self._mock_date: str | None = None
        self._events: list[dict] = []
        self._event_counter: int = 0

    def get_people(self) -> tuple[PersonInside, ...]:
        with self._lock:
            return tuple(self._people)

    def check_in(
        self,
        name: str,
        photo: str = DEFAULT_PORTRAIT,
        access: tuple[str, ...] = ("Lab interior", "Tool area"),
        checked_in: str | None = None,
    ) -> PersonInside:
        import time
        if not checked_in:
            checked_in = self._mock_time if self._mock_time else datetime.now().strftime("%H:%M")
        person = PersonInside(
            name=name.strip(),
            photo=photo.strip(),
            checked_in=checked_in.strip(),
            access=tuple(a.strip() for a in access if a.strip()),
        )
        with self._lock:
            self._people = [p for p in self._people if p.name.lower() != name.strip().lower()]
            self._people.append(person)
            self._event_counter += 1
            event = {
                "id": self._event_counter,
                "type": "IN",
                "person": person.to_dict(),
                "check_in": person.checked_in,
                "check_out": None,
                "timestamp": time.time(),
            }
            self._events.append(event)
            if len(self._events) > 100:
                self._events = self._events[-100:]
        self._notify(event)
        return person

    def check_out(
        self,
        name: str,
        check_out_time: str | None = None,
    ) -> tuple[bool, PersonInside | None, str]:
        import time
        if not check_out_time:
            check_out_time = self._mock_time if self._mock_time else datetime.now().strftime("%H:%M")
        with self._lock:
            initial_len = len(self._people)
            removed_person = next((p for p in self._people if p.name.lower() == name.strip().lower()), None)
            self._people = [p for p in self._people if p.name.lower() != name.strip().lower()]
            changed = len(self._people) != initial_len
            event = None
            if changed and removed_person:
                self._event_counter += 1
                event = {
                    "id": self._event_counter,
                    "type": "OUT",
                    "person": removed_person.to_dict(),
                    "check_in": removed_person.checked_in,
                    "check_out": check_out_time,
                    "timestamp": time.time(),
                }
                self._events.append(event)
                if len(self._events) > 100:
                    self._events = self._events[-100:]
        if event:
            self._notify(event)
        return changed, removed_person, check_out_time

    def reset(self) -> None:
        with self._lock:
            self._people = list(DEFAULT_PEOPLE)
        self._notify()

    def set_people(self, people: list[PersonInside]) -> None:
        with self._lock:
            self._people = list(people)
        self._notify()

    def populate(self, count: int) -> list[PersonInside]:
        new_people = []
        for i in range(count):
            name = SAMPLE_NAMES[i % len(SAMPLE_NAMES)]
            if i >= len(SAMPLE_NAMES):
                name = f"{name} {i // len(SAMPLE_NAMES) + 1}"
            photo = SAMPLE_PORTRAITS[i % len(SAMPLE_PORTRAITS)]
            access = SAMPLE_ACCESS_LISTS[i % len(SAMPLE_ACCESS_LISTS)]
            hour = 8 + (i * 17) // 60
            minute = (i * 17) % 60
            checked_in = f"{hour:02d}:{minute:02d}"
            new_people.append(PersonInside(name=name, photo=photo, checked_in=checked_in, access=access))
        with self._lock:
            self._people = new_people
        self._notify()
        return new_people

    def add_listener(self, listener: Callable[..., None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[..., None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self, event: dict | None = None) -> None:
        if event:
            import time
            self._last_event = (event, time.time())
        for listener in list(self._listeners):
            try:
                import inspect
                sig = inspect.signature(listener)
                if len(sig.parameters) > 0:
                    listener(event)
                else:
                    listener()
            except Exception:
                pass

    def get_recent_event(self, max_age_seconds: float = 5.0) -> dict | None:
        with self._lock:
            if not getattr(self, "_last_event", None):
                return None
            import time
            event, ts = self._last_event
            if (time.time() - ts) <= max_age_seconds:
                return event
            return None

    def get_events(self, since_id: int = 0, max_age_seconds: float = 30.0) -> list[dict]:
        with self._lock:
            import time
            now = time.time()
            return [
                e for e in self._events
                if e.get("id", 0) > since_id and (now - e.get("timestamp", 0)) <= max_age_seconds
            ]

    def set_mock_time(self, mock_time: str | None, mock_date: str | None = None) -> None:
        self._mock_time = mock_time
        self._mock_date = mock_date
        self._notify()

    def get_mock_time(self) -> str | None:
        return self._mock_time

    def get_mock_date(self) -> str | None:
        return self._mock_date


store = PresenceStore()
