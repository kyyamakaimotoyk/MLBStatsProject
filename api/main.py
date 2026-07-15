"""Read-only public API (Phase 6 web MVP).

Deliberately model-free (the NBA api/ lesson): this process only reads
prediction and result tables — no torch/lightgbm imports, no feature code.
Runs locally for now:

    .venv\\Scripts\\uvicorn api.main:app --reload --port 8000
"""

import os

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from core.db import get_engine

app = FastAPI(title="MLB Stats API", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _df(sql: str, **params) -> list[dict]:
    df = pd.read_sql(text(sql), get_engine(), params=params or None)
    # astype(object) first: an all-NULL column arrives as float64, and
    # .where() on a float column silently turns None back into NaN,
    # which JSON serialization rejects.
    return df.astype(object).where(df.notna(), None).to_dict("records")


@app.get("/api/health")
def health():
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/predictions")
def predictions(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Team-level predictions (all models) for a date, labeled with matchups."""
    rows = _df("""
        SELECT g.game_pk, g.game_date::text AS game_date, g.status,
               ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score, g.is_final,
               p.model_type, p.model_version, p.p_home, p.pred_margin, p.pred_total,
               p.data_through_date::text AS data_through_date
        FROM model_predictions p
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        WHERE g.game_date = :date
        ORDER BY g.game_pk, p.model_type
    """, date=date)
    if not rows:
        raise HTTPException(404, f"no predictions for {date}")
    return rows


@app.get("/api/batters")
def batters(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
            limit: int = Query(200, le=500)):
    """Per-batter predictions for a date, best HR probability first."""
    rows = _df("""
        SELECT g.game_pk, ht.abbrev AS home, at.abbrev AS away,
               pl.full_name AS batter, sp.full_name AS probable_pitcher,
               b.lineup_slot, b.exp_pa, b.exp_h, b.exp_tb, b.exp_hr, b.exp_bb, b.exp_k,
               b.p_hit, b.p_hr, b.p_tb2, b.p_bb, b.model_version
        FROM batter_predictions b
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        JOIN players pl ON pl.player_id = b.player_id
        LEFT JOIN players sp ON sp.player_id = b.sp_id
        WHERE g.game_date = :date
        ORDER BY b.p_hr DESC
        LIMIT :limit
    """, date=date, limit=limit)
    if not rows:
        raise HTTPException(404, f"no batter predictions for {date}")
    return rows


@app.get("/api/performance")
def performance(days: int = Query(30, le=365)):
    """Rolling accuracy/MAE per model against final scores."""
    team = _df("""
        SELECT p.model_type, p.model_version, count(*) AS n,
               avg(((p.pred_margin > 0) = (g.home_score > g.away_score))::int) AS win_acc,
               avg(abs(g.home_score - g.away_score - p.pred_margin)) AS margin_mae,
               avg(abs(g.home_score + g.away_score - p.pred_total)) AS total_mae
        FROM model_predictions p
        JOIN games g USING (game_pk)
        WHERE g.is_final AND g.game_date >= current_date - :days
        GROUP BY 1, 2 ORDER BY 1, 2
    """, days=days)
    batter = _df("""
        SELECT b.model_version, count(*) AS n,
               avg(power(b.p_hit - (bg.h >= 1)::int, 2)) AS brier_p_hit,
               avg(power(b.p_hr - (bg.hr >= 1)::int, 2)) AS brier_p_hr,
               avg(abs(bg.h - b.exp_h)) AS mae_h
        FROM batter_predictions b
        JOIN batter_game_lines bg USING (game_pk, player_id)
        JOIN games g ON g.game_pk = b.game_pk
        WHERE g.is_final AND g.game_date >= current_date - :days
        GROUP BY 1
    """, days=days)
    return {"days": days, "team": team, "batter": batter}


@app.get("/api/results")
def results(days: int = Query(7, le=60)):
    """Recent finals with the lgbm_runs prediction alongside."""
    return _df("""
        SELECT g.game_date::text AS game_date, ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score, p.p_home, p.pred_margin, p.pred_total,
               p.model_version
        FROM games g
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN model_predictions p
          ON p.game_pk = g.game_pk AND p.model_type = 'lgbm_runs'
        WHERE g.is_final AND g.game_date >= current_date - :days
        ORDER BY g.game_date DESC, g.game_pk
    """, days=days)
