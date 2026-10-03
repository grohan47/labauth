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
| `backup_runs` | Outcome of every backup attempt (status, destination, size, error). |
| `current_presence` | Realtime cache of who is inside, used by the display. Rebuildable from `presence_log`. |

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
