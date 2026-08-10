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

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402
from core.market import no_vig, no_vig_sql, with_market  # noqa: E402
from core.tiers import STRONG_MIN  # noqa: E402
from orchestration import grades  # noqa: E402

FAILURES: list[str] = []

# The grading computed straight from the base tables — deliberately written
# the long way, so this test fails if grades.py's resolution rule drifts.
# The tier truth is spelled out independently too: served (daily_v1) rows tier
# on their own calibrated p_home; historical rows tier on the E11c archive's
# calibrated probability taken on the published pick's side.
TRUTH_GAMES = f"""
    SELECT g.game_pk, g.game_date,
           (CASE WHEN p.p_home >= 0.5 THEN g.home_score > g.away_score
                 ELSE g.home_score < g.away_score END) AS correct,
           (CASE WHEN (
               CASE
                   WHEN p.model_version = 'daily_v1' OR cal.cal_p IS NULL THEN
                       CASE WHEN p.p_home >= 0.5 THEN p.p_home
                            ELSE 1 - p.p_home END
                   WHEN p.p_home >= 0.5 THEN cal.cal_p
                   ELSE 1 - cal.cal_p
               END) >= {STRONG_MIN}
            THEN 'strong' ELSE 'lean' END) AS tier,
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
        SELECT cp.p_home AS cal_p FROM model_predictions cp
        WHERE cp.game_pk = g.game_pk
          AND cp.model_type = '{grades.TIER_CAL_TYPE}'
          AND cp.model_version = '{grades.TIER_CAL_VERSION}'
        LIMIT 1
    ) cal ON TRUE
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
        SELECT game_pk, game_date, correct, tier, margin_err, p_home,
               market_p_home
        FROM pred_grades WHERE game_date >= {grades.ET_TODAY} - :days
    """), engine, params={"days": days})

    check("same set of graded games",
          set(truth["game_pk"]) == set(stored["game_pk"]),
          f"base={len(truth)} rollup={len(stored)}")

    merged = truth.merge(stored, on="game_pk", suffixes=("_base", "_roll"))
    for col in ("correct", "tier", "margin_err", "p_home", "market_p_home"):
        b, r = merged[f"{col}_base"], merged[f"{col}_roll"]
        if col in ("correct", "tier"):
            bad = int((b.fillna(-1) != r.fillna(-1)).sum())
        else:
            # Relative, not absolute. margin_err and p_home are REAL (float4),
            # so a value round-tripped through Python can land one ULP away —
            # ~1.9e-6 at a margin error of 20. A flat 1e-6 tolerance asserts
            # more precision than the column can physically hold and flags
            # that as a failure. rtol catches a real drift (a changed
            # prediction moves these by ~1e-1) while ignoring representation
            # noise. equal_nan: a game with no line has NaN on both sides.
            bad = int((~np.isclose(b.astype(float), r.astype(float),
                                   rtol=1e-6, atol=1e-6, equal_nan=True)).sum())
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


def test_no_vig_sql_matches_python() -> None:
    """core/market.py deliberately expresses the no-vig conversion twice —
    once in Python for row-level work, once in SQL so the perf rollup can
    aggregate without dragging ~660k rows into pandas. This is the test that
    licenses that duplication."""
    print("no_vig SQL and Python agree")
    engine = get_engine()
    rows = pd.read_sql(text(f"""
        SELECT ml_home, ml_away,
               {no_vig_sql('ml_home', 'ml_away')} AS sql_p
        FROM odds_lines
        WHERE ml_home IS NOT NULL AND ml_away IS NOT NULL
    """), engine)
    # no_vig returns a numpy array, not a Series — build one so the band
    # comparison below uses the same inclusive semantics as pandas .between().
    py = pd.Series(no_vig(rows["ml_home"], rows["ml_away"]), index=rows.index)
    worst = float((py - rows["sql_p"]).abs().max())
    check("identical on every captured line", worst < 1e-12,
          f"{len(rows):,} lines, worst absolute difference {worst:.1e}")
    # The band decides which rows count toward the market columns, so a
    # disagreement exactly at the edge would silently change the population.
    band_py = py.between(0.20, 0.85)
    band_sql = rows["sql_p"].between(0.20, 0.85)
    check("same rows fall inside the [0.20, 0.85] plausibility band",
          int((band_py != band_sql).sum()) == 0,
          f"{int(band_py.sum()):,} in band")


