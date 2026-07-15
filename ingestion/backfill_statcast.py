"""Statcast pitch-level backfill from Baseball Savant's CSV search endpoint.

One request per game day (~4-5k pitches), driven by 'statcast_day' ledger
entries (seeded by backfill_games.seed_range). Raw CSV is archived to S3;
a curated column subset lands in statcast_pitches (delete-then-insert per
day, so re-runs are idempotent). No pybaseball dependency — this is the same
endpoint it wraps, with our own retry/archive/ledger handling.

Usage:
    python -m ingestion.backfill_statcast --season 2024   # seed days + run
    python -m ingestion.backfill_statcast --limit 3       # run pending days
"""

import argparse
import io
import logging
import time

import pandas as pd
import requests
from sqlalchemy import text

from core.db import get_engine
from ingestion import ledger, raw_archive
from ingestion.backfill_games import seed_range

log = logging.getLogger("backfill_statcast")

SOURCE = "statcast_day"
SEARCH_URL = "https://baseballsavant.mlb.com/statcast_search/csv"
TIMEOUT_SECONDS = 180
MAX_RETRIES = 4

# Column name in Savant CSV -> column in statcast_pitches (same order as table).
COLUMNS = {
    "game_pk": "game_pk", "game_date": "game_date",
    "at_bat_number": "at_bat_number", "pitch_number": "pitch_number",
    "batter": "batter_id", "pitcher": "pitcher_id",
    "stand": "stand", "p_throws": "p_throws",
    "inning": "inning", "inning_topbot": "inning_topbot",
    "balls": "balls", "strikes": "strikes", "outs_when_up": "outs_when_up",
    "pitch_type": "pitch_type", "pitch_name": "pitch_name",
    "release_speed": "release_speed", "release_spin_rate": "release_spin_rate",
    "release_extension": "release_extension",
    "pfx_x": "pfx_x", "pfx_z": "pfx_z", "plate_x": "plate_x", "plate_z": "plate_z",
    "zone": "zone", "type": "type", "description": "description",
    "events": "events", "bb_type": "bb_type",
    "launch_speed": "launch_speed", "launch_angle": "launch_angle",
    "hit_distance_sc": "hit_distance_sc",
    "estimated_ba_using_speedangle": "estimated_ba_using_speedangle",
    "estimated_woba_using_speedangle": "estimated_woba_using_speedangle",
    "woba_value": "woba_value", "woba_denom": "woba_denom",
    "babip_value": "babip_value", "iso_value": "iso_value",
    "delta_run_exp": "delta_run_exp",
    "home_team": "home_team", "away_team": "away_team",
}

_INSERT = text(
    "INSERT INTO statcast_pitches ({cols}) VALUES ({params}) "
    "ON CONFLICT (game_pk, at_bat_number, pitch_number) DO NOTHING".format(
        cols=", ".join(COLUMNS.values()),
        params=", ".join(f":{c}" for c in COLUMNS.values()),
    )
)


def fetch_day(day: str) -> str:
    """Return the raw CSV text for one date (regular season + postseason)."""
    params = {
        "all": "true", "type": "details", "player_type": "pitcher",
        "hfGT": "R|PO|", "game_date_gt": day, "game_date_lt": day,
        "min_pitches": "0", "min_results": "0", "min_pas": "0",
    }
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(SEARCH_URL, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            log.warning("attempt %d/%d for %s failed: %s", attempt, MAX_RETRIES, day, exc)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def load_day(day: str, csv_text: str) -> int:
    df = pd.read_csv(io.StringIO(csv_text), low_memory=False)
    if df.empty:
        return 0
    keep = [c for c in COLUMNS if c in df.columns]
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        log.warning("%s: columns missing from Savant CSV: %s", day, missing)
    df = df[keep].rename(columns=COLUMNS)
    df = df.dropna(subset=["game_pk", "at_bat_number", "pitch_number"])
    df = df.drop_duplicates(subset=["game_pk", "at_bat_number", "pitch_number"])
    for col in ("game_pk", "at_bat_number", "pitch_number"):
        df[col] = df[col].astype(int)
    df = df.astype(object).where(df.notna(), None)
    records = df.to_dict("records")

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM statcast_pitches WHERE game_date = :d"), {"d": day})
        for i in range(0, len(records), 5000):
            conn.execute(_INSERT, records[i : i + 5000])
    return len(records)


def run(limit: int | None = None, sleep: float = 1.0) -> None:
    days = ledger.pending(SOURCE, limit)
    log.info("processing %d pending days", len(days))
    done = errors = 0
    for day in days:
        try:
            csv_text = fetch_day(day)
            season = day[:4]
            s3_key = raw_archive.put_text_gz(f"statcast/{season}/{day}.csv.gz", csv_text)
            n = load_day(day, csv_text)
            if n == 0:
                # The schedule said games happened this day; an empty CSV is a
                # fetch problem, not an empty day — retry later.
                ledger.mark(SOURCE, day, "error", detail="0 rows returned")
                errors += 1
            else:
                ledger.mark(SOURCE, day, "imported", s3_key=s3_key, detail=f"{n} pitches")
                done += 1
        except Exception as exc:
            try:
                ledger.mark(SOURCE, day, "error", detail=str(exc))
            except Exception:
                # DB unreachable: leave the day pending, no attempt burned.
                log.warning("day %s: ledger unreachable, left pending", day)
            errors += 1
            log.warning("day %s failed: %s", day, exc)
        if (done + errors) % 10 == 0:
            log.info("progress: %d days ok, %d errors", done, errors)
        time.sleep(sleep)
    log.info("finished: %d days, %d errors | ledger now %s", done, errors, ledger.counts(SOURCE))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, help="seed a whole season's days first")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    if args.season:
        seed_range(f"{args.season}-03-01", f"{args.season}-11-30")
    run(limit=args.limit, sleep=args.sleep)


if __name__ == "__main__":
    main()
