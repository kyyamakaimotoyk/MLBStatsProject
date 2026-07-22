"""Retrosheet game-log import (W0.3, 2026-07 cycle) — historical umpire crews.

Downloads season game-log ZIPs from retrosheet.org, archives the extracted
CSV to S3 (gzipped), and loads the umpire/K/BB subset of the 161-field layout
into retrosheet_gamelogs (migration 0010). Idempotent: per-season
delete-then-insert keyed on the season's date range.

The information used here was obtained free of charge from and is copyrighted
by Retrosheet. Interested parties may contact Retrosheet at
"www.retrosheet.org".

Usage:
    python -m ingestion.import_retrosheet --start 1998 --end 2025
    python -m ingestion.import_retrosheet --start 2024 --end 2024   # smoke
"""

import argparse
import csv
import gzip
import io
import logging
import zipfile

import requests
from sqlalchemy import text

from core.db import get_engine
from ingestion import raw_archive

log = logging.getLogger("import_retrosheet")

URL = "https://www.retrosheet.org/gamelogs/gl{year}.zip"

# 0-indexed positions in the 161-field game-log layout (glfields.txt):
# 0 date yyyymmdd, 1 game number, 3 visitor team, 6 home team,
# 9/10 visitor/home score, 12 day/night, 16 park id,
# visitor offense 21-37 (AB 21, H 22, BB 30, K 32),
# home offense 49-65 (AB 49, H 50, BB 58, K 60),
# umpires 77-88: HP id/name, 1B, 2B, 3B, LF, RF.
F = {
    "date": 0, "game_number": 1, "away_team": 3, "home_team": 6,
    "away_score": 9, "home_score": 10, "day_night": 12, "park_id": 16,
    "away_ab": 21, "away_h": 22, "away_bb": 30, "away_k": 32,
    "home_ab": 49, "home_h": 50, "home_bb": 58, "home_k": 60,
    "ump_hp_rid": 77, "ump_hp_name": 78, "ump_1b_rid": 79, "ump_1b_name": 80,
    "ump_2b_rid": 81, "ump_2b_name": 82, "ump_3b_rid": 83, "ump_3b_name": 84,
    "ump_lf_rid": 85, "ump_lf_name": 86, "ump_rf_rid": 87, "ump_rf_name": 88,
}
_INT_COLS = ("away_score", "home_score", "away_ab", "away_h", "away_bb",
             "away_k", "home_ab", "home_h", "home_bb", "home_k")
_NONE_VALUES = {"", "(none)"}

_INSERT = text(f"""
    INSERT INTO retrosheet_gamelogs
        ({", ".join(k for k in F if k != "date")}, game_date)
    VALUES ({", ".join(f":{k}" for k in F if k != "date")}, :game_date)
""")


def _row(fields: list[str]) -> dict | None:
    if len(fields) < 89:
        return None
    out = {}
    for key, idx in F.items():
        v = fields[idx].strip()
        out[key] = None if v in _NONE_VALUES else v
    d = out.pop("date")
    if not d or len(d) != 8:
        return None
    out["game_date"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    out["game_number"] = int(out["game_number"] or 0)
    for k in _INT_COLS:
        try:
            out[k] = int(out[k]) if out[k] is not None else None
        except ValueError:
            out[k] = None
    return out


def import_season(year: int) -> int:
    resp = requests.get(URL.format(year=year), timeout=120,
                        headers={"User-Agent": "MLBStatsProject/0.1 (personal research)"})
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        content = zf.read(name).decode("latin-1")
    raw_archive.put_text_gz(f"retrosheet/gl{year}.csv.gz", content)

    rows = [r for r in (
        _row(fields) for fields in csv.reader(io.StringIO(content))
    ) if r is not None]
    with get_engine().begin() as conn:
        conn.execute(
            text("""DELETE FROM retrosheet_gamelogs
                    WHERE game_date BETWEEN :a AND :b"""),
            {"a": f"{year}-01-01", "b": f"{year}-12-31"},
        )
        for i in range(0, len(rows), 1000):
            conn.execute(_INSERT, rows[i:i + 1000])
    full_crews = sum(1 for r in rows
                     if all(r[f"ump_{p}_rid"] for p in ("hp", "1b", "2b", "3b")))
    log.info("gl%d: %d games loaded, %d (%.1f%%) with full 4-umpire crews",
             year, len(rows), full_crews, 100 * full_crews / max(len(rows), 1))
    return len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=1998)
    ap.add_argument("--end", type=int, default=2025)
    args = ap.parse_args()
    total = 0
    for year in range(args.start, args.end + 1):
        try:
            total += import_season(year)
        except Exception as exc:
            log.warning("gl%d failed: %s", year, exc)
    log.info("done: %d games total", total)


if __name__ == "__main__":
    main()
