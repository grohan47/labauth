ALWAYS ASSUME THAT WHEN THE USER TALKS UI, THEY WANT IT IMPLEMENTED USING LYNE COMPONENTS ONLY. If a requested feature cannot be implemented with Lyne, and extensive search of Lyne documentation and Storybook fails to find a solution, then the feature should be flagged for user review. Only if the user explicitly approves a non-Lyne solution should it be implemented.

# LabAuth — App and Tech Stack Summary

## Purpose

LabAuth is an all-in-one login/logout and presence-tracking system for a robotics lab.

The system runs on a Lubuntu laptop or Raspberry Pi and connects to:

* an NFC reader through a Raspberry Pi Pico
* a fingerprint reader through USB or serial
* a webcam for enrollment photos
* two displays:

  * external monitor: permanent lab-status display
  * laptop screen: admin interface, reverting to status display when idle

The primary goal is to maintain an accurate, continuously updated record of everyone currently inside the lab.

---

## Core behavior

A user may identify themselves using either:

* fingerprint
* enrolled NFC card

Both credentials map to the same user account.

During normal operation, the application continuously listens for both fingerprint and NFC events.

When a valid credential is detected:

* if the user is currently outside, create a CHECK_IN event
* if the user is currently inside, create a CHECK_OUT event
* immediately update both connected displays

A short cooldown must prevent accidental repeated check-in/check-out events from a held card or fingerprint.

Unknown or failed credentials should produce concise feedback such as:

* Fingerprint not recognised
* Card not enrolled
* Try again
* Contact an administrator

Hardware failures should be distinguished from invalid credentials.

---

## Two-screen behavior

### External monitor

Always runs the public `/display` view.

It should show:

* authoritative analog clock
* digital time
* date
* current occupancy count
* cards for everyone currently inside
* each person's photo
* their authorised equipment/access
* brief transient check-in/check-out/error feedback

No admin controls should ever appear here.

### Laptop

Normally provides the admin interface.

When idle, it should automatically return to the same lab-status display.

Admin interaction should restore the admin interface.

---

## Admin functionality

The admin interface should provide access to:

* Enroll user
* Users
* History
* Settings

It should also show concise operational state such as:

* number currently inside
* NFC reader status
* fingerprint reader status
* backup status

Avoid generic dashboard clutter.

---

## Enrollment workflow

Enrollment temporarily pauses normal credential identification so the readers can be used exclusively by the enrollment process.

Enrollment should be sequential:

1. Identity
2. Photograph
3. Access permissions
4. Fingerprint
5. Optional NFC
6. Review

Enrollment captures:

* name / identifier
* webcam photograph
* allowed tools/equipment
* fingerprint template/reference
* optional NFC credential

Do not silently overwrite duplicate credentials. (Duplicates should be explicitly rejected)

---

## Database and logging

SQLite is the local authoritative datastore.

Maintain extensive immutable logs.

Important data includes:

### Users

* identity
* photo path
* active/deactivated state

### Credentials

* user ID
* credential type
* fingerprint template/index or NFC UID

### Tool permissions

* tools/equipment
* user-to-tool mappings

### Presence events

Every entry/exit must be logged permanently.

Example fields:

* event ID
* user ID
* CHECK_IN / CHECK_OUT
* timestamp UTC
* credential type
* credential ID
* reader/device ID
* optional metadata

Presence history is append-only during normal operation.

### Credential attempts

Log successful and failed attempts including:

* fingerprint/NFC
* success
* unknown credential
* read failure
* low-confidence match
* cooldown rejection
* reader error

Do not store raw biometric data in general logs.

### Admin audit log

Log consequential admin actions such as:

* permission changes
* credential replacement
* user deactivation
* settings changes

### Current presence

Maintain an efficient current-presence table/cache for realtime display.

The immutable presence event log remains the source of truth and should allow reconstruction.

---

## Historical queries

The GUI must support historical presence queries such as:

* who is inside now
* who was present at a specific timestamp
* who was present during a time interval
* attendance history for one person
* total time spent in the lab
* failed authentication attempts

Provide common queries through normal GUI controls.

Also provide an advanced SQL console.

The SQL console should use a read-only SQLite connection with:

`PRAGMA query_only = ON`

Normal GUI users should not be able to execute destructive SQL.

---

## Backup behavior

The app must work fully offline.

The network is required only for backups.

A Python BackupService periodically:

1. creates a consistent SQLite snapshot using SQLite's backup API
2. optionally compresses it
3. uploads it to a configured remote destination
4. records success/failure in the local database

<Database backups will be configured at a later stage>

Admin settings should include:

* backup enabled
* destination URL/host
* credentials/key configuration
* interval
* retention
* last backup
* next backup
* Test connection
* Backup now

Do not simply `cp` the live SQLite database during writes.

