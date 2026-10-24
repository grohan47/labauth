# Pico reader backend

The Python application owns credential decisions, enrollment leases, attendance
writes and reader configuration. The Raspberry Pi Pico bridges the fingerprint
sensor and future NFC reader to the host over USB serial. The Pico reports
credential observations; it does not decide who is present or store names.

For Pico wiring, pin assignments, firmware build instructions and the complete
ASCII command reference, see the [firmware guide](../firmware/labauth_pico/README.md).

## Configure and run

Install the Python dependencies and start the app from the repository root:

```sh
uv sync
LABAUTH_PICO_PORT=/dev/ttyACM0 uv run python src/main.py
```

Set `LABAUTH_PICO_PORT` to the stable serial device path for the Pico. On Linux,
`/dev/serial/by-id/...` is preferable when available. Set it to `auto` to select
the only connected Raspberry Pi Pico (USB vendor ID `0x2E8A`); `auto` fails if
zero or multiple matching devices are found. When the variable is unset or
empty, the backend does not open a serial port and reader operations remain
unavailable. The server defaults to `127.0.0.1:8080`.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `LABAUTH_PICO_PORT` | empty | Serial device path, or `auto` for exactly one Pico. |
| `LABAUTH_PICO_DEVICE_ID` | `pico` | Device label recorded with credential attempts and presence events. |
| `LABAUTH_DB_PATH` | `data/labauth.db` | SQLite database path. |
| `LABAUTH_ADMIN_PASSWORD` | `labauth@2026` | Admin login password; set a deployment-specific value. |
| `PORT` | `8080` | Local NiceGUI HTTP port. |

The serial service uses 115200 baud. On POSIX it requests exclusive access to the
port. A configured but missing/unresponsive device is retried after a one-second
wait. `connected` means the USB serial link opened; `ready` means firmware
handshake and synchronization completed. These states are separate from each
reader's hardware state (`fp` and `nfc`).

The USB ASCII protocol currently has no device authentication (`AUTH_MODE` is
`0` in the firmware). Treat the physical USB connection and host as trusted;
admin HTTP authorization does not authenticate a separate process that can
open the Pico serial port.

On connection, the backend checks `PING` and `STATUS`, requires firmware
protocol version 1, cancels leftover work, waits for fingerprint cleanup,
selects `IDLE`, reconciles pending enrollment drafts, reapplies the stored reader
switches, and selects `POLL`. A command acknowledgment timeout closes the
connection so the service can reconnect and synchronize again. The firmware
details and command semantics are documented in the
[Pico firmware guide](../firmware/labauth_pico/README.md).

## Reader modes and decisions

The admin controls set `POLL`, `CHECK` or `IDLE`:

* `POLL` is normal attendance mode. A valid enrolled credential toggles the
  person's presence and appends one immutable presence event. An already
  present person checks out. The backend applies its per-user three-second
  success cooldown across fingerprint and NFC.
* `CHECK` resolves identity and logs the attempt without changing presence.
  Resolved reads show the existing user IN/OUT card, with current presence and
  recorded check-in/check-out times, rather than a generic confirmation.
  The currently implemented backend handles fingerprint match events in this
  mode; NFC UID events are accepted for attendance in `POLL`.
* `IDLE` stops normal credential processing while preserving the serial
  management channel.

Fingerprint matches are template references such as `template:41`; NFC UIDs are
validated as hexadecimal and stored uppercase. Raw fingerprint images and
templates do not enter the general attempt log. Unknown credentials, denied
access and reader faults create brief display feedback and credential-attempt
records. Cooldown rejections are logged but do not create a second alert.

Fingerprint and NFC enable switches are independent of mode and hardware
health. Their desired values persist in SQLite and are reapplied after a Pico
reconnect; firmware switch state itself is temporary. Disabling fingerprint
cancels active fingerprint work and requests the sensor LED off. The LED-off
command is separate from the switch acknowledgment, so a disconnected or
unresponsive sensor cannot confirm the physical LED state. Enabling a switch
does not imply that a reader is connected or ready.

## Enrollment lease

Reader enrollment temporarily owns the Pico and pauses attendance processing.
An admin starts a server-created, owner-bound enrollment session only while the
reader service is ready. The backend switches to `IDLE`; reader traffic during
the lease is consumed only by the enrollment state machine and cannot become
attendance events.

Fingerprint enrollment records a provisional template candidate, verifies that
the template is not already mapped, waits for the explicit finish result and
keeps the new template associated with the lease until the user record is
saved. Cancel, skip and supported failure paths request cleanup before the
reader returns to normal use. On reconnection, pending drafts are cancelled;
uncommitted candidate templates are deleted when the sensor is available for
cleanup. If the device is disconnected or cleanup cannot be confirmed, the
backend reports an error and does not treat the template as enrolled in SQLite.
Physical hardware state still needs reconciliation after power loss during an
operation.

