"""Backup service for LabAuth.

Produces a consistent SQLite snapshot using SQLite's own backup API (never a
naive file copy of a live database) and pushes a full copy of every table to a
self-hosted PostgreSQL instance.

The PostgreSQL URL is intentionally a placeholder for now
(``backup.example.invalid`` per RFC 2606) so the pipeline can be wired and
exercised safely before real credentials exist. Local snapshots work without
any network access; only the remote push needs ``psycopg``.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import database as db

#: Placeholder target. Override with LABAUTH_BACKUP_DATABASE_URL or --database-url.
DEFAULT_BACKUP_URL = "postgresql://labauth:labauth@backup.example.invalid:5432/labauth"

#: Target schema mirror on PostgreSQL. Timestamps are kept as TEXT so the copy
#: is lossless and needs no parsing; BLOBs map to BYTEA.
POSTGRES_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id          BIGINT PRIMARY KEY,
        plaksha_id  TEXT,
        name        TEXT NOT NULL,
        photo       TEXT,
        is_temp     SMALLINT,
        status      TEXT,
        created_at  TEXT,
        updated_at  TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS access_areas (
        id          BIGINT PRIMARY KEY,
        code        TEXT NOT NULL,
        label       TEXT NOT NULL,
        sort_order  INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credentials (
        id               BIGINT PRIMARY KEY,
        user_id          BIGINT,
        credential_type  TEXT,
        identifier       TEXT,
        template         BYTEA,
        is_active        SMALLINT,
        enrolled_at      TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_access_areas (
        user_id     BIGINT NOT NULL,
        area_id     BIGINT NOT NULL,
        granted_at  TEXT,
        granted_by  TEXT,
        PRIMARY KEY (user_id, area_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bans (
        id           BIGINT PRIMARY KEY,
        user_id      BIGINT,
        reason       TEXT,
        banned_at    TEXT,
        unbanned_at  TEXT,
        banned_by    TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS presence_log (
        id             BIGINT PRIMARY KEY,
        user_id        BIGINT,
        event_type     TEXT,
        entry_method   TEXT,
        credential_id  BIGINT,
        occurred_at    TEXT,
        device_id      TEXT,
        metadata       TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credential_attempts (
        id               BIGINT PRIMARY KEY,
        occurred_at      TEXT,
        credential_type  TEXT,
        identifier       TEXT,
        user_id          BIGINT,
        outcome          TEXT,
        message          TEXT,
        device_id        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id           BIGINT PRIMARY KEY,
        occurred_at  TEXT,
        actor        TEXT,
        action       TEXT,
        entity_type  TEXT,
        entity_id    TEXT,
        before       TEXT,
        after        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_runs (
        id           BIGINT PRIMARY KEY,
        started_at   TEXT,
        finished_at  TEXT,
        status       TEXT,
        destination  TEXT,
        size_bytes   BIGINT,
        error        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS current_presence (
        user_id        BIGINT PRIMARY KEY,
        checked_in_at  TEXT,
        updated_at     TEXT
    )
    """,
)


def database_url() -> str:
    return os.environ.get("LABAUTH_BACKUP_DATABASE_URL", DEFAULT_BACKUP_URL)


@dataclass
class BackupResult:
    run: db.BackupRun
    snapshot_path: Optional[str]
    rows_copied: int
    remote_ok: bool


def default_snapshot_dir() -> Path:
    return db.db_path().parent / "backups"


def snapshot_database(destination: Path, source: Optional[Path] = None) -> Path:
    """Create a consistent snapshot of the live SQLite database."""
    source = source or db.db_path()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return destination


def _read_snapshot(snapshot_path: Path) -> tuple[dict[str, list[str]], dict[str, list[tuple]]]:
    columns: dict[str, list[str]] = {}
    rows: dict[str, list[tuple]] = {}
    conn = sqlite3.connect(str(snapshot_path))
    conn.row_factory = sqlite3.Row
    try:
        for table in db.BACKUP_TABLE_ORDER:
            table_columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
            columns[table] = table_columns
            if not table_columns:
                rows[table] = []
                continue
            select = ", ".join(table_columns)
            rows[table] = [
                tuple(row) for row in conn.execute(f"SELECT {select} FROM {table}").fetchall()
            ]
    finally:
        conn.close()
    return columns, rows


