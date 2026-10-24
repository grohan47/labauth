# LabAuth Pico firmware

One Raspberry Pi Pico acts as a USB-serial bridge for two credential readers:

- **Waveshare UART Fingerprint Sensor (F)** — active now.
- **PN532 NFC reader** — reserved on I2C0, implemented behind `ENABLE_PN532`.

The Pico is deliberately dumb. It reports **template IDs** and **NFC UIDs**. It
does not know whether an event is a check-in or check-out, and it does not store
names. The backend resolves the credential, applies cooldowns/duplicate rules,
and updates SQLite and the displays.

```
host (pyserial) <--USB CDC--> Pico
                                ├── UART1  GP20/GP21  Fingerprint F
                                └── I2C0   GP4/GP5  PN532 (future)
```

## Wiring

| Device | Pico pins | Notes |
|---|---|---|
| Fingerprint F RX | GP20 (UART1 TX / Serial2) | Pico transmits to sensor |
| Fingerprint F TX | GP21 (UART1 RX / Serial2) | Pico receives from sensor |
| Fingerprint F IRQ | GP19 (unused input) | May remain connected; never read by firmware |
| Fingerprint F VIN and VT | Same Pico 3.3 V rail | VIN powers the module; VT powers touch detection |
| Fingerprint F GND | Pico GND | Common ground |
| PN532 | I2C0: GP4 SDA, GP5 SCL | 5 V module; level-shift SDA/SCL; address `0x24` |
| Host | USB | `/dev/ttyACM*` |

The fingerprint sensor is 3.3 V. The common "PN532 V3 / HW-147" board is a
5 V-logic module: power it from 5 V and level-shift its I2C lines. Do **not**
run an I2C address scan on the PN532; it clock-stretches and expects a
status-byte read. A real PN532 reports chip ID `0x32`; a board at `0x28` is an
MFRC522-class device, not a PN532.

### Fingerprint presence over UART