def test_perf_rollups_match_base_tables(days: int) -> None:
    print(f"perf rollups agree with the base tables (last {days} days)")
    engine = get_engine()

    truth = pd.read_sql(text(f"""
        SELECT p.model_type, p.model_version, count(*) AS n,
               avg(((p.p_home >= 0.5) = (g.home_score > g.away_score))::int) AS win_acc,
               avg(abs(g.home_score - g.away_score - p.pred_margin)) AS margin_mae
        FROM model_predictions p JOIN games g USING (game_pk)
        WHERE g.is_final AND g.game_date >= {grades.ET_TODAY} - :days
        GROUP BY 1, 2
    """), engine, params={"days": days})
    roll = pd.read_sql(text(f"""
        SELECT model_type, model_version, sum(n) AS n,
               sum(win_correct)::double precision / nullif(sum(win_n), 0) AS win_acc,
               sum(margin_err_sum) / nullif(sum(margin_n), 0) AS margin_mae
        FROM model_perf_daily
        WHERE game_date >= {grades.ET_TODAY} - :days
        GROUP BY 1, 2
    """), engine, params={"days": days})
    m = truth.merge(roll, on=["model_type", "model_version"], suffixes=("_b", "_r"))
    check("same set of model variants",
          len(truth) == len(roll) == len(m),
          f"base={len(truth)} rollup={len(roll)}")
    check("n matches for every variant", int((m["n_b"] != m["n_r"]).sum()) == 0)
    for col in ("win_acc", "margin_mae"):
        bad = int((~np.isclose(m[f"{col}_b"].astype(float), m[f"{col}_r"].astype(float),
                               rtol=1e-9, atol=1e-12, equal_nan=True)).sum())
        check(f"{col} matches for every variant", bad == 0, f"{bad} mismatched")

    tb = pd.read_sql(text(f"""
        SELECT b.model_version, count(*) AS n,
               avg(power(b.p_hit - (bg.h >= 1)::int, 2)) AS brier_p_hit
        FROM batter_predictions b
        JOIN batter_game_lines bg USING (game_pk, player_id)
        JOIN games g ON g.game_pk = b.game_pk
        WHERE g.is_final AND g.game_date >= {grades.ET_TODAY} - :days
        GROUP BY 1
    """), engine, params={"days": days})
    rb = pd.read_sql(text(f"""
        SELECT model_version, sum(n) AS n,
               sum(brier_hit_sum) / nullif(sum(brier_hit_n), 0) AS brier_p_hit
        FROM batter_perf_daily
        WHERE game_date >= {grades.ET_TODAY} - :days
        GROUP BY 1
    """), engine, params={"days": days})
    mb = tb.merge(rb, on="model_version", suffixes=("_b", "_r"))
    check("same set of batter model versions",
          len(tb) == len(rb) == len(mb), f"base={len(tb)} rollup={len(rb)}")
    check("batter n matches", int((mb["n_b"] != mb["n_r"]).sum()) == 0)
    bad = int((~np.isclose(mb["brier_p_hit_b"].astype(float),
                           mb["brier_p_hit_r"].astype(float),
                           rtol=1e-9, atol=1e-12, equal_nan=True)).sum())
    check("brier_p_hit matches for every version", bad == 0, f"{bad} mismatched")


def _frames_match(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    """Compare two reads of the same rollup.

    Not .equals(). The stored float SUMS are produced by Postgres aggregates,
    and parallel aggregation does not fix the summation order — float addition
    is not associative, so two identical refreshes can land ~1e-15 apart. That
    is reproducibility to float precision, which is the strongest guarantee
    available here; requiring bit equality would fail on nothing but worker
    scheduling. Integer columns still have to match exactly, because a real
    drift shows up there first.
    """
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        return False, f"shape {a.shape} vs {b.shape}"
    for col in a.columns:
        x, y = a[col], b[col]
        if pd.api.types.is_float_dtype(x) or pd.api.types.is_float_dtype(y):
            bad = int((~np.isclose(x.astype(float), y.astype(float),
                                   rtol=1e-12, atol=0, equal_nan=True)).sum())
            if bad:
                return False, f"{col}: {bad} value(s) beyond 1e-12 relative"
        elif not x.equals(y):
            return False, f"{col}: {int((x != y).sum())} value(s) differ"
    return True, f"{len(a)} rows"


def test_incremental_equals_full(days: int) -> None:
    """An incremental refresh must not change what a full rebuild produced —
    otherwise the site's numbers depend on pipeline timing."""
    print(f"incremental refresh reproduces the full rebuild (last {days} days)")
    engine = get_engine()
    # Every ORDER BY here must be the table's full primary key. Sorting on a
    # prefix leaves ties in undefined order, and the comparison then fails on
    # row shuffling rather than on any change in the data.
    queries = {
        "pred_grades":
            "SELECT game_pk, correct, tier, margin_err, market_p_home "
            "FROM pred_grades "
            f"WHERE game_date >= {grades.ET_TODAY} - :days ORDER BY game_pk",
        "batter_grades_daily":
            "SELECT game_date, n, model_correct, hr_watch_hits "
            f"FROM batter_grades_daily WHERE game_date >= {grades.ET_TODAY} - :days "
            "ORDER BY game_date",
        "model_perf_daily":
            "SELECT game_date, model_type, model_version, n, win_correct, mkt_n, "
            "margin_err_sum FROM model_perf_daily "
            f"WHERE game_date >= {grades.ET_TODAY} - :days "
            "ORDER BY game_date, model_type, model_version",
        "batter_perf_daily":
            "SELECT game_date, model_version, n, brier_hit_sum FROM batter_perf_daily "
            f"WHERE game_date >= {grades.ET_TODAY} - :days "
            "ORDER BY game_date, model_version",
    }
    before = {t: pd.read_sql(text(q), engine, params={"days": days})
              for t, q in queries.items()}

    grades.refresh(days=days)

    for table, q in queries.items():
        after = pd.read_sql(text(q), engine, params={"days": days})
        ok, detail = _frames_match(before[table], after)
        check(f"{table} unchanged by a re-refresh", ok, detail)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()

    test_no_vig_sql_matches_python()
    test_matches_base_tables(args.days)
    test_perf_rollups_match_base_tables(args.days)
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
