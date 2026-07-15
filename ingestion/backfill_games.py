"""Game backfill: schedule -> ledger -> live feed -> S3 raw archive -> Postgres.

Resumable and idempotent: seeding registers Final games in the ledger; the run
loop only processes pending/error entries, archives raw JSON before parsing,
and loads each game in a single transaction (delete-then-insert for child
tables, upsert for games/players).

Usage:
    python -m ingestion.backfill_games --season 2024              # seed + run
    python -m ingestion.backfill_games --start 2024-06-01 --end 2024-06-03 --limit 10
    python -m ingestion.backfill_games                            # run pending only
"""

import argparse
import logging
import time

import requests
from sqlalchemy import text

from core.db import get_engine
from ingestion import ledger, raw_archive, statsapi_client
from ingestion.parsers import feed_live

log = logging.getLogger("backfill_games")

SOURCE = "statsapi_game"

_UPSERT_PLAYER = text("""
    INSERT INTO players (player_id, full_name, birth_date, bats, throws,
                         primary_position, mlb_debut, height, weight, active)
    VALUES (:player_id, :full_name, :birth_date, :bats, :throws,
            :primary_position, :mlb_debut, :height, :weight, :active)
    ON CONFLICT (player_id) DO UPDATE SET
        full_name = EXCLUDED.full_name, bats = EXCLUDED.bats,
        throws = EXCLUDED.throws, primary_position = EXCLUDED.primary_position,
        mlb_debut = EXCLUDED.mlb_debut, height = EXCLUDED.height,
        weight = EXCLUDED.weight, active = EXCLUDED.active, updated_at = now()
""")

_UPSERT_GAME = text("""
    INSERT INTO games (game_pk, season, game_type, game_date, first_pitch_utc,
                       status, home_team_id, away_team_id, venue_id, day_night,
                       doubleheader, game_number, scheduled_innings, innings_played,
                       home_score, away_score, weather_condition, temp_f,
                       wind_speed_mph, wind_dir, attendance, duration_minutes,
                       hp_umpire_id, hp_umpire_name, is_final, imported_at)
    VALUES (:game_pk, :season, :game_type, :game_date, :first_pitch_utc,
            :status, :home_team_id, :away_team_id, :venue_id, :day_night,
            :doubleheader, :game_number, :scheduled_innings, :innings_played,
            :home_score, :away_score, :weather_condition, :temp_f,
            :wind_speed_mph, :wind_dir, :attendance, :duration_minutes,
            :hp_umpire_id, :hp_umpire_name, :is_final, now())
    ON CONFLICT (game_pk) DO UPDATE SET
        season = EXCLUDED.season, game_type = EXCLUDED.game_type,
        game_date = EXCLUDED.game_date, first_pitch_utc = EXCLUDED.first_pitch_utc,
        status = EXCLUDED.status, home_team_id = EXCLUDED.home_team_id,
        away_team_id = EXCLUDED.away_team_id, venue_id = EXCLUDED.venue_id,
        day_night = EXCLUDED.day_night, doubleheader = EXCLUDED.doubleheader,
        game_number = EXCLUDED.game_number,
        scheduled_innings = EXCLUDED.scheduled_innings,
        innings_played = EXCLUDED.innings_played,
        home_score = EXCLUDED.home_score, away_score = EXCLUDED.away_score,
        weather_condition = EXCLUDED.weather_condition, temp_f = EXCLUDED.temp_f,
        wind_speed_mph = EXCLUDED.wind_speed_mph, wind_dir = EXCLUDED.wind_dir,
        attendance = EXCLUDED.attendance,
        duration_minutes = EXCLUDED.duration_minutes,
        hp_umpire_id = EXCLUDED.hp_umpire_id,
        hp_umpire_name = EXCLUDED.hp_umpire_name,
        is_final = EXCLUDED.is_final, imported_at = now()
""")

_INSERTS = {
    "lineups": text("""
        INSERT INTO lineups (game_pk, player_id, team_id, batting_order, start_position)
        VALUES (:game_pk, :player_id, :team_id, :batting_order, :start_position)
    """),
    "batter_lines": text("""
        INSERT INTO batter_game_lines (game_pk, player_id, team_id, is_home, is_starter,
            batting_order_slot, pa, ab, r, h, doubles, triples, hr, tb, rbi, bb, so,
            hbp, sb, cs, sf, sac, lob)
        VALUES (:game_pk, :player_id, :team_id, :is_home, :is_starter,
            :batting_order_slot, :pa, :ab, :r, :h, :doubles, :triples, :hr, :tb, :rbi,
            :bb, :so, :hbp, :sb, :cs, :sf, :sac, :lob)
    """),
    "pitcher_lines": text("""
        INSERT INTO pitcher_game_lines (game_pk, player_id, team_id, is_home, is_starter,
            outs, batters_faced, h, r, er, bb, so, hr, hbp, pitches, strikes)
        VALUES (:game_pk, :player_id, :team_id, :is_home, :is_starter,
            :outs, :batters_faced, :h, :r, :er, :bb, :so, :hr, :hbp, :pitches, :strikes)
    """),
    "plays": text("""
        INSERT INTO plays (game_pk, at_bat_index, inning, is_top, batter_id, pitcher_id,
            bat_side, pitch_hand, event, event_type, description, rbi, outs_post,
            home_score_post, away_score_post)
        VALUES (:game_pk, :at_bat_index, :inning, :is_top, :batter_id, :pitcher_id,
            :bat_side, :pitch_hand, :event, :event_type, :description, :rbi, :outs_post,
            :home_score_post, :away_score_post)
    """),
}

