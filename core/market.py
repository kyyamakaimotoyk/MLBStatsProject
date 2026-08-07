"""The betting market's pregame view, derived from raw odds captures.

Single source of truth for the no-vig conversion and the plausibility guard.
This lives in core/ because two images need it: the API serves market columns
alongside model predictions, and the pipeline pre-resolves the same columns
into pred_grades. Duplicating the formula is how the two silently drift apart.

Odds are a benchmark, never a model feature (hard rule). Nothing here may be
imported by a feature builder.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Pregame MLB win probabilities live in roughly this band. A capture outside
# it means the line was contaminated in-game, so it is not usable as a pregame
# benchmark. Same guard as scripts/benchmark_odds.py.
PLAUSIBLE_LO, PLAUSIBLE_HI = 0.20, 0.85

MARKET_SOURCE_COLS = [
    "close_ml_home", "close_ml_away", "close_total",
    "open_ml_home", "open_ml_away", "open_total",
]


def no_vig(ml_home, ml_away):
    """American moneylines -> the home team's vig-free win probability."""
    def implied(a):
        a = a.astype(float)
        return np.where(a < 0, -a / (-a + 100.0), 100.0 / (a + 100.0))
    ph, pa = implied(ml_home), implied(ml_away)
    return ph / (ph + pa)


def no_vig_sql(ml_home: str, ml_away: str) -> str:
    """The same conversion as no_vig(), as a SQL expression.

    Exists so aggregate rollups can do the arithmetic in Postgres instead of
    dragging ~660k rows into pandas to divide two numbers. This is the one
    place the formula is allowed to appear twice, and
    scripts/test_grade_rollups.py asserts the two agree on live data — if you
    edit one, edit both and run that test.
    """
    def implied(a: str) -> str:
        return (f"(CASE WHEN {a} < 0 "
                f"THEN -({a})::double precision / (-({a})::double precision + 100.0) "
                f"ELSE 100.0 / (({a})::double precision + 100.0) END)")
    ph, pa = implied(ml_home), implied(ml_away)
    return f"({ph} / ({ph} + {pa}))"


def with_market(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse the raw closing/opening captures into `market_p_home` and
    `market_total`, dropping the six source columns.

    Closing is preferred; an implausible closing capture falls back to the
    opening line; a game with neither plausible ships no market fields rather
    than a misleading one.
    """
    def no_vig_col(home_col: str, away_col: str) -> pd.Series:
        ok = df[home_col].notna() & df[away_col].notna()
        out = pd.Series(np.nan, index=df.index)
        if ok.any():
            out[ok] = no_vig(df.loc[ok, home_col], df.loc[ok, away_col])
        return out

    p_close = no_vig_col("close_ml_home", "close_ml_away")
    p_open = no_vig_col("open_ml_home", "open_ml_away")
    close_ok = p_close.between(PLAUSIBLE_LO, PLAUSIBLE_HI)
    open_ok = p_open.between(PLAUSIBLE_LO, PLAUSIBLE_HI)
    df["market_p_home"] = np.where(close_ok, p_close,
                                   np.where(open_ok, p_open, np.nan))
    df["market_total"] = np.where(close_ok, df["close_total"],
                                  np.where(open_ok, df["open_total"], np.nan))
    return df.drop(columns=MARKET_SOURCE_COLS)
