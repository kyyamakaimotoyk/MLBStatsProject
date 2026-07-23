"""B9b (2026-07 cycle): Savant Outs Above Average importer.

Pulls the player-level OAA leaderboard CSVs (the only files carrying
fielding_runs_prevented) per season and per month bucket, archives each raw
CSV to S3, and loads oaa_import (migration 0013). Export mechanics verified
2026-07-22 (docs/literature_review_2026-07.md P4): csv=true works
unauthenticated with a browser-ish User-Agent; range=year|4..9 (4 = combined
March/April); the CSV's year column is EMPTY, so season/bucket come from the
request parameters; infield OAA exists 2020+ only.

Idempotent: delete-then-insert per (season, bucket). The leakage rule lives
with the table (migration comment) and is enforced by the feature builder,
never here.

Usage:
    python -m ingestion.import_oaa --start 2016 --end 2026
    python -m ingestion.import_oaa --start 2024 --end 2024 --year-only  # smoke
"""

import argparse
import io
import logging
import time

import pandas as pd
import requests
from sqlalchemy import text

from core.db import get_engine
from ingestion import raw_archive

log = logging.getLogger("import_oaa")

URL = "https://baseballsavant.mlb.com/leaderboard/outs_above_average"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "MLBStatsProject research"}
MONTH_BUCKETS = (4, 5, 6, 7, 8, 9)  # 4 = combined March/April

# Savant CSV header -> oaa_import column. Headers drift; unmapped columns are
# logged once per file and skipped, absent ones land as NULL.
RENAME = {
    "player_id": "player_id",
    "last_name, first_name": "player_name", "player_name": "player_name",
    "display_team_name": "team", "team": "team", "team_name": "team",
    "primary_pos_formatted": "position", "pos": "position",
    "attempts": "attempts", "fielding_attempts": "attempts",
    "outs_above_average": "oaa",
    "fielding_runs_prevented": "runs_prevented",
    "actual_success_rate_formatted": "actual_success_rate",
    "actual_success_rate": "actual_success_rate",
    "adj_estimated_success_rate_formatted": "est_success_rate",
    "estimated_success_rate": "est_success_rate",
}
_PCT_COLS = ("actual_success_rate", "est_success_rate")  # arrive as '71%'
TABLE_COLS = ("season", "month_bucket", "player_id", "position", "player_name",
              "team", "attempts", "oaa", "runs_prevented",
              "actual_success_rate", "est_success_rate", "source_file")

_INSERT = text(
    "INSERT INTO oaa_import ({cols}) VALUES ({params}) "
    "ON CONFLICT (season, month_bucket, player_id, position) DO UPDATE SET "
    "player_name = EXCLUDED.player_name, team = EXCLUDED.team, "
    "attempts = EXCLUDED.attempts, oaa = EXCLUDED.oaa, "
    "runs_prevented = EXCLUDED.runs_prevented, "
    "actual_success_rate = EXCLUDED.actual_success_rate, "
    "est_success_rate = EXCLUDED.est_success_rate, "
    "source_file = EXCLUDED.source_file, imported_at = now()".format(
        cols=", ".join(TABLE_COLS),
        params=", ".join(f":{c}" for c in TABLE_COLS)))


def fetch(season: int, bucket: int) -> str:
    """bucket 0 = full season, 4..9 = month slice.

    The honored season parameter is `year` — startSeason/endSeason and
    seasonStart/seasonEnd are silently IGNORED and the endpoint serves the
    current season instead (caught 2026-07-23 when a 'completed' season came
    back with empty Aug/Sep buckets). load() cross-checks the CSV's own year
    column against the request."""
    params = {"type": "Fielder", "year": season,
              "range": "year" if bucket == 0 else str(bucket),
              "min": "1", "csv": "true"}
    resp = requests.get(URL, params=params, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    if "player_id" not in resp.text[:2000]:
        raise ValueError(f"unexpected response (not the CSV export?): "
                         f"{resp.text[:120]!r}")
    return resp.text


def load(season: int, bucket: int, csv_text: str, source_file: str) -> int:
    df = pd.read_csv(io.StringIO(csv_text))
    if df.empty:
        return 0
    if "year" in df.columns:
        years = set(df["year"].dropna().astype(int).unique())
        if years and years != {season}:
            raise ValueError(f"season mismatch: requested {season}, "
                             f"CSV carries {sorted(years)} — param drift?")
    known = {c: RENAME[c] for c in df.columns if c in RENAME}
    unmapped = [c for c in df.columns if c not in RENAME]
    if unmapped:
        log.info("%s: unmapped columns (skipped): %s", source_file, unmapped)
    df = df[list(known)].rename(columns=known)
    # duplicate targets (e.g. two name variants) — keep the first occurrence
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.dropna(subset=["player_id"])
    df["player_id"] = df["player_id"].astype(int)
    for col in ("position", "player_name", "team"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    for col in _PCT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.rstrip("%"), errors="coerce") / 100.0
    df["season"], df["month_bucket"] = season, bucket
    df["position"] = df.get("position", pd.Series("", index=df.index)).fillna("")
    df["source_file"] = source_file
    df = df.reindex(columns=list(TABLE_COLS))
    df = df.astype(object).where(df.notna(), None)
    records = df.to_dict("records")
    with get_engine().begin() as conn:
        conn.execute(text("""DELETE FROM oaa_import
                             WHERE season = :s AND month_bucket = :b"""),
                     {"s": season, "b": bucket})
        conn.execute(_INSERT, records)
    return len(records)


def run(start: int, end: int, year_only: bool = False, sleep: float = 2.0) -> None:
    total = 0
    for season in range(start, end + 1):
        buckets = (0,) if year_only else (0, *MONTH_BUCKETS)
        for bucket in buckets:
            tag = "year" if bucket == 0 else f"m{bucket}"
            source_file = f"savant_oaa/{season}/{tag}.csv.gz"
            try:
                csv_text = fetch(season, bucket)
                raw_archive.put_text_gz(source_file, csv_text)
                n = load(season, bucket, csv_text, source_file)
                total += n
                log.info("%d %s: %d rows", season, tag, n)
            except Exception as exc:
                log.warning("%d %s failed: %s", season, tag, exc)
            time.sleep(sleep)
    log.info("done: %d rows total", total)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=2016)
    ap.add_argument("--end", type=int, default=2026)
    ap.add_argument("--year-only", action="store_true")
    ap.add_argument("--sleep", type=float, default=2.0)
    args = ap.parse_args()
    run(args.start, args.end, year_only=args.year_only, sleep=args.sleep)


if __name__ == "__main__":
    main()
