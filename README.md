# LabAuth

Local NiceGUI application for the LabAuth display and enrollment workflows.

## Run

```bash
uv sync
uv run python src/main.py
```

Open <http://127.0.0.1:8080/display> in Chromium.

The display loads version-pinned `@sbb-esta/lyne-elements` and
`@sbb-esta/lyne-design-tokens` npm packages at runtime through jsDelivr. No Lyne
packages or transitive frontend dependencies are stored in this repository. An
internet connection is required when loading the UI.

## Data and backups

Presence, users, credentials and logs are stored in a local SQLite database
(`data/labauth.db`, override with `LABAUTH_DB_PATH`). See
[docs/DATABASE.md](docs/DATABASE.md) for the schema and design notes.

```bash
# Database tests (uses a throwaway database)
uv run python tests/test_database.py

# Snapshot the database without contacting the remote target
uv run python scripts/backup.py --local-only
```

Full backups mirror every table to a self-hosted PostgreSQL instance. The target
URL is a placeholder for now; install the optional client with
`uv sync --extra backup` and configure `LABAUTH_BACKUP_DATABASE_URL`.
