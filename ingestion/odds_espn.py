"""Daily betting-line capture from ESPN's public scoreboard endpoint (the NBA
project's vegas_lines_espn.py pattern). Benchmark-only — see migrations/0006.

ESPN retains the last pregame line on past dates, so capturing yesterday with
--closing stores an approximate closing line; capturing today stores the
current (morning) line. Games are matched to game_pk by (date, home, away)
team names, with doubleheaders zipped in start order.

Usage:
    python -m ingestion.odds_espn --date 2026-07-16            # morning line
    python -m ingestion.odds_espn --date 2026-07-12 --closing  # last line
"""

import argparse
import logging

import pandas as pd
import requests
from sqlalchemy import text

from core.db import get_engine

log = logging.getLogger("odds_espn")

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"

# ESPN displayName -> MLB StatsAPI name, where they differ.
NAME_OVERRIDES = {
    "Oakland Athletics": "Athletics",
    "Arizona Diamondbacks": "Arizona Diamondbacks",
}


def _int(v):
    try:
        return int(v) if v not in (None, "", "EVEN") else (100 if v == "EVEN" else None)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"


def fetch_day(date: str) -> list[dict]:
    """One dict per ESPN event with parsed odds. The scoreboard no longer
    embeds odds; each event's summary endpoint carries them in pickcenter."""
    import time

    resp = requests.get(SCOREBOARD, params={"dates": date.replace("-", ""), "limit": 100},
                        timeout=60)
    resp.raise_for_status()
    events = resp.json().get("events", [])
    rows = []
    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if not teams.get("home"):
            continue
        try:
            summary = requests.get(SUMMARY, params={"event": ev["id"]}, timeout=60).json()
        except requests.RequestException as exc:
            log.warning("summary for event %s failed: %s", ev.get("id"), exc)
            continue
        pick = summary.get("pickcenter") or []
        if not pick:
            continue
        o = pick[0]
        home_odds = o.get("homeTeamOdds") or {}
        away_odds = o.get("awayTeamOdds") or {}
        rows.append({
            "start": ev.get("date"),
            "state": ((ev.get("status") or {}).get("type") or {}).get("state"),
            "home_name": teams["home"].get("team", {}).get("displayName"),
            "away_name": teams["away"].get("team", {}).get("displayName"),
            "book": (o.get("provider") or {}).get("name", "unknown"),
            "ml_home": _int(home_odds.get("moneyLine")),
            "ml_away": _int(away_odds.get("moneyLine")),
            "runline_home": _float(o.get("spread")),
            "runline_home_price": _int(home_odds.get("spreadOdds")),
            "runline_away_price": _int(away_odds.get("spreadOdds")),
            "total": _float(o.get("overUnder")),
            "over_price": _int(o.get("overOdds")),
            "under_price": _int(o.get("underOdds")),
        })
        time.sleep(0.3)
    return rows


def capture(date: str, closing: bool = False) -> int:
    """Fetch, match to game_pk, and store one line per game. Returns rows written."""
    espn = fetch_day(date)
    if not espn:
        log.info("%s: no ESPN events/odds", date)
        return 0
    engine = get_engine()
    games = pd.read_sql(text("""
        SELECT g.game_pk, g.first_pitch_utc, g.game_number,
               ht.name AS home_name, at.name AS away_name
        FROM games g
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        WHERE g.game_date = :d
        ORDER BY g.first_pitch_utc NULLS LAST, g.game_number NULLS LAST, g.game_pk
    """), engine, params={"d": date})

    # zip per (home, away) matchup in start order (doubleheader-safe)
    assigned: dict[tuple, list] = {}
    for g in games.itertuples():
        assigned.setdefault((g.home_name, g.away_name), []).append(g.game_pk)

    records, unmatched, started = [], [], 0
    for row in sorted(espn, key=lambda r: r["start"] or ""):
        home = NAME_OVERRIDES.get(row["home_name"], row["home_name"])
        away = NAME_OVERRIDES.get(row["away_name"], row["away_name"])
        pks = assigned.get((home, away)) or []
        if not pks:
            unmatched.append(f"{away} @ {home}")
            continue
        game_pk = pks.pop(0)
        # Non-closing captures store pregame lines only: once a game starts,
        # ESPN swaps in live odds, and an in-game line is not a pregame
        # benchmark (the reader-side [0.20, 0.85] plausibility guard can't
        # catch all of it). The pk is popped above regardless, so the
        # doubleheader zip stays aligned when game 1 is skipped.
        if not closing and row.get("state") not in (None, "pre"):
            started += 1
            continue
        records.append({
            "game_pk": game_pk, "book": row["book"], "is_closing": closing,
            "ml_home": row["ml_home"], "ml_away": row["ml_away"],
            "runline_home": row["runline_home"],
            "runline_home_price": row["runline_home_price"],
            "runline_away_price": row["runline_away_price"],
            "total": row["total"], "over_price": row["over_price"],
            "under_price": row["under_price"], "source": "espn_daily",
        })
    if unmatched:
        log.warning("%s: %d ESPN events unmatched: %s", date, len(unmatched), unmatched)
    if started:
        log.info("%s: skipped %d started/finished games (pregame lines only)", date, started)
    if records:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO odds_lines
                    (game_pk, book, is_closing, ml_home, ml_away, runline_home,
                     runline_home_price, runline_away_price, total, over_price,
                     under_price, source)
                VALUES (:game_pk, :book, :is_closing, :ml_home, :ml_away, :runline_home,
                        :runline_home_price, :runline_away_price, :total, :over_price,
                        :under_price, :source)
            """), records)
    log.info("%s: stored %d lines (closing=%s)", date, len(records), closing)
    return len(records)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True)
    ap.add_argument("--closing", action="store_true")
    args = ap.parse_args()
    capture(args.date, closing=args.closing)


if __name__ == "__main__":
    main()
