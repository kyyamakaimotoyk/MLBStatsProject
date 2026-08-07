"""Refresh the serving rollups: pred_grades and batter_grades_daily.

These tables answer "how has the model actually done", which used to be
recomputed from base tables on every page view. The expensive part is not the
arithmetic — it is resolving which of ~81 append-only prediction rows per game
is the published one. That resolution is stable once a game is final, so it
belongs here, in the pipeline that already runs whenever the inputs change.

Both tables are derived and disposable. `--full` rebuilds from scratch.

When to run what:
  * The daily pipeline calls refresh() with the default window after writing
    predictions, and again on --scores-only ticks (a final landing is what
    turns a prediction into a grade).
  * A walk-forward backfill can change which row wins for games that have no
    daily_v1 prediction, and it rewrites history rather than the recent
    window. Run `python -m orchestration.grades --full` after one.

Usage:
    python -m orchestration.grades              # default window (30 days)
    python -m orchestration.grades --days 90
    python -m orchestration.grades --full       # rebuild all history
"""

import argparse
import logging

import pandas as pd
from sqlalchemy import text

from core.db import get_engine
from core.market import with_market

log = logging.getLogger(__name__)

PRIMARY = "lgbm_runs"

# Finals arrive on the even-hour score refreshes and predictions upsert at
# 18/21/23, so a game's grade can still move a day or two after game_date
# (suspended games and doubleheaders are the long tail). 30 days is far past
# that and still only ~400 rows.
DEFAULT_DAYS = 30

ET_TODAY = "(now() AT TIME ZONE 'America/New_York')::date"

# The published prediction for a game: prefer the daily run, then the most
# recent write. Identical ordering to what the API used to do inline — if this
# ever changes, pred_grades must be rebuilt with --full.
_GAME_ROWS = f"""
    SELECT g.game_pk, g.game_date, p.model_type, p.model_version,
           p.p_home, p.pred_margin, p.pred_total,
           g.home_score - g.away_score AS margin,
           g.home_score + g.away_score AS total,
           (g.home_score > g.away_score) AS home_won,
           (CASE WHEN p.p_home >= 0.5 THEN g.home_score > g.away_score
                 ELSE g.home_score < g.away_score END) AS correct,
           abs(g.home_score - g.away_score - p.pred_margin) AS margin_err,
           abs(g.home_score + g.away_score - p.pred_total) AS total_err,
           c.ml_home AS close_ml_home, c.ml_away AS close_ml_away,
           c.total AS close_total,
           op.ml_home AS open_ml_home, op.ml_away AS open_ml_away,
           op.total AS open_total
    FROM games g
    JOIN LATERAL (
        SELECT * FROM model_predictions p
        WHERE p.game_pk = g.game_pk AND p.model_type = :m
        ORDER BY (p.model_version = 'daily_v1') DESC, p.created_at DESC
        LIMIT 1
    ) p ON TRUE
    LEFT JOIN LATERAL (
        SELECT * FROM odds_lines o
        WHERE o.game_pk = g.game_pk AND o.is_closing
          AND o.ml_home IS NOT NULL AND o.ml_away IS NOT NULL
        ORDER BY o.captured_at DESC LIMIT 1
    ) c ON TRUE
    LEFT JOIN LATERAL (
        SELECT * FROM odds_lines o
        WHERE o.game_pk = g.game_pk AND NOT o.is_closing
          AND o.ml_home IS NOT NULL AND o.ml_away IS NOT NULL
        ORDER BY o.captured_at DESC LIMIT 1
    ) op ON TRUE
    WHERE g.is_final AND g.game_date >= :since
"""

_UPSERT_GAME = """
    INSERT INTO pred_grades (
        game_pk, game_date, model_type, model_version, p_home, pred_margin,
        pred_total, margin, total, home_won, correct, margin_err, total_err,
        market_p_home, market_total, refreshed_at)
    VALUES (
        :game_pk, :game_date, :model_type, :model_version, :p_home,
        :pred_margin, :pred_total, :margin, :total, :home_won, :correct,
        :margin_err, :total_err, :market_p_home, :market_total, now())
    ON CONFLICT (game_pk) DO UPDATE SET
        game_date = EXCLUDED.game_date,
        model_type = EXCLUDED.model_type,
        model_version = EXCLUDED.model_version,
        p_home = EXCLUDED.p_home,
        pred_margin = EXCLUDED.pred_margin,
        pred_total = EXCLUDED.pred_total,
        margin = EXCLUDED.margin,
        total = EXCLUDED.total,
        home_won = EXCLUDED.home_won,
        correct = EXCLUDED.correct,
        margin_err = EXCLUDED.margin_err,
        total_err = EXCLUDED.total_err,
        market_p_home = EXCLUDED.market_p_home,
        market_total = EXCLUDED.market_total,
        refreshed_at = now()
"""

