"""B8b (2026-07 cycle): re-parse the S3 raw Statcast archive into the widened
statcast_pitches (migration 0012) — on_1b/2b/3b base state, score state,
sz_top/bot, spray + fielder identities, spin_axis and friends.

Archive-only by design: Savant retro-revises data, so re-fetching would
silently drift the already-curated columns; re-parsing the archive keeps
them byte-identical while adding the new ones. Ledger-driven and resumable
under its own source ('statcast_reprocess', seeded from imported
statcast_day entries); each day is one delete-then-insert transaction via
ingestion.backfill_statcast.load_day, so readers never see a partial day.

Do NOT run concurrently with a feature-snapshot rebuild (shared RDS); expect
~1,300 day-files / ~5.5-6M rows, several hours. Check RDS free storage first
(the script prints current table size; expect ~30-40% growth).

Usage:
    .venv\\Scripts\\python scripts\\reprocess_statcast.py --limit 3   # smoke
    .venv\\Scripts\\python scripts\\reprocess_statcast.py             # full run
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402
from ingestion import ledger, raw_archive  # noqa: E402
from ingestion.backfill_statcast import load_day  # noqa: E402

log = logging.getLogger("reprocess_statcast")

SOURCE = "statcast_reprocess"


def _seed_and_map() -> dict[str, str]:
    """Seed the reprocess ledger from every imported statcast_day entry and
    return {day: s3_key}."""
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT object_key, s3_key FROM ingest_ledger
            WHERE source = 'statcast_day' AND status = 'imported'
              AND s3_key IS NOT NULL
        """)).all()
    mapping = {day: key for day, key in rows}
    ledger.seed(SOURCE, sorted(mapping))
    return mapping


def run(limit: int | None = None, sleep: float = 0.0) -> None:
    with get_engine().connect() as conn:
        size, nrows = conn.execute(text(
            "SELECT pg_size_pretty(pg_total_relation_size('statcast_pitches')), "
            "(SELECT count(*) FROM statcast_pitches)")).one()
    log.info("statcast_pitches: %s rows, %s on disk — expect ~30-40%% growth; "
             "verify RDS free storage before a full run", f"{nrows:,}", size)

    mapping = _seed_and_map()
    days = ledger.pending(SOURCE, limit)
    log.info("reprocessing %d pending days (of %d archived)", len(days), len(mapping))
    done = errors = pitches = 0
    started = time.monotonic()
    for day in days:
        s3_key = mapping.get(day)
        if not s3_key:
            ledger.mark(SOURCE, day, "permanent_missing", detail="no s3_key")
            continue
        try:
            n = load_day(day, raw_archive.get_text_gz(s3_key))
            ledger.mark(SOURCE, day, "imported", s3_key=s3_key, detail=f"{n} pitches")
            done += 1
            pitches += n
        except Exception as exc:
            try:
                ledger.mark(SOURCE, day, "error", detail=str(exc))
            except Exception:
                log.warning("day %s: ledger unreachable, left pending", day)
            errors += 1
            log.warning("day %s failed: %s", day, exc)
        if (done + errors) % 25 == 0:
            rate = (done + errors) / max(time.monotonic() - started, 1)
            log.info("progress: %d days, %d errors, %s pitches, ~%d min left",
                     done, errors, f"{pitches:,}",
                     int((len(days) - done - errors) / max(rate, 1e-6) / 60))
        if sleep:
            time.sleep(sleep)
    log.info("finished: %d days, %d errors, %s pitches | ledger %s",
             done, errors, f"{pitches:,}", ledger.counts(SOURCE))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()
    run(limit=args.limit, sleep=args.sleep)


if __name__ == "__main__":
    main()
