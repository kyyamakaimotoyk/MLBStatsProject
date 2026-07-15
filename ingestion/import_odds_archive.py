"""One-time historical odds import from the scraped SportsBookReview dataset
(github.com/ArnavSaraogi/mlb-odds-scraper release asset, 2021-2025).

Benchmark-only, like all odds (migrations/0006). Two consensus rows per game:
  book='consensus_open'  is_closing=FALSE  — cross-book median opening line
  book='consensus'       is_closing=TRUE   — cross-book median of current
                                             lines that pass a stability filter

Stability filter: the dataset's "currentLine" is whenever the scrape ran —
for finished games some books show IN-GAME lines. A book is kept for the
closing consensus only if its implied home probability moved < 0.15 from its
open; live lines swing far more, real closing moves almost never do.

Usage:
    python -m ingestion.import_odds_archive --file mlb_odds_dataset.json --from-season 2022
"""

import argparse
import json
import logging
import statistics

import pandas as pd
from sqlalchemy import text

from core.db import get_engine

log = logging.getLogger("odds_archive")

NAME_OVERRIDES = {
    "Oakland Athletics": "Athletics",
    "Cleveland Indians": "Cleveland Guardians",
}
MAX_CLOSE_SHIFT = 0.15


def _implied(home_odds, away_odds):
    def p(a):
        return (-a / (-a + 100.0)) if a < 0 else (100.0 / (a + 100.0))
    try:
        ph, pa = p(float(home_odds)), p(float(away_odds))
        return ph / (ph + pa)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _median(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _consensus(game: dict) -> dict | None:
    """Consensus open + stability-filtered close for one game entry."""
    odds = game.get("odds") or {}
    ml = odds.get("moneyline") or []
    spreads = odds.get("pointspread") or []
    totals = odds.get("total") or odds.get("totals") or []

    open_home, open_away, close_home, close_away = [], [], [], []
    for book in ml:
        o, c = book.get("openingLine") or {}, book.get("currentLine") or {}
        open_home.append(o.get("homeOdds"))
        open_away.append(o.get("awayOdds"))
        p_open = _implied(o.get("homeOdds"), o.get("awayOdds"))
        p_cur = _implied(c.get("homeOdds"), c.get("awayOdds"))
        if p_open is not None and p_cur is not None and abs(p_cur - p_open) < MAX_CLOSE_SHIFT:
            close_home.append(c.get("homeOdds"))
            close_away.append(c.get("awayOdds"))

    def spread_median(key):
        return (_median([(b.get(key) or {}).get("homeSpread") for b in spreads]),
                _median([(b.get(key) or {}).get("homeOdds") for b in spreads]),
                _median([(b.get(key) or {}).get("awayOdds") for b in spreads]))

    def total_median(key):
        return (_median([(b.get(key) or {}).get("total") for b in totals]),
                _median([(b.get(key) or {}).get("overOdds") for b in totals]),
                _median([(b.get(key) or {}).get("underOdds") for b in totals]))

    out = {}
    for label, closing, mlh, mla, spread_key, total_key in (
        ("consensus_open", False, _median(open_home), _median(open_away),
         "openingLine", "openingLine"),
        ("consensus", True, _median(close_home), _median(close_away),
         "currentLine", "currentLine"),
    ):
        if mlh is None or mla is None:
            continue
        rl, rl_hp, rl_ap = spread_median(spread_key)
        tot, over_p, under_p = total_median(total_key)
        out[label] = {
            "book": label, "is_closing": closing,
            "ml_home": int(mlh), "ml_away": int(mla),
            "runline_home": rl,
            "runline_home_price": int(rl_hp) if rl_hp is not None else None,
            "runline_away_price": int(rl_ap) if rl_ap is not None else None,
            "total": tot,
            "over_price": int(over_p) if over_p is not None else None,
            "under_price": int(under_p) if under_p is not None else None,
            "source": "archive_sbr",
        }
    return out or None


def run(path: str, from_season: int) -> None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    games = pd.read_sql(text("""
        SELECT g.game_pk, g.game_date::text AS game_date, g.first_pitch_utc,
               ht.name AS home_name, at.name AS away_name
        FROM games g
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        WHERE g.season >= :s
        ORDER BY g.first_pitch_utc NULLS LAST, g.game_pk
    """), get_engine(), params={"s": from_season})
    slots: dict[tuple, list] = {}
    for g in games.itertuples():
        slots.setdefault((g.game_date, g.home_name, g.away_name), []).append(g.game_pk)

    records, matched, unmatched, no_odds = [], 0, 0, 0
    for date, day_games in sorted(data.items()):
        if date < f"{from_season}-01-01":
            continue
        for entry in sorted(day_games, key=lambda e: (e.get("gameView") or {}).get("startDate") or ""):
            view = entry.get("gameView") or {}
            home = NAME_OVERRIDES.get(view.get("homeTeam", {}).get("fullName"),
                                      view.get("homeTeam", {}).get("fullName"))
            away = NAME_OVERRIDES.get(view.get("awayTeam", {}).get("fullName"),
                                      view.get("awayTeam", {}).get("fullName"))
            pks = slots.get((date, home, away)) or []
            if not pks:
                unmatched += 1
                continue
            cons = _consensus(entry)
            if not cons:
                no_odds += 1
                pks.pop(0)
                continue
            game_pk = pks.pop(0)
            matched += 1
            for row in cons.values():
                records.append({"game_pk": game_pk, "captured_at": view.get("startDate")
                                or f"{date}T12:00:00+00:00", **row})

    log.info("matched %d games (%d unmatched, %d without usable odds); %d rows",
             matched, unmatched, no_odds, len(records))
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM odds_lines WHERE source = 'archive_sbr'"))
        insert = text("""
            INSERT INTO odds_lines
                (game_pk, book, captured_at, is_closing, ml_home, ml_away,
                 runline_home, runline_home_price, runline_away_price,
                 total, over_price, under_price, source)
            VALUES (:game_pk, :book, :captured_at, :is_closing, :ml_home, :ml_away,
                    :runline_home, :runline_home_price, :runline_away_price,
                    :total, :over_price, :under_price, :source)
            ON CONFLICT (game_pk, book, captured_at) DO NOTHING
        """)
        for i in range(0, len(records), 2000):
            conn.execute(insert, records[i : i + 2000])
    log.info("import complete")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    ap.add_argument("--from-season", type=int, default=2022)
    args = ap.parse_args()
    run(args.file, args.from_season)


if __name__ == "__main__":
    main()