---

## Timekeeping

The machine clock is the central time authority.

That's it. Just grab the time from the host and move on. The host will maintain time via its own faculties.

---

# Tech Stack

Keep the stack intentionally small.

## Language

Python

## Python environment/dependency management

`uv`

## UI / application framework

NiceGUI

NiceGUI handles:

* local web server
* application routing
* Python-side UI state
* realtime updates to connected clients

## Visual design system

SBB Lyne

Use actual:

* `@sbb-esta/lyne-elements`
* `@sbb-esta/lyne-design-tokens`

Load version-pinned Lyne npm packages through a public CDN. Do not vendor Lyne
components or their transitive frontend dependencies in this repository.

NiceGUI is not the visual design system.

Avoid leaking Quasar styling into the final UI where Lyne provides an equivalent component.

Create a small Python-to-Lyne bridge if necessary.

## Browser

Chromium installed separately.

Typical views:

* external monitor → `/display`
* laptop → `/admin`
* laptop idle → `/display`

## Database

SQLite via Python's standard `sqlite3` or a very thin abstraction.

Do not introduce PostgreSQL for the local application.

## Hardware communication

* `pyserial` for Pico/serial devices
* fingerprint device SDK/library as required
* webcam through an appropriate Python/OpenCV/browser capture path

Hardware logic must remain separate from UI logic.

## Service management

systemd

Responsibilities:

* launch LabAuth on boot
* restart it if it crashes

## Packaging

PyInstaller later, if a single deployable executable is desired.

Chromium remains an external system dependency.

---

# Architecture

```text
NFC Pico ─────────────┐
                      │
Fingerprint reader ───┼──> CredentialManager
                      │          │
                      │          ▼
                      │    PresenceManager
                      │          │
                      │          ├── SQLite
                      │          └── UI events
                      │
Camera ────────────────┘

                           NiceGUI
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
         External monitor               Laptop
           /display                  /admin or /display

SQLite
├── users
├── credentials
├── tool access
├── presence events
├── current presence
├── failed attempts
├── admin audit log
├── settings
└── backup log

BackupService
    │
    └── periodic SQLite snapshot
             │
             └── SFTP / WebDAV / HTTPS remote backup
```

---

# Internal architecture

Prefer small modules such as:

```text
labauth/
├── main.py
├── config.py
├── database.py
├── models.py
├── presence.py
├── credentials.py
├── time_service.py
├── hardware/
│   ├── nfc.py
│   ├── fingerprint.py
│   └── camera.py
├── services/
│   ├── enrollment.py
│   ├── backup.py
│   └── query_service.py
└── ui/
    ├── lyne.py
    ├── display.py
    ├── admin.py
    ├── enroll.py
    ├── users.py
    ├── history.py
    └── settings.py
```

Do not overengineer this into microservices.

---

# Hardware abstraction

NFC and fingerprint readers should emit the same high-level event shape.

Example:

```python
CredentialEvent(
    source='nfc',
    identifier='04A7...'
)
```

or:

```python
CredentialEvent(
    source='fingerprint',
    identifier='template:41'
)
```

Application flow:

```text
reader
→ CredentialEvent
→ resolve user
→ PresenceManager
→ CHECK_IN / CHECK_OUT
→ SQLite transaction
→ realtime UI update
```

The PresenceManager should not contain device-specific code.

Provide fake/mock readers for development so most UI and backend work can be done without physical hardware attached.

---

# System modes

Use a simple application mode/state system:

* NORMAL
* ENROLLMENT
* MAINTENANCE if needed

NORMAL:

* NFC and fingerprint continuously listen for identification

ENROLLMENT:

* normal identification is paused
* enrollment workflow temporarily owns the readers

Do not repeatedly destroy and recreate hardware workers.

---

# Design requirements

The entire UI must follow SBB Lyne.

Use:

* actual Lyne components
* actual Lyne tokens
* Lyne Storybook/component guidance
* SBB Reduced/minimalism principles

Strongly prefer implied function.

Do not add:

* marketing copy
* mission statements
* welcome text
* explanatory subtitles
* helper text for obvious controls
* decorative dashboard cards
* gradients
* unnecessary icons
* filler content

If a heading, button, state, or layout already communicates a function, do not explain it again.

Whitespace is intentional.

One primary action per task.

Secondary information should be progressively disclosed.

The permanent display should remain especially calm and sparse.

---

# Explicit non-goals

Do not add unless clearly justified later:

* Docker
* Redis
* Celery
* PostgreSQL for the local node
* React
* Node runtime in production
* microservices
* Kubernetes
* cloud dependency for authentication
* separate frontend/backend repositories
* complicated message brokers

The intended system is:

**one Python application + one SQLite database + two Chromium views + local hardware + periodic remote backups.**