def push_snapshot_to_postgres(snapshot_path: Path, dsn: str) -> int:
    """Replace every table on the PostgreSQL target with the snapshot's contents."""
    try:
        import psycopg  # type: ignore import-not-found
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "psycopg is not installed. Install the backup extra with "
            "`uv sync --extra backup` (or `pip install 'psycopg[binary]'`)."
        ) from exc

    columns, rows = _read_snapshot(Path(snapshot_path))
    total = 0
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for statement in POSTGRES_SCHEMA:
                cur.execute(statement)

            table_list = ", ".join(db.BACKUP_TABLE_ORDER)
            cur.execute(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")

            for table in db.BACKUP_TABLE_ORDER:
                table_columns = columns[table]
                table_rows = rows[table]
                if not table_columns or not table_rows:
                    continue
                placeholders = ", ".join(["%s"] * len(table_columns))
                statement = (
                    f"INSERT INTO {table} ({', '.join(table_columns)}) "
                    f"VALUES ({placeholders})"
                )
                cur.executemany(statement, table_rows)
                total += len(table_rows)
    return total


class BackupService:
    """Snapshot the local database and mirror it to PostgreSQL."""

    def __init__(
        self,
        *,
        target_url: Optional[str] = None,
        snapshot_dir: Optional[Path] = None,
        push: bool = True,
    ) -> None:
        self.target_url = target_url or database_url()
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else default_snapshot_dir()
        self.push = push

    def run(self, *, keep_snapshot: bool = True) -> BackupResult:
        db.init_db()
        run = db.create_backup_run(self.target_url)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        snapshot_path = self.snapshot_dir / f"labauth-{stamp}.db"
        size_bytes: Optional[int] = None
        try:
            snapshot_database(snapshot_path)
            size_bytes = snapshot_path.stat().st_size
            rows_copied = (
                push_snapshot_to_postgres(snapshot_path, self.target_url) if self.push else 0
            )
            finished = db.finish_backup_run(run.id, "success", size_bytes=size_bytes) or run
            result = BackupResult(
                run=finished,
                snapshot_path=str(snapshot_path),
                rows_copied=rows_copied,
                remote_ok=self.push,
            )
            return result
        except Exception as exc:
            if snapshot_path.exists():
                size_bytes = snapshot_path.stat().st_size
            db.finish_backup_run(
                run.id,
                "failed",
                size_bytes=size_bytes,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            if not keep_snapshot and snapshot_path.exists():
                snapshot_path.unlink()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the LabAuth SQLite database.")
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "PostgreSQL target (default: LABAUTH_BACKUP_DATABASE_URL env var "
            f"or {DEFAULT_BACKUP_URL})"
        ),
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Only create the SQLite snapshot; do not push to PostgreSQL.",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help=f"Where to write snapshots (default: {default_snapshot_dir()})",
    )
    parser.add_argument(
        "--delete-snapshot",
        action="store_true",
        help="Remove the local snapshot once the backup finishes successfully.",
    )
    args = parser.parse_args(argv)

    target = args.database_url or database_url()
    service = BackupService(
        target_url=target,
        snapshot_dir=Path(args.snapshot_dir) if args.snapshot_dir else None,
        push=not args.local_only,
    )

    print(f"Source database : {db.db_path()}")
    print(f"Snapshot        : {service.snapshot_dir}")
    print(f"Target          : {'(local only)' if args.local_only else target}")
    try:
        result = service.run(keep_snapshot=not args.delete_snapshot)
    except Exception as exc:
        print(f"Backup FAILED: {exc}")
        return 1

    print(f"Snapshot written: {result.snapshot_path}")
    print(f"Rows copied     : {result.rows_copied}")
    print(f"Backup run id   : {result.run.id} ({result.run.status})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