# Pure SQL: no per-row resolution leaks out to Python here. hr_rank is ranked
# WITHIN a game_date, so restricting the window drops whole days rather than
# reshuffling the ones that remain — which is what makes an incremental
# refresh give the same answer as a full rebuild.
_UPSERT_BATTER_DAYS = f"""
    INSERT INTO batter_grades_daily (
        game_date, n, model_correct, always_yes_correct, hr_base_hits,
        hr_watch_n, hr_watch_hits, refreshed_at)
    SELECT y.game_date, count(*),
           count(*) FILTER (WHERE (y.p_hit >= 0.5) = (y.h >= 1)),
           count(*) FILTER (WHERE y.h >= 1),
           count(*) FILTER (WHERE y.hr >= 1),
           count(*) FILTER (WHERE y.hr_rank <= 5),
           count(*) FILTER (WHERE y.hr_rank <= 5 AND y.hr >= 1),
           now()
    FROM (
        SELECT x.*, ROW_NUMBER() OVER (PARTITION BY x.game_date
                                       ORDER BY x.p_hr DESC NULLS LAST) AS hr_rank
        FROM (
            SELECT DISTINCT ON (bp.game_pk, bp.player_id)
                   g.game_date, bp.p_hit, bp.p_hr, bg.h, bg.hr
            FROM batter_game_lines bg
            JOIN games g ON g.game_pk = bg.game_pk AND g.is_final
            JOIN batter_predictions bp
              ON bp.game_pk = bg.game_pk AND bp.player_id = bg.player_id
            WHERE bg.h IS NOT NULL AND bp.p_hit IS NOT NULL
              AND g.game_date >= :since
            ORDER BY bp.game_pk, bp.player_id,
                     (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
        ) x
    ) y
    GROUP BY 1
    ON CONFLICT (game_date) DO UPDATE SET
        n = EXCLUDED.n,
        model_correct = EXCLUDED.model_correct,
        always_yes_correct = EXCLUDED.always_yes_correct,
        hr_base_hits = EXCLUDED.hr_base_hits,
        hr_watch_n = EXCLUDED.hr_watch_n,
        hr_watch_hits = EXCLUDED.hr_watch_hits,
        refreshed_at = now()
"""


def refresh(days: int = DEFAULT_DAYS, full: bool = False) -> dict[str, int]:
    """Rebuild the rollups for the trailing `days`, or all history if `full`.

    Deletes the window before reinserting so a game that stops qualifying —
    a final reverted to in-progress, a prediction withdrawn — leaves the
    rollup rather than lingering as a stale grade.
    """
    engine = get_engine()
    with engine.begin() as conn:
        since_sql = "DATE '1900-01-01'" if full else f"{ET_TODAY} - {int(days)}"
        since = conn.execute(text(f"SELECT {since_sql} AS d")).scalar()
        log.info("refreshing grade rollups from %s%s", since, " (full)" if full else "")

        raw = pd.read_sql(text(_GAME_ROWS), conn, params={"m": PRIMARY, "since": since})
        conn.execute(text("DELETE FROM pred_grades WHERE game_date >= :since"),
                     {"since": since})
        if not raw.empty:
            rows = with_market(raw)
            # NaN -> None so psycopg writes SQL NULL instead of the float nan,
            # which Postgres would happily store in a REAL column and then
            # serve to the site as a number.
            payload = rows.astype(object).where(rows.notna(), None).to_dict("records")
            conn.execute(text(_UPSERT_GAME), payload)

        conn.execute(text("DELETE FROM batter_grades_daily WHERE game_date >= :since"),
                     {"since": since})
        conn.execute(text(_UPSERT_BATTER_DAYS), {"since": since})

        counts = {
            "pred_grades": conn.execute(
                text("SELECT count(*) FROM pred_grades")).scalar(),
            "batter_grades_daily": conn.execute(
                text("SELECT count(*) FROM batter_grades_daily")).scalar(),
            "games_written": len(raw),
        }
    log.info("grade rollups: %s games in window, %s total, %s batter days",
             counts["games_written"], counts["pred_grades"],
             counts["batter_grades_daily"])
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"trailing window to rebuild (default {DEFAULT_DAYS})")
    ap.add_argument("--full", action="store_true",
                    help="rebuild all history; needed after a walk-forward backfill")
    args = ap.parse_args()
    counts = refresh(days=args.days, full=args.full)
    print(f"pred_grades={counts['pred_grades']:,}  "
          f"batter_grades_daily={counts['batter_grades_daily']:,}")


if __name__ == "__main__":
    main()
