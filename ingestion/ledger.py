"""Helpers around the ingest_ledger table (migrations/0001).

Every fetchable object gets a row before any network call; ingestion is
therefore resumable and idempotent — kill a backfill at any point and rerun.

To retry objects that exhausted their attempts:
    UPDATE ingest_ledger SET attempts = 0, status = 'pending'
    WHERE source = :source AND status = 'error';
"""

from sqlalchemy import text

from core.db import get_engine

MAX_ATTEMPTS = 5


def seed(source: str, keys: list) -> None:
    """Register objects as pending; already-known keys are untouched."""
    if not keys:
        return
    rows = [{"source": source, "key": str(k)} for k in keys]
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ingest_ledger (source, object_key)
                VALUES (:source, :key)
                ON CONFLICT (source, object_key) DO NOTHING
                """
            ),
            rows,
        )


def pending(source: str, limit: int | None = None) -> list[str]:
    sql = """
        SELECT object_key FROM ingest_ledger
        WHERE source = :source AND status IN ('pending', 'error') AND attempts < :max
        ORDER BY object_key
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_engine().connect() as conn:
        return conn.execute(text(sql), {"source": source, "max": MAX_ATTEMPTS}).scalars().all()


def mark(source: str, key, status: str, s3_key: str | None = None, detail: str | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE ingest_ledger
                SET status = :status,
                    attempts = attempts + 1,
                    s3_key = COALESCE(:s3_key, s3_key),
                    detail = :detail,
                    updated_at = now()
                WHERE source = :source AND object_key = :key
                """
            ),
            {"source": source, "key": str(key), "status": status, "s3_key": s3_key,
             "detail": detail[:500] if detail else None},
        )


def counts(source: str) -> dict[str, int]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT status, count(*) FROM ingest_ledger WHERE source = :s GROUP BY status"),
            {"s": source},
        ).all()
    return {status: n for status, n in rows}
