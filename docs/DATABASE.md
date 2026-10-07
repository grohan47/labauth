# LabAuth Database

SQLite is the local, authoritative datastore. The schema, repository functions
and connection handling live in [`src/database.py`](../src/database.py); domain
value objects live in [`src/models.py`](../src/models.py).

The database file defaults to `data/labauth.db` (git-ignored) and can be
overridden with the `LABAUTH_DB_PATH` environment variable. The database runs in
WAL mode and connections are opened per operation.

## Schema

```mermaid
erDiagram
    USERS ||--o{ USER_ACCESS_AREAS : "has access to"
    ACCESS_AREAS ||--o{ USER_ACCESS_AREAS : "granted"
    USERS ||--o{ BANS            : "subject to"
    USERS ||--o{ PRESENCE_LOG    : "generates"
    USERS ||--o{ CREDENTIALS     : "authenticates with"
    CREDENTIALS ||--o{ CREDENTIAL_ATTEMPTS : "produces"
    USERS ||--o| CURRENT_PRESENCE : "cached as inside"

    USERS {
        bigint id PK
        text plaksha_id UK
        text name
        text photo
        text email
        text phone
        boolean is_temp
        text status
        timestamp created_at
        timestamp updated_at
    }
    ACCESS_AREAS {
        bigint id PK
        text code UK
        text label
        int sort_order
    }
    USER_ACCESS_AREAS {
        bigint user_id PK,FK
        bigint area_id PK,FK
        timestamp granted_at
        text granted_by
    }
    BANS {
        bigint id PK
        bigint user_id FK
        text reason
        timestamp banned_at
        timestamp unbanned_at
        text banned_by
    }
    PRESENCE_LOG {
        bigint id PK
        bigint user_id FK
        text event_type
        text entry_method
        bigint credential_id FK
        timestamp occurred_at
        text device_id
        text metadata
    }
    CREDENTIALS {
        bigint id PK
        bigint user_id FK
        text credential_type
        text identifier UK
        blob template
        boolean is_active
        timestamp enrolled_at
    }
    CREDENTIAL_ATTEMPTS {
        bigint id PK
        timestamp occurred_at
        text credential_type
        text identifier
        bigint user_id FK
        text outcome
        text message
        text device_id
    }
    ADMIN_AUDIT_LOG {
        bigint id PK
        timestamp occurred_at
        text actor
        text action
        text entity_type
        text entity_id
        text before
        text after
    }
    BACKUP_RUNS {
        bigint id PK
        timestamp started_at
        timestamp finished_at
        text status
        text destination
        bigint size_bytes
        text error
    }
    ALERTS {
        bigint id PK
        text message
        text severity
        text expires_at
        timestamp created_at
        timestamp updated_at
    }
    CURRENT_PRESENCE {
        bigint user_id PK,FK
        timestamp checked_in_at
        timestamp updated_at
    }
```

### Tables

| Table | Purpose |
| --- | --- |
| `users` | Everyone known to the system (students, staff, temporary users). `is_temp` marks self-registered temporary users. |
| `access_areas` | The pre-defined, admin-managed access areas (seeded with `indoor_lab`, `tool_area`). |
| `user_access_areas` | Many-to-many grant of access areas to a user. |
| `bans` | Ban timelines. An open ban is a row with `unbanned_at IS NULL`; only one open ban per user is allowed. |
| `credentials` | NFC UIDs and fingerprint templates, mapped to a user. `UNIQUE (credential_type, identifier)` rejects duplicates. |
| `presence_log` | The immutable in/out log; the authoritative record of real check-in/check-out events. |
| `credential_attempts` | Every authentication attempt, successful or not, with the raw reader message preserved in `message`. |
| `admin_audit_log` | Consequential admin actions (user added/deleted, display settings changed, bans, etc.) with optional before/after snapshots. |
| `settings` | Persisted display configuration, e.g. per-screen visibility flags. |
| `alerts` | Operator announcements shown on both displays. `severity` is `critical`, `caution` or `info`; `expires_at` is an optional lifetime, `NULL` meaning it stays until deleted. |
| `backup_runs` | Outcome of every backup attempt (status, destination, size, error). |
| `current_presence` | Realtime cache of who is inside, used by the display. Rebuildable from `presence_log`. |

### No automatic seeding

A new database is created **empty**: no demo users and an empty lab. Users only
ever enter the database through a real check-in, the explicit developer
`populate()` tooling, or enrollment. The pre-defined `access_areas` rows are
seeded because they are configuration rather than demo data.

This means the database persists across restarts — what you see is what is
actually stored. To start over, delete the database file:

```bash
rm -f data/labauth.db data/labauth.db-wal data/labauth.db-shm
```

### Design notes

* **Normalised.** Access areas are a lookup table plus a junction, never a CSV
  column. Bans are temporal rows, so "banned" is derived (an open ban exists)
  rather than stored twice.
* **`id` is the DB-generated unique ID.** `plaksha_id` is an optional external
  university ID, unique only when present (partial unique index).
* **Access area policy.** The canonical areas are seeded and the frontend is
  expected to offer them as checkboxes. `ensure_access_area(..., allow_create=False)`
  enforces the pre-defined set; the develop/test API still allows new areas so
  the display tooling keeps working.
