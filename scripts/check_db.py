"""Connectivity and schema sanity check.

Verifies the RDS connection (including the Secrets Manager credential path),
prints the server version, and lists public tables with row counts.

Usage: python scripts/check_db.py
"""

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402


def main() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version()")).scalar_one()
        print(f"connected: {version}")
        tables = conn.execute(
            text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' ORDER BY table_name
                """
            )
        ).scalars().all()
        if not tables:
            print("no tables yet (run scripts/migrate.py)")
        for table in tables:
            count = conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            print(f"  {table}: {count} rows")


if __name__ == "__main__":
    main()