All fingerprint modes use `CMD_FINGER_DETECT` (`0x0021`) to check placement and
removal over UART. The command returns `1` for present and `0` for absent. See the
[Sensor F command manual, page 16](https://files.waveshare.com/wiki/UART_Fingerprint_Sensor_F/UART_Fingerprint_Sensor_F_Command_Manual.pdf).
VIN and VT remain connected to the same 3.3 V rail; VT is the touch supply, not
a signal. See the
[Sensor F pin definitions](https://docs.waveshare.com/UART_Fingerprint_Sensor_F)
and [connection guide](https://docs.waveshare.com/UART_Fingerprint_Sensor_F/PC-Software).
Neither supply is driven by a GPIO.

IRQ may remain wired to GP19. The firmware leaves that pin as an input but
does not read it, attach an interrupt, or use it as a wake/placement/removal
hint. There is no optional IRQ control path.

While waiting for a finger or removal, the state machine schedules a presence
query every 100 ms after the previous response. Two consecutive successful
responses must confirm the expected state before advancing. An opposite
response resets the confirmation count; missing, invalid or failed responses
cannot count as removal or placement. Each new wait starts a fresh count.
Capture and template generation must still succeed before an enrollment
impression is accepted. A late response cannot revive an expired baseline prompt.
The later guided learning phase has no placement/removal time limit.

Polling is non-blocking and permits only one UART command in flight. USB and
future NFC continue to be serviced while the sensor responds or the interval
elapses. No presence queries run while the reader is disabled, idle, waiting
for a new `ENROLL` command, or in a cooldown. `FP HEALTH` uses a one-shot
presence query for diagnostics; its result does not advance an enrollment.

The LED is on while capture is armed, including waiting for UART presence in `POLL`,
`CHECK`, armed `VERIFY`, and each enrollment placement prompt. It stays on
during capture/processing, then turns off while waiting for removal and during
cooldowns. It turns back on when the next impression/read is armed.
Enrollment completion, cancellation and baseline timeouts leave it off until another
`ENROLL` or an attendance mode is armed. `IDLE`, maintenance and UART faults
also request OFF. A touch cannot bypass enrollment prompts, cooldowns, or the
requirement to remove a held finger.

LED control is itself a non-blocking UART command. If the sensor is unplugged
or unresponsive, the Pico cannot guarantee the physical LED goes off. It keeps
OFF as the requested state and sends it after recovering the UART link, before
re-arming. LED updates preserve the current operation and its original timers.

`MODE POLL` remains normal attendance mode. No power gating, CPU sleep or
sensor standby command is used here.

## Build

Open `labauth_pico.ino` in the Arduino IDE and select **Raspberry Pi Pico** with
the **Raspberry Pi Pico/RP2040/RP2350 by Earle F. Philhower, III** core (6.3.0
was used for the build check). No extra libraries are needed while
`ENABLE_PN532` is `0`.

For `ENABLE_PN532 1`, use the PN532 I2C driver once it is implemented. Keep the
I2C work non-blocking: one short transfer per `tick()`, never a blocking
"read the whole response" call.

## Modes

| Mode | Fingerprint | NFC | LED | Purpose |
|---|---|---|---|---|
| `IDLE` | off | off | off | Safe stop; commands still accepted |
| `POLL` | UART presence + 1:N scan | auto polling | on when armed | Normal check-in/out credential stream |
| `ENROLL` | one enrollment per `ENROLL` command | off | on for each placement/capture | Add a finger; backend maps the returned ID to a user |
| `CHECK` | UART presence + 1:N scan | off | on when armed | Display "registered / not registered"; backend shows the name |
| `VERIFY` | UART presence + 1:1 against `VERIFY <id>` | off | on when armed | High-confidence check for a known user |
| `MAINT` | diagnostics only | one-shot only | off | Incident response, listing, deletion, health |

The Pico never converts an event into `CHECK_IN`/`CHECK_OUT`. In `POLL`, a match
is a credential observation; in `CHECK`, the same match is a lookup. The backend
knows which mode it selected.

`READY`/`READY mode=...` means the Pico host link is up. `EVT FP READY` means the
fingerprint transport is up; `STATUS fp=...` is authoritative. A command sent
immediately after a mode change can receive `ERR FP BUSY` while the LED update
completes; retry it once.

The Pico does not store names. `CHECK` returns `FP MATCH id=N`; the backend maps
`template:N` to a user and displays the name. Raw fingerprint images and
template upload/download are deliberately not exposed.

### Cooldowns

The anti-spam policy is in `config.h`:

- Entering `POLL`, `CHECK` or `VERIFY` requires an empty sensor first. A finger
  left on the reader from `CHECK` cannot immediately become a sign-in.
- Wait for the finger/card to be **removed** before re-arming.
- Successful read: short cooldown (`300 ms`) so a queue of people can move.
- Unsuccessful read: longer cooldown (`1500 ms`) so a held/bad finger does not
  spam attempts.
- Baseline enrollment and one-shot finger placement wait: `20 s`. Continuous modes wait
  for UART-confirmed presence without a placement timeout.
- Baseline removal wait: `10 s`. Guided Auto Learn has no placement/removal
  timeout or capture cap; use `ENROLL FINISH` or `CANCEL` to stop it.
- A held finger never bypasses the start/removal gate just because time passes.
- Presence interval: `100 ms`, with two consecutive UART confirmations for both
  placement and removal.
- NFC card release: `500 ms` (when implemented).

The backend should still deduplicate per user and apply its own cooldown; the
Pico cannot know whether a template belongs to a valid user.

## Host protocol

Newline-delimited ASCII. Commands are case-insensitive. The same commands work
from `pyserial` and from the Arduino Serial Monitor.

```
OK <command> [detail]        accepted/completed
ERR <scope> <detail>         command or reader error
EVT <source> <event> ...     asynchronous event
STATUS ...                   mode and reader states
READY ...                    boot or host reconnect
```

### Commands

| Command | Action |
|---|---|
| `MODE IDLE\|POLL\|ENROLL\|CHECK\|VERIFY\|MAINT` | Switch mode |
| `ENROLL` | Start baseline enrollment followed by uncapped guided Auto Learn (only in `ENROLL`) |
| `ENROLL FINISH` | Finish guided learning after pending UART work; wait for `FP ENROLLED` |
| `VERIFY <id>` | Arm 1:1 checks against a template ID (only in `VERIFY`) |
| `CANCEL` | Abort the current operation |
| `STATUS` | Reader/mode states, requested `led`, attendance `polling`, enable switches, `enroll` ID, `learning` and `cleanup` |
| `PING` | Liveness check; replies `OK PONG` |
| `FP SCAN` | One-shot 1:N scan (MAINT/IDLE) |
| `FP ENABLE\|DISABLE` | Independent backend/UI fingerprint switch, available in any mode |
| `FP STATUS` | Fingerprint link state, enable switch and requested LED state |
| `FP COUNT` | Number of enrolled templates |
| `FP LIST` | Emit every occupied template slot |
| `FP HEALTH` | Ping, finger state, parameters, count, damaged-template check |
| `FP PARAMS` | Read sensor parameters 0–4 |
| `FP EXISTS <id>` | Is this template slot occupied? |
| `FP DELETE <id>` | Delete one template (MAINT/IDLE) |
| `FP PING` | Recover/verify the fingerprint link |
| `FP LED ON\|OFF` | LED test; `OFF` is rejected in active modes |
| `NFC STATUS` | NFC reader state |
| `NFC ENABLE\|DISABLE` | Independent backend/UI NFC switch, available in any mode |
| `NFC READ` | One-shot UID read (MAINT/IDLE) |
| `NFC ON\|OFF` | Diagnostic enable/disable (MAINT/IDLE) |
| `LED ON\|OFF` | Alias for `FP LED` |
| `REBOOT` | Reboot the Pico |
| `HELP` | Print the command list |

### Backend/UI reader switches

Use these commands for the planned frontend toggles:

```text
FP DISABLE
FP ENABLE
NFC DISABLE
NFC ENABLE
```

Each replies `OK <reader> <command>` followed by `STATUS`, which includes
`fp_enabled=ON|OFF` and `nfc_enabled=ON|OFF`. `READY` includes both settings on
USB reconnect, and `FP STATUS`/`NFC STATUS` report the individual `enabled`
setting. These are permission switches, separate from physical reader health:
enabling NFC still reports `nfc=ABSENT` until the PN532 driver/hardware exists.
Likewise, `polling=ON` means attendance mode was selected; both reader switches
can be OFF in that mode. The backend should read each switch explicitly.

- `FP DISABLE` cancels any scan, one-shot, verification or enrollment, stops
  automatic matching and requests LED OFF. Disabled fingerprint commands return
  `ERR FP DISABLED`; even `LED ON` cannot override the switch. Link recovery and
  LED-off delivery and rollback of a provisional template can still run.
  `STATUS` and host `PING` remain available.
- `NFC DISABLE` stops automatic and one-shot reads and cancels pending reader
  work. Disabled read/diagnostic commands return `ERR NFC DISABLED`.
- Switching one reader leaves the other reader's setting and the current mode
  unchanged. Enabling NFC during `ENROLL` does not start NFC reads or attendance.
- `FP ENABLE` restores the behavior allowed by the current mode. Attendance,
  check and verify modes require finger removal before accepting another touch.
  `ENROLL` waits for a new `ENROLL` command; an aborted enrollment never restarts
  automatically. Repeating an unchanged switch command is harmless.
- Switches survive mode changes and USB reconnection. They are temporary RAM
  settings and default to ON after reboot; boot mode is still `IDLE`. A backend
  that retains toggle preferences should reapply them after a reboot.

These are software disables, not power switches: VIN and VT remain on the shared
3.3 V rail. `OK FP DISABLE` acknowledges the software gate; actual LED OFF is a
separate UART operation and may wait for link recovery. An enrollment disabled
after STORE is rolled back before another enrollment/mode can start. A power
loss or Pico reboot during provisional enrollment still needs reconciliation
with `FP LIST`; the rollback record is held in RAM.

Before sending DISABLE, the backend should stop processing that reader's
attendance events and ignore older events already buffered on the USB link.
After the acknowledgement, synchronize the frontend from the returned switch
fields. Backend/frontend wiring for these controls is not implemented here.
Keep `NFC ON|OFF` for maintenance diagnostics; those commands cannot override
`NFC DISABLE` and remain restricted to `MAINT`/`IDLE`.

### Events

```
EVT FP MATCH id=41
EVT FP NOMATCH
EVT FP VERIFY id=41 result=MATCH
EVT FP PROGRESS phase=FREE_ID id=41
EVT FP PROGRESS phase=PLACE step=1/3
EVT FP PROGRESS phase=REMOVE step=1/3
EVT FP PROGRESS phase=RETRY stage=BASE reason=BAD_QUALITY retry=1 hint=CENTER_OVERLAP
EVT FP PROGRESS phase=LEARN_READY id=41 finish=ENROLL_FINISH
EVT FP PROGRESS phase=PLACE stage=LEARN id=41 hint=SLIGHT_LEFT
EVT FP LEARN id=41 result=MATCH update=1 captures=4 matches=3
EVT FP LEARN id=41 result=NOMATCH captures=5 hint=MOVE_TOWARD_CENTER
EVT FP ENROLLED id=41 captures=8 matches=4 updates=3
EVT FP ENROLL_CLEANED id=41
EVT FP DUPLICATE id=17
EVT FP COUNT count=42
EVT FP SLOT id=17
EVT FP EXISTS id=17 registered=1
EVT FP PARAM type=1 value=3
EVT FP HEALTH broken=0 first=0 tx=120 timeouts=0 badframes=0
EVT FP PRESENT present=1
EVT FP DELETED id=17
EVT FP READY
EVT FP FAULT
EVT FP CANCELLED
EVT FP ENROLL_ABORTED
EVT FP LIST_END
EVT NFC UID uid=04A10B2C3D4E5F
EVT NFC ABSENT
```

Errors carry the sensor result code when there is one:

```
ERR FP 0x19 BAD_QUALITY
ERR FP 0x18 ...              duplicate fingerprint (store)
ERR FP 0x12 NO_TEMPLATE
ERR FP TIMEOUT
ERR FP BADFRAME
ERR FP BUSY
ERR MODE diagnostics-only
```

### Backend responsibilities

- Map `FP MATCH id=N` to a user via the `credentials` table (`template:N`).
- Handle `FP NOMATCH` as an unknown/failed fingerprint, not a hardware error.
- Map `NFC UID` to a user; normalize to uppercase hex.
- Reject duplicate enrollments (`FP DUPLICATE id=...`); do not silently reassign.
- Delete the sensor template and the DB association together; otherwise a slot
  can point at the wrong person.
- Replacing the fingerprint sensor invalidates every stored template ID; all
  fingerprint credentials must be re-enrolled.
- Apply the sign-in/out toggle and deduplication/cooldown.

## Enrollment flow

1. Backend enters `MODE ENROLL` and sends `ENROLL`.
2. Pico reads Auto Learn (parameter 4), enables it if off, and verifies readback
   before proceeding. Failure stops enrollment instead of pretending learning works.
3. Pico finds a free ID and collects three overlapping **central** impressions,
   with UART-confirmed removal between each. Bad-quality samples retry the same
   buffer. A merge rejection restarts the baseline with `hint=CENTER_OVERLAP`.
4. The merged baseline is stored provisionally. `phase=LEARN_READY id=N` starts
   guided learning; this is **not** `FP ENROLLED` and must not create an association.
5. The user repeatedly lifts and replaces the same finger with small changes.
   Each new capture is generated into RAM buffer 0 and verified **1:1 against N**.
   Successful verifications allow the sensor's Auto Learn algorithm to update
   that one template. No extra template slots are allocated.
6. `FP LEARN` reports matches, mismatches and the raw sensor update flag.
   There is no capture cap, and learning waits indefinitely for placement/removal.
7. Backend/Serial Monitor sends `ENROLL FINISH`. The Pico drains any pending
   UART operation, stops taking new captures, and emits `FP ENROLLED id=N ...`.
   Only then should the backend associate `template:N` with the user.
8. Backend explicitly sends `MODE POLL` to resume attendance.

The module can merge only two or three templates at a time. Auto Learn is
enabled through parameter 4 and applied by SEARCH/VERIFY; see the
[Sensor F command manual, pages 13 and 29–31](https://files.waveshare.com/wiki/UART_Fingerprint_Sensor_F/UART_Fingerprint_Sensor_F_Command_Manual.pdf).
Enabling Auto Learn is a **module-wide setting** and remains ON afterward, so
normal successful scans/verifications can also update stored templates. No
security level or duplicate-check setting is lowered or changed.

Sensor F exposes no coverage percentage, "complete finger" flag, or direction
feedback. `update=0` means no update was reported for that match, not that coverage
is complete. The firmware cycles generic hints (`CENTER`, `SLIGHT_LEFT`,
`SLIGHT_RIGHT`, `TIP_WITH_OVERLAP`, `BASE_WITH_OVERLAP`, `ROTATE_SLIGHTLY`). They
are UI suggestions, not measurements. On a mismatch or poor image it suggests
`MOVE_TOWARD_CENTER`; use small movements with overlap. A non-matching region
cannot train the template. This improves the opportunity for learning but does
not guarantee every placement will match.

`ENROLL FINISH` may be sent immediately after `LEARN_READY` to keep the baseline,
or after any number of guided captures. `OK ENROLL FINISH` acknowledges the
request; `FP ENROLLED` is the final completion event. Sending FINISH before the
learning phase returns `ERR FP NOT_LEARNING`. Capture/match counters describe
the learning phase; final `captures` includes the three baseline impressions.

Entering `MODE ENROLL` stops automatic fingerprint scans, disables NFC polling
and cancels pending reader operations before acknowledging the mode change.
`STATUS ... polling=OFF` confirms that the normal check-in/out stream is paused.
While an enrollment is queued, running, learning or awaiting cleanup, switching to another mode returns
`ERR MODE enrollment-active`; repeating `MODE ENROLL` leaves it running.
`NFC ON`, `NFC READ` and `FP SCAN` are also rejected in this mode.

Success, failure, baseline timeout and `CANCEL` all leave the Pico in `ENROLL`, with
polling off. The backend must explicitly send `MODE POLL` after saving the
template association or handling cancellation/failure. Re-entering `POLL`
requires finger removal before scanning, so the enrollment finger cannot
immediately toggle attendance.

When the frontend is connected to the Pico through the backend, the backend
must pause attendance processing for **both** credential sources before sending
`MODE ENROLL`, ignore any previously queued match/UID events, wait for
`OK MODE ENROLL`, then send `ENROLL`. Resume attendance only after receiving
`OK MODE POLL`. Treat `FP ENROLLED` as an enrollment result, never an attendance
event. This frontend/backend connection is not implemented yet.

A duplicate finger returns `FP DUPLICATE id=<existing>`. The sensor's duplicate
check parameter (type 2) should be ON; read it with `FP PARAMS` and enable it
with the Waveshare tool if needed. Without it, the sensor can store the same
finger under two IDs.

To discard an active enrollment, send `CANCEL` (or `FP DISABLE`). It emits
`FP ENROLL_ABORTED` and acknowledges the command. If a provisional STORE was
sent, the driver deletes that newly reserved ID and emits `FP ENROLL_CLEANED id=N`.
It also does this after a communication fault, once the UART link recovers.
A missing STORE acknowledgement is treated as "possibly stored" and rolled back.
Duplicate rejection never deletes the pre-existing duplicate ID.

While `STATUS cleanup=ON`, new enrollments and mode changes remain blocked.
Failed cleanup retries with `ERR FP ENROLL_CLEANUP id=N code=...`; wait for
`FP ENROLL_CLEANED` before starting another operation. Link resynchronization,
LED OFF and cleanup still run while fingerprint scanning is disabled. After a
Pico reboot/power interruption, RAM cleanup state is lost: reconcile template
IDs against the backend before accepting orphaned slots.

### Enrollment regression check (no hardware)

From the repository root:

```sh
g++ -std=c++17 -Wall -Wextra -Werror -Itests/firmware \
  tests/firmware/test_enrolment.cpp firmware/labauth_pico/fingerprint.cpp \
  firmware/labauth_pico/nfc.cpp firmware/labauth_pico/protocol.cpp \
  -o /tmp/labauth-test-enrolment
/tmp/labauth-test-enrolment
```

This runs the production sketch, command parser and reader state machines
against a simulated Sensor F. It covers exclusive enrollment, cancellation
during LED setup, timeout/failure, three-impression success, UART presence
confirmation, held-finger gates, match/verify, cooldowns, timer wraparound and
explicit attendance resume. It checks the polling interval, opposite/noisy IRQ
levels, inconsistent UART presence, malformed/failed/missing/late responses,
and USB command handling while waiting for UART. LED checks cover placement
waits, removal, cooldowns, timeouts, cancellation, disabled modes and link recovery.
Reader-switch checks cover independent controls, persistence across mode changes,
idempotent commands, enrollment cancellation, held-finger re-enabling, absent NFC,
and suppression of fingerprint replies received after disable.
Guided-learning checks cover more than ten captures, no-update/mismatch replies,
manual finish during UART activity, Auto Learn readback, baseline retries,
duplicate rejection, and rollback/retry after cancel, disable or a lost STORE reply.
It does not prove physical sensor behavior
or frontend/backend integration; NFC remains a stub.

## PN532 drop-in

The seam is already present:

- `nfc.h` / `nfc.cpp` expose the same `begin/tick/setEnabled/busy/state` shape as
  the fingerprint reader.
- `ENABLE_PN532` selects the stub or the future implementation.
- I2C0 GP4/GP5 and address `0x24` are reserved in `config.h`.
- `NFC READ` gives the backend a one-shot path for card enrollment.
- `NFC` is disabled automatically in `ENROLL`, `CHECK`, `VERIFY` and `MAINT`.
- In `POLL`, both readers are serviced on every `loop()` pass. The fingerprint
  driver never blocks, so the PN532 and host link keep running.

When implementing, keep the I2C state machine non-blocking and emit the same
event shape (`EVT NFC UID uid=...`). Do not add sign-in/out logic here.

## Security

For bench testing `AUTH_MODE` is `0`. Both the backend and a Serial Monitor can
send commands. Once the hardware is trusted, add authentication in two stages.

### Stage 1: shared-key HMAC (recommended first)

- Give the Pico and backend a random 32-byte key.
- Use a canonical envelope with a monotonic sequence number and a boot nonce:
  `v1 <seq> <body>`.
- Append `#<HMAC-SHA256(v1 <seq> <body>)>` to each command/event.
- The Pico verifies commands before dispatch; the backend verifies events before
  acting on them. Reject reused/old sequence numbers.
- Arduino-Pico includes BearSSL, so HMAC-SHA256 is practical.
- A shared key prevents forgery but not eavesdropping. It is much simpler than
  public-key crypto and is sufficient for a local USB cable.

### Stage 2: public/private keys

- Backend holds an Ed25519 private key; the Pico stores the public key and
  verifies signed commands.
- Pico holds its own Ed25519 private key; the backend stores the Pico's public
  key and verifies signed events.
- Add a challenge-response at connect (backend nonce, Pico signature) to stop
  replay of old commands/events.
- For confidentiality, add an X25519 ephemeral exchange and ChaCha20-Poly1305 or
  AES-256-GCM session encryption. The data here is template IDs and UIDs, not
  raw biometrics, so authenticity matters more than secrecy.
- Ed25519 verification is fast enough on the RP2040; signing is slower but
  events are low-rate.

### Key storage and limits

A key compiled into flash can be extracted by someone with physical access and
a debugger. For stronger protection use RP2040 OTP or an external secure element
(ATECC608A/SE050), enable flash readout protection where available, and treat
physical access as a separate threat. Authentication does not stop someone who
can reflash the Pico.

With authentication enabled, typed Serial Monitor commands no longer work
unless they are signed. Keep a separate unsigned bench build, or gate service
mode behind a physical jumper/BOOTSEL action.

## Testing checklist

1. `PING`, `STATUS`, `HELP` over USB; confirm `READY` after reconnect.
2. `MODE CHECK`; place an enrolled finger → `FP MATCH`; unknown finger →
   `FP NOMATCH`; remove and replace quickly to verify the short cooldown.
3. `MODE ENROLL`; `ENROLL`; three overlapping central impressions →
   `phase=LEARN_READY id=N`; vary placement gradually and observe `FP LEARN`.
   Send `ENROLL FINISH`, wait for `FP ENROLLED id=N`, then use `MODE MAINT`
   to verify with `FP EXISTS N` and `FP LIST`.
4. Try the same finger again → `FP DUPLICATE id=N`.
5. `MODE POLL`; tap a card (once PN532 is fitted) and a finger; confirm both
   event streams continue while the other reader is active.
6. Unplug/replug the fingerprint sensor; confirm `FP FAULT` then `FP READY`
   without resetting the Pico.
7. `MODE MAINT`; `FP HEALTH`, `FP PARAMS`, `FP DELETE N`, `FP LIST`.
8. Cancel during guided learning; wait for `FP ENROLL_CLEANED` and confirm that
   ID is empty in maintenance mode. Cancel during `FP LIST` and confirm `FP CANCELLED`.

Only one process can own `/dev/ttyACM0` at a time. Close the backend before using
the Serial Monitor, or use the backend's command console.


### Polling availability

In `POLL`, normal fingerprint waiting/capture reports `fp=READY` in `STATUS`
and `FP state=READY` in `FP STATUS`. `STATUS fp_state` retains the raw driver
state (often `BUSY`). Startup, faults, disabled readers, enrolment/cleanup and
command-admission checks retain their actual states. The backend also maps
ordinary polling `BUSY` from older firmware to `READY` for the admin UI.
