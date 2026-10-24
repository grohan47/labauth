# LabAuth

Local NiceGUI application for the LabAuth display and enrollment workflows.

## Run

```bash
uv sync
uv run python src/main.py
```

Open <http://127.0.0.1:8080/display> in Chromium.

The display loads version-pinned `@sbb-esta/lyne-elements` and
`@sbb-esta/lyne-design-tokens` through jsDelivr unless a current local bundle
exists. CDN loading requires internet access on an uncached browser. Browser
caching alone does not guarantee offline startup.

For offline UI assets:

```bash
npm install
npm run build:assets
```

The generated `src/static/vendor/` bundle includes a manifest of component and
package versions. The app checks it before selecting local assets; stale or
incomplete bundles fall back to the pinned CDN imports. Rebuild after changing
the Lyne version or component list. Generated assets and `node_modules/` are
ignored by Git. Only the generated bundle is needed at runtime; `node_modules/`
can be removed after building. If the local bundle is absent, the app uses CDN
loading.

## Hardware firmware

The Pico bridge firmware, reader state machines and USB line protocol live in
[`firmware/labauth_pico`](firmware/labauth_pico/README.md). The fingerprint
backend and enrollment lease are documented in
[`docs/PICO_BACKEND.md`](docs/PICO_BACKEND.md). The fingerprint path is
integrated over USB serial. The current live check confirmed the USB handshake,
mode and switch acknowledgments, and firmware reporting `led=OFF` after disable;
it did not establish a successful fingerprint match. The PN532 I2C reader is
reserved behind `ENABLE_PN532` and currently reports `ABSENT`.

Configure the Pico's serial device before starting LabAuth:

```bash
LABAUTH_PICO_PORT=/dev/ttyACM0 uv run python src/main.py
```

Use `LABAUTH_PICO_PORT=auto` only when exactly one Pico is connected. Port,
device ID and service behavior are described in the backend guide.

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
