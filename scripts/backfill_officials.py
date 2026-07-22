"""Backfill game_officials from the S3 raw GUMBO archive — no network fetches.

feed_live.parse() is pure, so the full umpire crews that the old parser
discarded (it kept only Home Plate) are recovered by re-parsing archived
feeds. Idempotent and resumable: only games with no game_officials rows are
processed, and the upsert (ingestion.officials) never clobbers newer data.

Usage:
    .venv\\Scripts\\python scripts\\backfill_officials.py --limit 50   # smoke test
    .venv\\Scripts\\python scripts\\backfill_officials.py --workers 8  # full run
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402
from ingestion import officials, raw_archive  # noqa: E402
from ingestion.parsers import feed_live  # noqa: E402

log = logging.getLogger("backfill_officials")

_TODO = text("""
    SELECT l.object_key, l.s3_key
    FROM ingest_ledger l
    WHERE l.source = 'statsapi_game' AND l.status = 'imported'
      AND l.s3_key IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM game_officials o
                      WHERE o.game_pk = CAST(l.object_key AS BIGINT))
    ORDER BY l.object_key
""")


def _process(item: tuple[str, str]) -> int:
    """Returns the number of officials rows written (0 = feed had none)."""
    game_pk, s3_key = item
    try:
        parsed = feed_live.parse(raw_archive.get_json_gz(s3_key))
        rows = parsed.get("officials", [])
        if rows:
            with get_engine().begin() as conn:
                officials.upsert(conn, rows, source="backfill_s3")
        return len(rows)
    except Exception as exc:
        log.warning("game %s (%s) failed: %s", game_pk, s3_key, exc)
        return -1


def run(limit: int | None = None, workers: int = 8) -> None:
    with get_engine().connect() as conn:
        todo = [tuple(r) for r in conn.execute(_TODO).all()]
    if limit:
        todo = todo[:limit]
    log.info("re-parsing %d archived feeds with %d workers", len(todo), workers)
    done = empty = errors = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n in pool.map(_process, todo):
            if n > 0:
                done += 1
            elif n == 0:
                empty += 1
            else:
                errors += 1
            total = done + empty + errors
            if total % 500 == 0:
                rate = total / max(time.monotonic() - started, 1)
                log.info("progress: %d with officials, %d empty, %d errors, "
                         "%.1f games/s, ~%d min left",
                         done, empty, errors, rate,
                         int((len(todo) - total) / max(rate, 0.01) / 60))
    log.info("finished: %d games with officials, %d without, %d errors",
             done, empty, errors)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    run(limit=args.limit, workers=args.workers)


if __name__ == "__main__":
    main()
