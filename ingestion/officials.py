"""Canonical writer for game_officials (migration 0009).

One upsert used by every capture path (live import, S3 re-parse, pregame
probes, Retrosheet history). The ON CONFLICT clause only overwrites when the
official IDENTITY changed: a row whose identity is already correct keeps its
original source and captured_at, so the earliest pregame sighting survives
later imports — that first-seen timestamp against first_pitch_utc IS the
officials-post-time measurement.
"""

from sqlalchemy import text

UPSERT = text("""
    INSERT INTO game_officials
        (game_pk, official_type, official_id, official_name, source, captured_at)
    VALUES (:game_pk, :official_type, :official_id, :official_name, :source, now())
    ON CONFLICT (game_pk, official_type) DO UPDATE SET
        official_id = EXCLUDED.official_id,
        official_name = EXCLUDED.official_name,
        source = EXCLUDED.source,
        captured_at = EXCLUDED.captured_at
    WHERE game_officials.official_id IS DISTINCT FROM EXCLUDED.official_id
""")


def upsert(conn, officials: list[dict], source: str) -> None:
    if not officials:
        return
    conn.execute(UPSERT, [{**o, "source": source} for o in officials])