_CHILD_TABLES = {
    "lineups": "lineups",
    "batter_lines": "batter_game_lines",
    "pitcher_lines": "pitcher_game_lines",
    "plays": "plays",
}


def _load_game(conn, parsed: dict) -> None:
    game_pk = parsed["game"]["game_pk"]
    if parsed["players"]:
        # Stable lock-acquisition order: concurrent workers upserting
        # overlapping player sets deadlock if their row order differs.
        conn.execute(_UPSERT_PLAYER, sorted(parsed["players"], key=lambda p: p["player_id"] or 0))
    conn.execute(_UPSERT_GAME, parsed["game"])
    for key, table in _CHILD_TABLES.items():
        conn.execute(text(f"DELETE FROM {table} WHERE game_pk = :pk"), {"pk": game_pk})
        if parsed[key]:
            conn.execute(_INSERTS[key], parsed[key])
    conn.execute(
        text("DELETE FROM probable_pitchers WHERE game_pk = :pk AND source = 'backfill'"),
        {"pk": game_pk},
    )
    conn.execute(
        text("""
            INSERT INTO probable_pitchers (game_pk, source, home_pitcher_id, away_pitcher_id)
            VALUES (:game_pk, 'backfill', :home_pitcher_id, :away_pitcher_id)
        """),
        parsed["probable"],
    )


def _month_chunks(start: str, end: str):
    """Yield (chunk_start, chunk_end) ISO date pairs, ~1 month each."""
    from datetime import date, timedelta

    cur = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while cur <= stop:
        nxt = min((cur.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1), stop)
        yield cur.isoformat(), nxt.isoformat()
        cur = nxt + timedelta(days=1)


def seed_range(start: str, end: str) -> None:
    """Register all Final games (and their dates, for Statcast) in the ledger."""
    finals = []
    for chunk_start, chunk_end in _month_chunks(start, end):
        games = statsapi_client.schedule(chunk_start, chunk_end)
        finals += [g for g in games if g.get("status", {}).get("codedGameState") == "F"]
        log.info("schedule %s..%s: %d final games", chunk_start, chunk_end, len(finals))
    ledger.seed(SOURCE, sorted({g["gamePk"] for g in finals}))
    ledger.seed("statcast_day", sorted({g["officialDate"] for g in finals}))
    log.info("ledger: %s | statcast_day: %s", ledger.counts(SOURCE), ledger.counts("statcast_day"))


def _process_game(key: str) -> bool:
    """Fetch, archive, parse, load one game. Returns True on success.

    The outer except exists because the inner handlers write to the ledger —
    if the DB itself is unreachable (network blip), that write raises too.
    In that case we swallow and leave the ledger untouched: the item stays
    pending with no attempt burned, and the next run picks it up.
    """
    game_pk = int(key)
    try:
        try:
            feed = statsapi_client.live_feed(game_pk)
            parsed = feed_live.parse(feed)
            season = parsed["game"]["season"]
            s3_key = raw_archive.put_json_gz(
                f"statsapi/feed_live/{season}/{game_pk}.json.gz", feed)
            with get_engine().begin() as conn:
                _load_game(conn, parsed)
            ledger.mark(SOURCE, key, "imported", s3_key=s3_key)
            return True
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                ledger.mark(SOURCE, key, "permanent_missing", detail="404 from feed")
            else:
                ledger.mark(SOURCE, key, "error", detail=str(exc))
            log.warning("game %s failed: %s", key, exc)
            return False
        except Exception as exc:  # keep the backfill alive; ledger records it
            ledger.mark(SOURCE, key, "error", detail=str(exc))
            log.warning("game %s failed: %s", key, exc)
            return False
    except Exception as exc:
        log.warning("game %s: unreachable infrastructure, left pending: %s", key, exc)
        return False


def run(limit: int | None = None, sleep: float = 0.2, workers: int = 1) -> None:
    """Process pending games; `workers` threads amortize the RDS/S3 round-trip
    latency (the DB is in us-east-1, so per-statement RTT dominates a single
    sequential loop)."""
    from concurrent.futures import ThreadPoolExecutor

    keys = ledger.pending(SOURCE, limit)
    log.info("processing %d pending games with %d workers", len(keys), workers)
    done = errors = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ok in pool.map(_process_game, keys):
            done += ok
            errors += not ok
            if (done + errors) % 50 == 0:
                rate = (done + errors) / max(time.monotonic() - started, 1)
                remaining = len(keys) - done - errors
                log.info("progress: %d ok, %d errors, %.2f games/s, ~%d min left",
                         done, errors, rate, int(remaining / max(rate, 0.01) / 60))
            time.sleep(sleep)
    log.info("finished: %d imported, %d errors | ledger now %s", done, errors, ledger.counts(SOURCE))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, help="seed a whole season (Mar 1 - Nov 30)")
    ap.add_argument("--start", help="seed range start (YYYY-MM-DD)")
    ap.add_argument("--end", help="seed range end (YYYY-MM-DD)")
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sleep", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.season:
        seed_range(f"{args.season}-03-01", f"{args.season}-11-30")
    elif args.start and args.end:
        seed_range(args.start, args.end)
    if not args.seed_only:
        run(limit=args.limit, sleep=args.sleep, workers=args.workers)


if __name__ == "__main__":
    main()
