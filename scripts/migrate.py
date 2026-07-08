"""Ordered-SQL migration runner.

Applies migrations/*.sql in filename order, recording each applied file in
schema_migrations. Plain, numbered SQL keeps the schema visible and diffable —
this replaces the NBA project's ad-hoc ALTER TABLE auto-evolution.

Usage:
    python scripts/migrate.py            # apply pending migrations
    python scripts/migrate.py --dry-run  # list pending without applying
"""

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename   TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        applied = {
            row[0] for row in conn.execute(text("SELECT filename FROM schema_migrations"))
        }

    pending = [
        p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in applied
    ]
    if not pending:
        print("Up to date; nothing to apply.")
        return

    for path in pending:
        if dry_run:
            print(f"pending: {path.name}")
            continue
        with engine.begin() as conn:
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {"f": path.name},
            )
        print(f"applied: {path.name}")


if __name__ == "__main__":
    main()
