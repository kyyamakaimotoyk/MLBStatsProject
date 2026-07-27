"""Outcome tracker: how have stored predictions done against final scores?

Joins model_predictions / batter_predictions to results and prints rolling
performance per model. Works for both walk-forward backfills and the daily
pipeline (model_version daily_v1) once games go final.

Usage:
    python scripts/track_performance.py                 # last 30 days
    python scripts/track_performance.py --days 90
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    engine = get_engine()

    team = pd.read_sql(text("""
        SELECT p.model_type, p.model_version, p.pred_margin, p.pred_total, p.p_home,
               g.home_score - g.away_score AS margin, g.home_score + g.away_score AS total
        FROM model_predictions p
        JOIN games g USING (game_pk)
        WHERE g.is_final AND g.game_date >= current_date - :days
    """), engine, params={"days": args.days})
    if team.empty:
        print(f"no team predictions with results in the last {args.days} days")
    else:
        team["hit"] = (team["p_home"] >= 0.5) == (team["margin"] > 0)
        team["margin_ae"] = (team["margin"] - team["pred_margin"]).abs()
        team["total_ae"] = (team["total"] - team["pred_total"]).abs()
        summary = team.groupby(["model_type", "model_version"]).agg(
            n=("hit", "size"), win_acc=("hit", "mean"),
            margin_mae=("margin_ae", "mean"), total_mae=("total_ae", "mean"))
        print(f"=== team predictions, last {args.days} days ===")
        print(summary.round(4).to_string())

    batter = pd.read_sql(text("""
        SELECT p.model_version, p.p_hit, p.p_hr, p.exp_h, p.exp_hr,
               b.h, b.hr
        FROM batter_predictions p
        JOIN batter_game_lines b USING (game_pk, player_id)
        JOIN games g ON g.game_pk = p.game_pk
        WHERE g.is_final AND g.game_date >= current_date - :days
    """), engine, params={"days": args.days})
    if batter.empty:
        print(f"\nno batter predictions with results in the last {args.days} days")
    else:
        batter["hit1"] = (batter["h"] >= 1).astype(float)
        batter["hr1"] = (batter["hr"] >= 1).astype(float)
        summary = batter.groupby("model_version").apply(
            lambda d: pd.Series({
                "n": len(d),
                "brier_p_hit": ((d["p_hit"] - d["hit1"]) ** 2).mean(),
                "brier_p_hr": ((d["p_hr"] - d["hr1"]) ** 2).mean(),
                "mae_h": (d["h"] - d["exp_h"]).abs().mean(),
                "mae_hr": (d["hr"] - d["exp_hr"]).abs().mean(),
            }), include_groups=False)
        print(f"\n=== batter predictions, last {args.days} days ===")
        print(summary.round(4).to_string())


if __name__ == "__main__":
    main()
