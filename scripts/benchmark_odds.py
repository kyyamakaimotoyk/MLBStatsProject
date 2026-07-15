"""Benchmark stored predictions against market closing lines.

The gold-standard evaluation (docs/PROJECT_PLAN.md §8): compare each model's
picks/margins/totals to the closing line on the same games. Uses whatever
overlap exists between model_predictions and odds_lines (is_closing).

Vig removal: implied probabilities from both moneylines, normalized to sum
to 1 (the standard no-vig closing probability).

Usage:
    python scripts/benchmark_odds.py                       # all overlap
    python scripts/benchmark_odds.py --version daily_v1    # daily pipeline only
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402


def implied_prob(american: pd.Series) -> pd.Series:
    """American odds -> implied probability (with vig)."""
    a = american.astype(float)
    return np.where(a < 0, -a / (-a + 100.0), 100.0 / (a + 100.0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=None, help="filter model_version")
    args = ap.parse_args()

    sql = """
        SELECT p.model_type, p.model_version, p.p_home, p.pred_margin, p.pred_total,
               o.ml_home, o.ml_away, o.total AS close_total, o.runline_home,
               g.home_score, g.away_score, g.game_date
        FROM model_predictions p
        JOIN games g USING (game_pk)
        JOIN LATERAL (
            SELECT * FROM odds_lines o
            WHERE o.game_pk = p.game_pk AND o.is_closing
              AND o.ml_home IS NOT NULL AND o.ml_away IS NOT NULL
            ORDER BY o.captured_at DESC LIMIT 1
        ) o ON TRUE
        WHERE g.is_final
    """
    params = {}
    if args.version:
        sql += " AND p.model_version = :v"
        params["v"] = args.version
    df = pd.read_sql(text(sql), get_engine(), params=params or None)
    if df.empty:
        print("no overlap between predictions and closing lines yet")
        return

    raw_home = implied_prob(df["ml_home"])
    raw_away = implied_prob(df["ml_away"])
    df["market_p_home"] = raw_home / (raw_home + raw_away)
    df["margin"] = df["home_score"] - df["away_score"]
    df["total"] = df["home_score"] + df["away_score"]
    df["home_won"] = df["margin"] > 0

    # Archive-corruption guard: pregame MLB win probabilities live in roughly
    # [0.25, 0.80]; anything outside [0.20, 0.85] is a bad row (e.g. an
    # in-game line that slipped through) and poisons log loss. Exclude the
    # game for ALL models so the comparison stays paired.
    ok = df["market_p_home"].between(0.20, 0.85)
    dropped = df.loc[~ok, "game_date"].nunique()
    if (~ok).any():
        print(f"excluded {(~ok).sum()} rows ({dropped} dates) with implausible "
              f"market probabilities (archive corruption guard)")
    df = df[ok]

    print(f"=== vs closing line, {df['game_date'].min()} .. {df['game_date'].max()} ===\n")
    rows = []
    for (mtype, mver), grp in df.groupby(["model_type", "model_version"]):
        agree = ((grp["p_home"] > 0.5) == (grp["market_p_home"] > 0.5)).mean()
        rows.append({
            "model": mtype, "version": mver, "n": len(grp),
            "model_acc": ((grp["pred_margin"] > 0) == grp["home_won"]).mean(),
            "market_acc": ((grp["market_p_home"] > 0.5) == grp["home_won"]).mean(),
            "model_logloss": -np.mean(np.where(grp["home_won"],
                                               np.log(grp["p_home"].clip(1e-6, 1 - 1e-6)),
                                               np.log((1 - grp["p_home"]).clip(1e-6, 1 - 1e-6)))),
            "market_logloss": -np.mean(np.where(grp["home_won"],
                                                np.log(grp["market_p_home"]),
                                                np.log(1 - grp["market_p_home"]))),
            "total_mae_model": (grp["total"] - grp["pred_total"]).abs().mean(),
            "total_mae_market": (grp["total"] - grp["close_total"]).abs().mean()
            if grp["close_total"].notna().any() else np.nan,
            "pick_agreement": agree,
        })
    out = pd.DataFrame(rows).set_index(["model", "version"])
    print(out.round(4).to_string())


if __name__ == "__main__":
    main()
