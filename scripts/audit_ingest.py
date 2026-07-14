"""Phase 1 exit-criteria audit: row counts and sanity ratios per season.

Checks (per docs/PROJECT_PLAN.md Phase 1):
  - ledger status breakdown per source
  - games per season/type vs expectations (~2,430 regular-season games)
  - per-game averages: batter lines (~22-28), plays (~75-85), lineups (= 18)
  - statcast pitches per season (~700-750k) and days missing vs game dates

Usage: python scripts/audit_ingest.py
"""

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402


def main() -> None:
    engine = get_engine()
    with engine.connect() as conn:
        print("=== ingest_ledger ===")
        for source, status, n in conn.execute(text(
            "SELECT source, status, count(*) FROM ingest_ledger GROUP BY 1, 2 ORDER BY 1, 2"
        )):
            print(f"  {source:15s} {status:18s} {n}")

        print("\n=== games by season/type ===")
        for season, gtype, n in conn.execute(text(
            "SELECT season, game_type, count(*) FROM games GROUP BY 1, 2 ORDER BY 1, 2"
        )):
            print(f"  {season} {gtype}: {n}")

        print("\n=== per-game averages (imported games) ===")
        row = conn.execute(text("""
            SELECT
              (SELECT count(*) FROM games WHERE imported_at IS NOT NULL)      AS games,
              (SELECT count(*) FROM lineups)::float
                / NULLIF((SELECT count(*) FROM games WHERE imported_at IS NOT NULL), 0) AS lineups_pg,
              (SELECT count(*) FROM batter_game_lines)::float
                / NULLIF((SELECT count(*) FROM games WHERE imported_at IS NOT NULL), 0) AS batters_pg,
              (SELECT count(*) FROM pitcher_game_lines)::float
                / NULLIF((SELECT count(*) FROM games WHERE imported_at IS NOT NULL), 0) AS pitchers_pg,
              (SELECT count(*) FROM plays)::float
                / NULLIF((SELECT count(*) FROM games WHERE imported_at IS NOT NULL), 0) AS plays_pg
        """)).one()
        print(f"  imported games: {row.games}")
        print(f"  lineups/game:   {row.lineups_pg:.1f}  (expect 18.0)" if row.lineups_pg else "  no data")
        if row.batters_pg:
            print(f"  batters/game:   {row.batters_pg:.1f}  (expect ~22-28)")
            print(f"  pitchers/game:  {row.pitchers_pg:.1f}  (expect ~8-12)")
            print(f"  plays/game:     {row.plays_pg:.1f}  (expect ~75-85)")

        print("\n=== score integrity (plays vs games) ===")
        bad = conn.execute(text("""
            SELECT count(*) FROM games g
            JOIN (SELECT game_pk, max(home_score_post) AS h, max(away_score_post) AS a
                  FROM plays GROUP BY game_pk) p USING (game_pk)
            WHERE g.is_final AND (g.home_score <> p.h OR g.away_score <> p.a)
        """)).scalar_one()
        print(f"  final games where max play score != final score: {bad} (expect 0)")

        print("\n=== statcast by season ===")
        for season, pitches, days in conn.execute(text("""
            SELECT extract(year FROM game_date)::int, count(*), count(DISTINCT game_date)
            FROM statcast_pitches GROUP BY 1 ORDER BY 1
        """)):
            print(f"  {season}: {pitches} pitches over {days} days (expect ~700-750k/season)")

        print("\n=== statcast days missing (game dates with no pitches) ===")
        missing = conn.execute(text("""
            SELECT count(DISTINCT g.game_date) FROM games g
            WHERE g.imported_at IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM statcast_pitches s WHERE s.game_date = g.game_date)
        """)).scalar_one()
        print(f"  {missing} (expect 0 when backfill is complete)")

        print("\n=== reference ===")
        for table in ("teams", "venues", "players", "players_xref"):
            n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            print(f"  {table}: {n}")


if __name__ == "__main__":
    main()