* **Immutable log.** `presence_log` only ever gains rows during normal
  operation. `reset()`/`populate()` (developer tooling) update `current_presence`
  directly so they neither pollute the log nor raise operator alerts.
* **Photos are file paths only.** Photos are intentionally excluded from
  backups; a missing photo falls back to the default placeholder.

## Backups

`src/services/backup.py` (CLI: `scripts/backup.py`) takes a consistent snapshot
with SQLite's backup API and mirrors **every table** to a self-hosted PostgreSQL
instance. The target URL is currently a placeholder
(`postgresql://labauth:labauth@backup.example.invalid:5432/labauth`, RFC 2606).

```bash
# Snapshot only (no network, no psycopg required)
uv run python scripts/backup.py --local-only

# Full backup to the configured PostgreSQL target
uv run python scripts/backup.py --database-url postgresql://user:pass@host:5432/labauth

# Remove the local snapshot once the backup succeeds
uv run python scripts/backup.py --delete-snapshot
```

Configuration:

| Variable | Meaning |
| --- | --- |
| `LABAUTH_DB_PATH` | SQLite database path (default `data/labauth.db`). |
| `LABAUTH_BACKUP_DATABASE_URL` | PostgreSQL target (default: the placeholder above). |

The PostgreSQL client is an optional dependency:

```bash
uv sync --extra backup
```

Every attempt — success or failure — is recorded in `backup_runs` with its
destination, size and error.

## Tests

```bash
uv run python tests/test_database.py
```

The suite runs against a throwaway temporary database and covers schema
creation, seeding, users/access, bans, credentials and attempts, the audit log,
the presence feed, and the local backup path.

## Enrolment

The `/enrollment` page requires an admin session. Identity, photo and access
selection form one vertical editable student card with a centred portrait.
Only the name is required. The access
choices come from `access_areas`, start unchecked, and submit stable row IDs.
The original canonical areas remain Indoor lab and Tool area; enrolment does
not add example equipment to the configuration.

Linked Git worktrees use the primary checkout's `data/labauth.db` by default,
so enrolment, administration and the main display share the same configured
areas and people. Portraits are also served from and saved to the primary
checkout. Existing worktree-local database files are preserved but are no
longer selected by default. `LABAUTH_DB_PATH` still takes precedence for
explicit deployments and disposable tests.

`POST /api/enrolment/complete` validates the draft and calls `create_enrolment()`.
User, grants and audit entry commit in a single SQLite transaction. Duplicate
Plaksha IDs and unknown/stale areas reject the entire save. The confirmation
card uses the saved database record. Enrolment does not check a person in.

Email and phone are nullable record fields, excluded from public presence
cards. Existing database files receive these columns without losing records.
Uploaded and captured photos are centre-cropped in the browser, decoded and
normalised as PNG on the server, and stored as photo paths. Failed saves remove
their new photo file. Pillow provides image validation.

Both fingerprint and NFC readers currently show **Reader unavailable** and can
be skipped. Skip remains available regardless of connection or enrolment state,
including once real readers are integrated. No fingerprint success, NFC identifier
or credential is simulated.
The API rejects browser-supplied credential claims. Driver integration and
fingerprint consistency verification are deferred until real readers are added.

The theme follows the same server clock as the main display: light from 06:00
until 18:00, dark otherwise. It refreshes in place without clearing the draft.
The page has no header or step list. A thin red Lyne divider shows progress
across the top; white-on-red Lyne buttons stay at the bottom for navigation.
The NFC step uses Polina Mamontova's physical card-and-terminal animation in
SBB red, with theme-aware fills and a still frame for reduced motion. It has
no phone or expanding circles. Navigation buttons have no shadow. Source and license are
recorded in `src/static/animations/README.md`.

Lyne 5.8.0 and design tokens 2.1.3 load from pinned CDN modules, including the
checkbox, menu and select modules. The photo preview uses the documented native image
composition with Lyne image utility classes, avoiding the image component's
CDN image URL rewriting for local photos. See the official
[Image](https://digital.sbb.ch/en/design-system/lyne/components/image/),
[Menu](https://digital.sbb.ch/en/design-system/lyne/components/menu/) and
[Dialog](https://digital.sbb.ch/en/design-system/lyne/components/dialog/) patterns.

## Alerts

Operator announcements are rows in the standalone `alerts` table. Each has a
`message`, a `severity` (`critical` > `caution` > `info`) and an optional
`expires_at` lifetime. The `/admin` Alerts pane creates, edits, deletes and sets
the expiry of alerts; expired rows are filtered out of `list_alerts()` and
physically purged on the next write.

The API is `/api/alerts` (`GET` public, `POST` create) plus
`/api/alerts/{id}` (`PUT`, `DELETE`), all mutations requiring an admin session
and each one recorded in `admin_audit_log`. Both display channels render the
same single-line ticker at the top of the screen: active alerts are ordered by
severity, cross-fade between one another, and reveal a message that does not fit
on one line a line at a time with a short scroll between lines. The ticker is an
overlay and has no visibility toggle, so it never reflows the presence layout.
