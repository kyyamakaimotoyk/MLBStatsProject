"""Runs park factors, point-in-time by construction.

The factor for season S at venue V uses only regular-season games from the
up-to-3 seasons strictly before S, shrunk toward 1.0 by sample size. The
earliest ingested season has no prior data and gets 1.0 everywhere — noted
as a known limitation (backfilling 2019-2021 would fix it; revisit if park
features matter in ablation).

Usage: python -m features.park_factors
"""

import logging

import pandas as pd
from sqlalchemy import text

from core.db import get_engine

log = logging.getLogger("park_factors")

SHRINK_GAMES = 60  # pseudo-games of PF=1.0


def build() -> pd.DataFrame:
    games = pd.read_sql(
        text("""
            SELECT season, venue_id, home_score + away_score AS total_runs
            FROM games
            WHERE is_final AND game_type = 'R'
              AND home_score IS NOT NULL AND venue_id IS NOT NULL
        """),
        get_engine(),
    )
    seasons = sorted(games["season"].unique())
    rows = []
    for season in seasons:
        prior = games[games["season"].isin([s for s in seasons if season - 3 <= s < season])]
        league_rpg = prior["total_runs"].mean() if len(prior) else None
        for venue_id in games.loc[games["season"] == season, "venue_id"].unique():
            at_venue = prior[prior["venue_id"] == venue_id]
            n = len(at_venue)
            if league_rpg and n:
                raw = at_venue["total_runs"].mean() / league_rpg
                pf = 1.0 + (raw - 1.0) * n / (n + SHRINK_GAMES)
            else:
                pf = 1.0
            rows.append({"season": int(season), "venue_id": int(venue_id),
                         "pf_runs": float(pf), "n_games": n})
    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = build()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM park_factors"))
        conn.execute(
            text("""
                INSERT INTO park_factors (season, venue_id, pf_runs, n_games)
                VALUES (:season, :venue_id, :pf_runs, :n_games)
            """),
            df.to_dict("records"),
        )
    spread = df.groupby("season")["pf_runs"].agg(["min", "max"])
    log.info("wrote %d park factors\n%s", len(df), spread)


if __name__ == "__main__":
    main()
