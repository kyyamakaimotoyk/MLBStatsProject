"""Drift test for the serving rollups (pred_grades, batter_grades_daily).

The rollups exist so the public API never resolves "which of ~81 append-only
prediction rows is the published one" at request time. That trade is only safe
while the rollup still agrees with the base tables. Two ways it can rot:

  1. The resolution rule in orchestration/grades.py drifts from the one the
     rest of the system uses, or a backfill rewrites history the incremental
     window never revisits.
  2. An incremental refresh gives a different answer than a full rebuild —
     which would mean the numbers depend on when the pipeline happened to run.

This checks both against live data, so it needs the database.

Usage:
    python scripts/test_grade_rollups.py            # trailing 120 days
    python scripts/test_grade_rollups.py --days 400
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402
from core.market import with_market  # noqa: E402
from orchestration import grades  # noqa: E402

FAILURES: list[str] = []

# The grading computed straight from the base tables — deliberately written
# the long way, so this test fails if grades.py's resolution rule drifts.
TRUTH_GAMES = f"""
    SELECT g.game_pk, g.game_date,
           (CASE WHEN p.p_home >= 0.5 THEN g.home_score > g.away_score
                 ELSE g.home_score < g.away_score END) AS correct,
           abs(g.home_score - g.away_score - p.pred_margin) AS margin_err,
           p.p_home,
           c.ml_home AS close_ml_home, c.ml_away AS close_ml_away,
           c.total AS close_total,
           op.ml_home AS open_ml_home, op.ml_away AS open_ml_away,
           op.total AS open_total
    FROM games g
    JOIN LATERAL (
        SELECT * FROM model_predictions p
        WHERE p.game_pk = g.game_pk AND p.model_type = 'lgbm_runs'
        ORDER BY (p.model_version = 'daily_v1') DESC, p.created_at DESC LIMIT 1
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
    WHERE g.is_final AND g.game_date >= {grades.ET_TODAY} - :days
"""

TRUTH_BATTER_DAYS = f"""
    SELECT y.game_date, count(*) AS n,
           count(*) FILTER (WHERE (y.p_hit >= 0.5) = (y.h >= 1)) AS model_correct,
           count(*) FILTER (WHERE y.hr_rank <= 5 AND y.hr >= 1) AS hr_watch_hits
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
              AND g.game_date >= {grades.ET_TODAY} - :days
            ORDER BY bp.game_pk, bp.player_id,
                     (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
        ) x
    ) y
    GROUP BY 1
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'  -- ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)


def test_matches_base_tables(days: int) -> None:
    print(f"rollups agree with the base tables (last {days} days)")
    engine = get_engine()
    truth = with_market(pd.read_sql(text(TRUTH_GAMES), engine, params={"days": days}))
    stored = pd.read_sql(text(f"""
        SELECT game_pk, game_date, correct, margin_err, p_home, market_p_home
        FROM pred_grades WHERE game_date >= {grades.ET_TODAY} - :days
    """), engine, params={"days": days})

    check("same set of graded games",
          set(truth["game_pk"]) == set(stored["game_pk"]),
          f"base={len(truth)} rollup={len(stored)}")

    merged = truth.merge(stored, on="game_pk", suffixes=("_base", "_roll"))
    for col in ("correct", "margin_err", "p_home", "market_p_home"):
        b, r = merged[f"{col}_base"], merged[f"{col}_roll"]
        if col in ("correct",):
            bad = int((b.fillna(-1) != r.fillna(-1)).sum())
        else:
            # both sides NaN counts as agreement
            bad = int(((b - r).abs() > 1e-6).fillna(b.notna() != r.notna()).sum())
        check(f"{col} matches for every game", bad == 0, f"{bad} mismatched")

    tb = pd.read_sql(text(TRUTH_BATTER_DAYS), engine, params={"days": days})
    sb = pd.read_sql(text(f"""
        SELECT game_date, n, model_correct, hr_watch_hits
        FROM batter_grades_daily WHERE game_date >= {grades.ET_TODAY} - :days
    """), engine, params={"days": days})
    m = tb.merge(sb, on="game_date", suffixes=("_base", "_roll"))
    check("same set of graded days", len(tb) == len(sb) == len(m),
          f"base={len(tb)} rollup={len(sb)} joined={len(m)}")
    for col in ("n", "model_correct", "hr_watch_hits"):
        bad = int((m[f"{col}_base"] != m[f"{col}_roll"]).sum())
        check(f"batter {col} matches for every day", bad == 0, f"{bad} mismatched")


def test_incremental_equals_full(days: int) -> None:
    """An incremental refresh must not change what a full rebuild produced —
    otherwise the site's numbers depend on pipeline timing."""
    print(f"incremental refresh reproduces the full rebuild (last {days} days)")
    engine = get_engine()
    cols = ("SELECT game_pk, correct, margin_err, market_p_home FROM pred_grades "
            f"WHERE game_date >= {grades.ET_TODAY} - :days ORDER BY game_pk")
    before = pd.read_sql(text(cols), engine, params={"days": days})
    bcols = ("SELECT game_date, n, model_correct, hr_watch_hits FROM batter_grades_daily "
             f"WHERE game_date >= {grades.ET_TODAY} - :days ORDER BY game_date")
    bbefore = pd.read_sql(text(bcols), engine, params={"days": days})

    grades.refresh(days=days)

    after = pd.read_sql(text(cols), engine, params={"days": days})
    bafter = pd.read_sql(text(bcols), engine, params={"days": days})
    check("pred_grades unchanged by a re-refresh", before.equals(after),
          f"{len(before)} rows")
    check("batter_grades_daily unchanged by a re-refresh", bbefore.equals(bafter),
          f"{len(bbefore)} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()

    test_matches_base_tables(args.days)
    test_incremental_equals_full(args.days)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        print("If a walk-forward backfill just ran, rebuild with "
              "`python -m orchestration.grades --full` and re-test.")
        sys.exit(1)
    print("PASS: rollups agree with the base tables and are refresh-stable")


if __name__ == "__main__":
    main()
