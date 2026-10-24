"""Atomic credential decisions and attendance writes for serial readers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import database as db


def _now() -> tuple[datetime, str]:
    value = datetime.now(timezone.utc)
    return value, db._iso_from_dt(value)


def process_credential(
    kind: str,
    identifier: str,
    mode: str,
    device_id: str = "pico",
    cooldown_seconds: float = 3.0,
) -> dict[str, Any]:
    """Validate an enrolled credential and atomically record its decision.

    ``CHECK`` performs identity lookup and attempt logging only. ``POLL`` toggles
    presence and appends the immutable attendance event in the same transaction.
    """
    if kind not in ("nfc", "fingerprint"):
        raise ValueError("kind must be nfc or fingerprint")
    mode = mode.upper()
    if mode not in ("CHECK", "POLL"):
        raise ValueError("mode must be CHECK or POLL")
    identifier = str(identifier)
    now, timestamp = _now()
    outcome = "unknown_credential"
    stored_outcome = outcome
    message = "Credential not enrolled"
    user: dict[str, Any] | None = None
    event: dict[str, Any] | None = None

    with db.get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT c.id credential_id, c.user_id, c.credential_type, c.identifier,
                      u.name, u.photo, u.plaksha_id, u.status, u.is_temp
               FROM credentials c JOIN users u ON u.id=c.user_id
               WHERE c.credential_type=? AND c.identifier=? AND c.is_active=1""",
            (kind, identifier),
        ).fetchone()

        if row:
            access = db._labels_for(conn, row["user_id"])
            user = {"id": row["user_id"], "name": row["name"], "photo": row["photo"],
                    "plaksha_id": row["plaksha_id"], "status": row["status"], "access": access}
            banned = conn.execute(
                "SELECT 1 FROM bans WHERE user_id=? AND unbanned_at IS NULL LIMIT 1",
                (row["user_id"],),
            ).fetchone() is not None
            inside = conn.execute(
                "SELECT checked_in_at FROM current_presence WHERE user_id=?", (row["user_id"],)
            ).fetchone()

            if row["status"] != "active" or banned:
                outcome, stored_outcome, message = "denied", "reader_error", "Account is not authorised"
            elif mode == "POLL" and inside is None and not access:
                outcome, stored_outcome, message = "denied", "reader_error", "No access area is assigned"
            else:
                last = conn.execute(
                    """SELECT occurred_at FROM credential_attempts
                       WHERE user_id=? AND outcome='success'
                       ORDER BY id DESC LIMIT 1""",
                    (row["user_id"],),
                ).fetchone()
                recent = False
                if last and cooldown_seconds > 0:
                    try:
                        previous = datetime.fromisoformat(last["occurred_at"].replace("Z", "+00:00"))
                        recent = (now - previous).total_seconds() < cooldown_seconds
                    except (ValueError, TypeError):
                        recent = False
                if recent:
                    outcome, message = "cooldown", "Credential used recently"
                else:
                    outcome, message = "success", ""
                    person = {
                        "user_id": row["user_id"], "name": row["name"], "photo": row["photo"],
                        "access": access, "checked_in": inside is not None,
                        "is_temp": bool(row["is_temp"]),
                    }
                    if mode == "CHECK":
                        # Reuse the normal person card using recorded presence;
                        # looking up a finger must never invent an attendance event.
                        person["is_inside"] = inside is not None
                        if inside:
                            check_in = inside["checked_in_at"]
                            check_out = None
                        else:
                            last_visit = conn.execute(
                                """SELECT MAX(CASE WHEN event_type='check_in' THEN occurred_at END) AS check_in,
                                          MAX(CASE WHEN event_type='check_out' THEN occurred_at END) AS check_out
                                   FROM presence_log WHERE user_id=?""",
                                (row["user_id"],),
                            ).fetchone()
                            check_in, check_out = last_visit["check_in"], last_visit["check_out"]
                        event = {"type": "CHECK", "person": person,
                                 "check_in": db.iso_to_local_hhmm(check_in) if check_in else None,
                                 "check_out": db.iso_to_local_hhmm(check_out) if check_out else None,
                                 "timestamp": timestamp}
                    elif inside is None:
                        conn.execute(
                            "INSERT INTO presence_log (user_id,event_type,entry_method,credential_id,occurred_at,device_id,metadata) VALUES (?, 'check_in', ?, ?, ?, ?, NULL)",
                            (row["user_id"], kind, row["credential_id"], timestamp, device_id),
                        )
                        conn.execute(
                            "INSERT INTO current_presence (user_id,checked_in_at,updated_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET checked_in_at=excluded.checked_in_at, updated_at=excluded.updated_at",
                            (row["user_id"], timestamp, timestamp),
                        )
                        person["checked_in"] = True
                        event = {"type": "IN", "person": person,
                                 "check_in": db.iso_to_local_hhmm(timestamp), "check_out": None,
                                 "timestamp": timestamp}
                    else:
                        conn.execute(
                            "INSERT INTO presence_log (user_id,event_type,entry_method,credential_id,occurred_at,device_id,metadata) VALUES (?, 'check_out', ?, ?, ?, ?, NULL)",
                            (row["user_id"], kind, row["credential_id"], timestamp, device_id),
                        )
                        conn.execute("DELETE FROM current_presence WHERE user_id=?", (row["user_id"],))
                        person["checked_in"] = False
                        event = {"type": "OUT", "person": person,
                                 "check_in": db.iso_to_local_hhmm(inside["checked_in_at"]),
                                 "check_out": db.iso_to_local_hhmm(timestamp), "timestamp": timestamp}
            stored_outcome = outcome if outcome != "denied" else "reader_error"

        conn.execute(
            "INSERT INTO credential_attempts (occurred_at,credential_type,identifier,user_id,outcome,message,device_id) VALUES (?,?,?,?,?,?,?)",
            (timestamp, kind, identifier, row["user_id"] if row else None, stored_outcome, message or None, device_id),
        )

    return {"outcome": outcome, "user": user, "event": event}
