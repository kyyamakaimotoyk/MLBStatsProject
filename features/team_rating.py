"""Elo-style team strength, tuned for baseball.

Sequential over all final games (regular season + postseason) in time order,
so the pregame rating for game G reflects only games before G — point-in-time
by construction. Constants follow the 538 MLB conventions: small K (single
games carry little information in baseball), modest home advantage (~54%
home win rate), log margin-of-victory multiplier, 2/3 season carryover.

A pure-Elo baseline should land around 55-56% accuracy (vs 66% in the NBA —
baseball is noisier).

Usage: python -m features.team_rating
"""

import logging
import math

import pandas as pd
from sqlalchemy import text

from core.db import get_engine

log = logging.getLogger("team_rating")

K = 4.0
HOME_ADV = 24.0      # Elo points; ~54% for even teams
MEAN = 1500.0
CARRYOVER = 2 / 3    # regression toward MEAN at season boundaries


def build(max_date: str | None = None) -> pd.DataFrame:
    """Return one row per game: pregame ratings and home win probability."""
    sql = """
        SELECT game_pk, season, game_date, first_pitch_utc,
               home_team_id, away_team_id, home_score, away_score
        FROM games
        WHERE is_final
    """
    params = {}
    if max_date:
        sql += " AND game_date <= :max_date"
        params["max_date"] = max_date
    sql += " ORDER BY game_date, first_pitch_utc, game_pk"
    games = pd.read_sql(text(sql), get_engine(), params=params)

    ratings: dict[int, float] = {}
    last_season: dict[int, int] = {}
    rows = []
    correct = decided = 0

    for g in games.itertuples():
        for team in (g.home_team_id, g.away_team_id):
            if team not in ratings:
                ratings[team] = MEAN
            elif last_season.get(team) != g.season:
                ratings[team] = MEAN + CARRYOVER * (ratings[team] - MEAN)
            last_season[team] = g.season

        rh, ra = ratings[g.home_team_id], ratings[g.away_team_id]
        p_home = 1.0 / (1.0 + 10 ** (-((rh + HOME_ADV - ra) / 400.0)))
        rows.append({"game_pk": g.game_pk, "home_rating": rh, "away_rating": ra, "p_home": p_home})

        if g.home_score is None or g.away_score is None:
            continue
        margin = g.home_score - g.away_score
        home_won = margin > 0
        decided += 1
        correct += (p_home > 0.5) == home_won
        # 538 NFL-style MOV multiplier: dampens blowouts by the favorite
        winner_diff = (rh + HOME_ADV - ra) if home_won else (ra - rh - HOME_ADV)
        mult = math.log(abs(margin) + 1) * 2.2 / (winner_diff * 0.001 + 2.2)
        delta = K * mult * ((1.0 if home_won else 0.0) - p_home)
        ratings[g.home_team_id] += delta
        ratings[g.away_team_id] -= delta

    log.info("built ratings for %d games; pure-Elo accuracy %.3f", len(rows), correct / max(decided, 1))
    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = build()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM team_strength_pregame"))
        conn.execute(
            text("""
                INSERT INTO team_strength_pregame (game_pk, home_rating, away_rating, p_home)
                VALUES (:game_pk, :home_rating, :away_rating, :p_home)
            """),
            df.to_dict("records"),
        )
    log.info("wrote %d rows to team_strength_pregame", len(df))


if __name__ == "__main__":
    main()
