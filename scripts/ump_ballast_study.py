"""Wave 4 (2026-07 cycle): estimate the EB shrinkage ballasts for the per-HP-
umpire K/BB factors on OUR OWN data (2019+, MLBAM ids — the era and id space
the UMP_SERVE feature serves in). The Retrosheet crew study measured the
signal by era; this fixes the constants the feature build freezes.

Method (the alpha-atlas pattern — estimate offline, freeze in code): per-ump
season-level factors vs the season league rate (>= MIN_SEASON_GAMES HP games
both seasons), pooled year-over-year Pearson r. Season reliability r = n /
(n + n0) at the mean per-season game count n, so n0 = n * (1 - r) / r, clipped
to BALLAST_BOUNDS. K's collapsed signal (crew study: r ~ .10 post-2016) makes
its ballast large — "shrink K hard" falls out of the data rather than being
hand-tuned. Constants land in features/team_features.py (UMP_SERVE block) and
the tuning-log entry.

Usage:
    .venv\\Scripts\\python scripts\\ump_ballast_study.py
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402

log = logging.getLogger("ump_ballast_study")

MIN_SEASON_GAMES = 20
BALLAST_BOUNDS = (10.0, 2000.0)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = pd.read_sql(text("""
        SELECT g.season, o.official_id AS ump_id, bl.k, bl.bb, bl.pa
        FROM games g
        JOIN game_officials o
             ON o.game_pk = g.game_pk AND o.official_type = 'Home Plate'
        JOIN (SELECT game_pk, SUM(so) AS k, SUM(bb) AS bb, SUM(pa) AS pa
              FROM batter_game_lines GROUP BY game_pk) bl
             ON bl.game_pk = g.game_pk
        WHERE g.is_final AND g.game_type = 'R' AND o.official_id IS NOT NULL
    """), get_engine())
    log.info("loaded %d HP-ump games, seasons %d-%d",
             len(df), df["season"].min(), df["season"].max())

    lg = df.groupby("season")[["k", "bb", "pa"]].sum()
    us = df.groupby(["ump_id", "season"]).agg(
        k=("k", "sum"), bb=("bb", "sum"), pa=("pa", "sum"), n=("k", "size"))
    us = us[us["n"] >= MIN_SEASON_GAMES].reset_index().merge(
        lg, on="season", suffixes=("", "_lg"))
    us["k_factor"] = (us["k"] / us["pa"]) / (us["k_lg"] / us["pa_lg"])
    us["bb_factor"] = (us["bb"] / us["pa"]) / (us["bb_lg"] / us["pa_lg"])

    print(f"\nump-seasons with >= {MIN_SEASON_GAMES} HP games: {len(us)}; "
          f"mean games/season n = {us['n'].mean():.1f}")
    for stat in ("k_factor", "bb_factor"):
        piv = us.pivot_table(index="ump_id", columns="season", values=stat)
        pairs = []
        for s in sorted(us["season"].unique())[:-1]:
            if s in piv.columns and s + 1 in piv.columns:
                p = piv[[s, s + 1]].dropna()
                if len(p) >= 15:
                    pairs.append(p.to_numpy())
        stacked = np.vstack(pairs)
        r = float(np.corrcoef(stacked[:, 0], stacked[:, 1])[0, 1])
        n_bar = us["n"].mean()
        n0 = float(np.clip(n_bar * (1 - r) / max(r, 1e-6), *BALLAST_BOUNDS))
        sd = float(us.groupby("season")[stat].std().mean())
        print(f"{stat}: pooled YoY r = {r:.3f} over {len(stacked)} pairs, "
              f"between-ump SD = {sd:.4f}\n"
              f"  -> ballast n0 = {n0:.0f} games "
              f"(w at a 90-game window = {90 / (90 + n0):.2f})")


if __name__ == "__main__":
    main()
