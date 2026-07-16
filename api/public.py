"""Plain-language public API (the hoopmodel.com presentation model).

Everything here is phrased for non-statistical users: win chances as
percentages, predicted scores from the runs heads, picks graded with
correct/incorrect — no odds prices, no statistical jargon. The primary
model everywhere is lgbm_runs; the record includes both walk-forward
backfill (honest out-of-sample history) and live daily predictions.
"""

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from core.db import get_engine

router = APIRouter()

PRIMARY = "lgbm_runs"


def _clean(df: pd.DataFrame) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _no_vig(ml_home, ml_away):
    def implied(a):
        a = a.astype(float)
        return np.where(a < 0, -a / (-a + 100.0), 100.0 / (a + 100.0))
    ph, pa = implied(ml_home), implied(ml_away)
    return ph / (ph + pa)


def _graded_games(days: int, include_today: bool = True) -> pd.DataFrame:
    """One row per game: prediction + result + consensus, newest first."""
    df = pd.read_sql(text(f"""
        SELECT g.game_pk, g.game_date::text AS game_date, g.status, g.is_final,
               ht.abbrev AS home, ht.name AS home_name,
               at.abbrev AS away, at.name AS away_name,
               g.home_score, g.away_score,
               p.p_home, p.pred_home_runs, p.pred_away_runs, p.pred_total,
               o.ml_home, o.ml_away
        FROM games g
        JOIN LATERAL (
            SELECT * FROM model_predictions p
            WHERE p.game_pk = g.game_pk AND p.model_type = :model
            ORDER BY (p.model_version = 'daily_v1') DESC, p.created_at DESC
            LIMIT 1
        ) p ON TRUE
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN LATERAL (
            SELECT * FROM odds_lines o
            WHERE o.game_pk = p.game_pk AND o.ml_home IS NOT NULL
            ORDER BY o.is_closing DESC, o.captured_at DESC LIMIT 1
        ) o ON TRUE
        WHERE g.game_date >= current_date - :days
          AND g.game_date <{"=" if include_today else ""} current_date
        ORDER BY g.game_date DESC, g.game_pk
    """), get_engine(), params={"model": PRIMARY, "days": days})
    if df.empty:
        return df
    has_ml = df["ml_home"].notna() & df["ml_away"].notna()
    df["consensus"] = np.nan
    if has_ml.any():
        df.loc[has_ml, "consensus"] = _no_vig(df.loc[has_ml, "ml_home"],
                                              df.loc[has_ml, "ml_away"])
    df["pick"] = np.where(df["p_home"] >= 0.5, df["home"], df["away"])
    df["pick_chance"] = np.where(df["p_home"] >= 0.5, df["p_home"], 1 - df["p_home"])
    winner = np.where(df["home_score"] > df["away_score"], df["home"], df["away"])
    df["correct"] = np.where(df["is_final"], df["pick"] == winner, None)
    return df.drop(columns=["ml_home", "ml_away"])


@router.get("/api/public/summary")
def summary():
    """Headline cards: the visible track record."""
    engine = get_engine()
    rec = pd.read_sql(text("""
        SELECT g.game_date,
               (CASE WHEN p.pred_margin > 0 THEN g.home_score > g.away_score
                     ELSE g.home_score < g.away_score END) AS correct,
               abs(g.home_score - g.away_score - p.pred_margin) AS margin_err,
               abs(g.home_score + g.away_score - p.pred_total) AS total_err
        FROM games g
        JOIN LATERAL (
            SELECT * FROM model_predictions p
            WHERE p.game_pk = g.game_pk AND p.model_type = :m
            ORDER BY (p.model_version = 'daily_v1') DESC, p.created_at DESC
            LIMIT 1
        ) p ON TRUE
        WHERE g.is_final
    """), engine, params={"m": PRIMARY})
    batter = pd.read_sql(text("""
        SELECT (bp.p_hit >= 0.5) = (bg.h >= 1) AS hit_correct
        FROM batter_game_lines bg
        JOIN games g ON g.game_pk = bg.game_pk
        JOIN LATERAL (
            SELECT * FROM batter_predictions bp
            WHERE bp.game_pk = bg.game_pk AND bp.player_id = bg.player_id
            ORDER BY (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
            LIMIT 1
        ) bp ON TRUE
        WHERE g.is_final
    """), engine)
    if rec.empty:
        raise HTTPException(404, "no graded predictions yet")
    last30 = rec[rec["game_date"] >= rec["game_date"].max() - pd.Timedelta(days=30)]
    return {
        "games_graded": int(len(rec)),
        "winners_pct": float(rec["correct"].mean()),
        "last30_wins": int(last30["correct"].sum()),
        "last30_losses": int((~last30["correct"]).sum()),
        "avg_score_error": float(rec["margin_err"].mean()),
        "avg_total_error": float(rec["total_err"].mean()),
        "batter_calls_graded": int(len(batter)),
        "batter_hit_call_pct": float(batter["hit_correct"].mean()) if len(batter) else None,
        "since": str(rec["game_date"].min())[:10],
    }


