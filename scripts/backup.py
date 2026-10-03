#!/usr/bin/env python3
"""CLI entry point for LabAuth backups.

Usage:
    uv run python scripts/backup.py --local-only
    uv run python scripts/backup.py --database-url postgresql://user:pass@host/db
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from services.backup import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