NFC enrollment is available only when the firmware reports NFC ready. The
current firmware build has an NFC stub, so NFC reports `ABSENT` and cannot read
or enroll cards.

Identity-only enrollment remains available without a reader session. The
browser may send a server-created `reader_session` when saving, but cannot set a
fingerprint template, NFC UID or credential list itself. The server obtains
credential values from the owned lease and commits the person and credentials
in the same database transaction. A credential-bearing browser payload is
rejected. Saving an identity without a `reader_session` does not create a
credential or a presence event.

The lease is bound to the authenticated admin session through a server-side
owner hash. Session reads and actions require the same owner. Polling an active
session extends its expiry; the connected reader loop schedules cleanup for an
expired lease. On service startup, pending leases are reconciled before normal
polling resumes.

## HTTP API

Admin endpoints require the `labauth_admin_session` cookie. Mutating admin
requests reject a supplied `Origin` that does not match the local request
origin. The public event feed is the only reader endpoint without admin
authentication. Responses from status/event reads are not cached.

| Method and path | Access | Request / result |
| --- | --- | --- |
| `GET /api/readers/events?since=<cursor>` | Public | Returns recent `CHECK` and `ERROR` events plus the current integer cursor. The service retains up to 100 events and only serves events younger than 20 seconds. `IN`/`OUT` continue to come from `/api/presence/events`. |
| `GET /api/readers/status` | Admin | Returns `connected`, `ready`, `configured`, `error`, `mode`, `fp_enabled`, `nfc_enabled`, `fp`, `nfc` and `enrollment`. |
| `POST /api/readers/control` | Admin | JSON is either `{"mode":"POLL"}`, `{"mode":"CHECK"}`, `{"mode":"IDLE"}`, or `{"reader":"fingerprint","enabled":true}` / the equivalent NFC switch. |
| `POST /api/readers/enrolments` | Admin | Starts a lease; JSON is `{}` or an optional active `user_id`. Returns the owner-bound session view. |
| `GET /api/readers/enrolments/{session_id}` | Session owner | Returns the current enrollment state and reader progress. |
| `POST /api/readers/enrolments/{session_id}` | Session owner | JSON is `{"action":"fingerprint"}`, `finish`, `nfc`, `skip_fingerprint`, `skip_nfc`, or `cancel`. |
| `POST /api/enrolment/complete` | Admin | Saves identity and access fields. Include the owned `reader_session` to commit credentials recorded during that lease; omit it for identity-only enrollment. |

Unauthenticated admin requests return `401`; a mismatched supplied origin on a
mutation returns `403`; unavailable readers, invalid operations and session
state conflicts return a `409` detail response. A session ID owned by another
admin returns `404` for both reads and actions.

## Tests and evidence

Run the database-backed service and HTTP API tests with isolated temporary
databases:

```sh
uv run python tests/test_reader_records.py
uv run python tests/test_pico_service.py
uv run python tests/test_reader_api.py
uv run python tests/test_reader_browser.py
```

`test_pico_service.py` connects the production service to a PTY firmware
emulator. It checks handshake, credential decisions, presence writes, mode
ownership, enrollment and cleanup. It is not physical hardware evidence.
`test_reader_api.py` starts an isolated application with an unavailable serial
port and checks authorization, origin handling, session ownership, identity-only
save and browser credential-forgery rejection.
`test_reader_browser.py` uses the repository's Chromium/CDP harness and a PTY
to exercise the actual admin controls, user cards, failure cards, cooldown and
exclusive enrollment lease across the application and SQLite.
It also completes the frontend enrollment journey and verifies that both
PTY-observed credentials survive Next, review and save. A delayed real status
response exercises reader actions during polling and stale-response rejection.

Bench evidence recorded on 2026-10-24: the live Pico completed the USB
handshake, mode commands and independent switch acknowledgments. Disabling the
fingerprint reader was followed by firmware `STATUS` reporting `led=OFF`. NFC
reported `ABSENT`. This confirms the USB command/control path and the reported
LED state; it does not establish a successful fingerprint match, NFC read,
credential enrollment or end-to-end attendance transaction.

Starting enrollment on that Pico also returned a free template ID. Cancelling
exposed a cached-readiness race before template deletion. The backend now waits
for a fresh ready/cleanup status, and the regression passes with the PTY
emulator. The Pico was disconnected before this correction could be retested
on hardware. No fingerprint capture or attendance write was observed during
the physical test.


### Polling status

Normal fingerprint polling reports `fp=READY`; raw driver activity is available
as `fp_state` in `/api/readers/status`. The compatibility mapping for older
firmware applies only to enabled, connected polling outside enrolment, learning
or cleanup. Updated firmware supplies both fields itself. Faults, startup and
non-polling busy states remain visible. Maintenance still uses the raw status
and command acknowledgements rather than this availability label.