@router.get("/api/public/feed")
def feed(days: int = Query(7, le=90)):
    """Tonight's picks + the last N days graded, one call, newest first."""
    df = _graded_games(days)
    if df.empty:
        raise HTTPException(404, "no games in window")
    batters = pd.read_sql(text("""
        SELECT bp.game_pk, pl.full_name AS name, bp.p_hr, bp.exp_h, bp.p_hit
        FROM batter_predictions bp
        JOIN players pl ON pl.player_id = bp.player_id
        JOIN games g ON g.game_pk = bp.game_pk
        WHERE g.game_date >= current_date - :days
        ORDER BY bp.p_hr DESC
    """), get_engine(), params={"days": days})
    top_by_game = {pk: _clean(grp.head(3).drop(columns=["game_pk"]))
                   for pk, grp in batters.groupby("game_pk")}
    days_out = []
    for date, grp in df.groupby("game_date", sort=False):
        games = _clean(grp)
        for game in games:
            game["watch"] = top_by_game.get(game["game_pk"], [])
        days_out.append({"date": date, "games": games})
    return {"days": days_out}


@router.get("/api/public/team/{abbrev}")
def team(abbrev: str, days: int = Query(45, le=120)):
    """A team's recent games with our predictions graded, plus simple form."""
    df = pd.read_sql(text("""
        SELECT g.game_pk, g.game_date::text AS game_date, g.is_final,
               ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score, p.p_home, p.pred_home_runs,
               p.pred_away_runs
        FROM games g
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN model_predictions p
          ON p.game_pk = g.game_pk AND p.model_type = :m
        WHERE (ht.abbrev = :ab OR at.abbrev = :ab)
          AND g.game_date >= current_date - :days
        ORDER BY g.game_date DESC
    """), get_engine(), params={"m": PRIMARY, "ab": abbrev.upper(), "days": days})
    if df.empty:
        raise HTTPException(404, f"no recent games for {abbrev}")
    ab = abbrev.upper()
    is_home = df["home"] == ab
    finals = df[df["is_final"]]
    won = np.where(finals["home"] == ab,
                   finals["home_score"] > finals["away_score"],
                   finals["away_score"] > finals["home_score"])
    runs_for = np.where(finals["home"] == ab, finals["home_score"], finals["away_score"])
    df["team_won"] = None
    df.loc[df["is_final"], "team_won"] = won
    return {
        "team": ab,
        "last10_wins": int(won[:10].sum()),
        "last10_losses": int((~won[:10]).sum()),
        "runs_per_game_l10": float(np.mean(runs_for[:10])) if len(finals) else None,
        "games": _clean(df),
    }


@router.get("/api/public/player/{player_id}")
def player(player_id: int, days: int = Query(45, le=120)):
    """A batter's recent game log with our calls graded."""
    engine = get_engine()
    name = pd.read_sql(text(
        "SELECT full_name FROM players WHERE player_id = :p"), engine,
        params={"p": player_id})
    if name.empty:
        raise HTTPException(404, "unknown player")
    df = pd.read_sql(text("""
        SELECT g.game_date::text AS game_date, ht.abbrev AS home, at.abbrev AS away,
               bg.pa, bg.h, bg.hr, bg.tb, bg.bb, bg.so AS k,
               bp.exp_h, bp.p_hit, bp.p_hr
        FROM batter_game_lines bg
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN batter_predictions bp
          ON bp.game_pk = bg.game_pk AND bp.player_id = bg.player_id
        WHERE bg.player_id = :p AND g.is_final
          AND g.game_date >= current_date - :days
        ORDER BY g.game_date DESC
    """), engine, params={"p": player_id, "days": days})
    recent = df.head(15)
    return {
        "player_id": player_id,
        "name": name["full_name"].iloc[0],
        "l15_hits_per_game": float(recent["h"].mean()) if len(recent) else None,
        "l15_hr": int(recent["hr"].sum()) if len(recent) else 0,
        "games": _clean(df),
    }


@router.get("/api/public/results")
def results(days: int = Query(1400, le=2000)):
    """Flat graded rows for client-side chart derivation (hoopmodel pattern:
    the browser computes skill/ROC/confusion/error metrics from raw rows)."""
    df = pd.read_sql(text("""
        SELECT g.game_date::text AS game_date, p.p_home, p.pred_margin,
               p.pred_total,
               g.home_score - g.away_score AS margin,
               g.home_score + g.away_score AS total,
               (g.home_score > g.away_score) AS home_won
        FROM games g
        JOIN LATERAL (
            SELECT * FROM model_predictions p
            WHERE p.game_pk = g.game_pk AND p.model_type = :m
            ORDER BY (p.model_version = 'daily_v1') DESC, p.created_at DESC
            LIMIT 1
        ) p ON TRUE
        WHERE g.is_final AND g.game_date >= current_date - :days
        ORDER BY g.game_date
    """), get_engine(), params={"m": PRIMARY, "days": days})
    return _clean(df)


@router.get("/api/public/teams")
def teams_list():
    return _clean(pd.read_sql(text("""
        SELECT team_id, abbrev, name, league, division
        FROM teams WHERE active ORDER BY league, division, name
    """), get_engine()))


@router.get("/api/public/players")
def players_search(q: str = Query(..., min_length=2)):
    """Name search for the player deep-dive."""
    df = pd.read_sql(text("""
        SELECT DISTINCT p.player_id, p.full_name
        FROM players p
        JOIN batter_game_lines bg USING (player_id)
        WHERE p.full_name ILIKE :q
        LIMIT 20
    """), get_engine(), params={"q": f"%{q}%"})
    return _clean(df)
