"""Read-only public API (Phase 6 web MVP).

Deliberately model-free (the NBA api/ lesson): this process only reads
prediction and result tables — no torch/lightgbm imports, no feature code.
Runs locally for now:

    .venv\\Scripts\\uvicorn api.main:app --reload --port 8000
"""

import os
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from core.db import get_engine


def _no_vig(ml_home: pd.Series, ml_away: pd.Series) -> pd.Series:
    def implied(a):
        a = a.astype(float)
        return np.where(a < 0, -a / (-a + 100.0), 100.0 / (a + 100.0))
    ph, pa = implied(ml_home), implied(ml_away)
    return ph / (ph + pa)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prime the read cache in the background so the first visitor after a
    deploy doesn't pay for a cold process. Warms exactly what the site's two
    default page loads ask for; anything else fills in on demand."""
    from api import public
    from api.cache import warm

    warm([
        (public.summary, {}),
        (public.feed, {"days": 7}),           # Tonight, initial day tables
        (public.feed, {"days": 21}),          # Record, three-week strip
        (public.results, {"days": 30}),       # Tonight, default 1m window
        (public.results, {"days": 60}),       # Record, default 2m window
        (public.batter_results, {"days": 60}),
    ])
    yield


app = FastAPI(title="MLB Stats API", version="0.1", lifespan=lifespan)

# Middleware order: the last one added is the outermost, so CORS must be added
# last — its headers have to survive on every response, including the
# compressed ones and the error paths.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def public_cache_headers(request: Request, call_next):
    """Let the browser (and a CDN, if one is ever put in front of this) reuse
    these responses. Without it, moving between Tonight and Record refetches
    the same track record from scratch. The windows are deliberately shorter
    than the server-side TTLs — this is the last cache to go stale and the
    only one we cannot flush."""
    response = await call_next(request)
    if (request.method == "GET" and response.status_code == 200
            and request.url.path.startswith("/api/public/")):
        response.headers["Cache-Control"] = (
            "public, max-age=60, stale-while-revalidate=600")
    return response


from api.public import ET_TODAY, router as public_router  # noqa: E402

app.include_router(public_router)


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
    """Team-level predictions (all models) for a date, labeled with matchups
    and the latest captured market line (closing preferred)."""
    df = pd.read_sql(text("""
        SELECT g.game_pk, g.game_date::text AS game_date, g.status,
               ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score, g.is_final,
               p.model_type, p.model_version, p.p_home, p.pred_margin, p.pred_total,
               p.data_through_date::text AS data_through_date,
               o.ml_home, o.ml_away, o.total AS market_total,
               o.book AS market_book, o.is_closing AS market_is_closing
        FROM model_predictions p
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN LATERAL (
            SELECT * FROM odds_lines o
            WHERE o.game_pk = p.game_pk AND o.ml_home IS NOT NULL
            ORDER BY o.is_closing DESC, o.captured_at DESC LIMIT 1
        ) o ON TRUE
        WHERE g.game_date = :date
        ORDER BY g.game_pk, p.model_type
    """), get_engine(), params={"date": date})
    if df.empty:
        raise HTTPException(404, f"no predictions for {date}")
    has_ml = df["ml_home"].notna() & df["ml_away"].notna()
    df["market_p_home"] = np.nan
    if has_ml.any():
        df.loc[has_ml, "market_p_home"] = _no_vig(df.loc[has_ml, "ml_home"],
                                                  df.loc[has_ml, "ml_away"])
    return df.astype(object).where(df.notna(), None).to_dict("records")


@app.get("/api/batters")
def batters(date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
            limit: int = Query(200, le=500)):
    """Per-batter predictions for a date, best HR probability first."""
    rows = _df("""
        SELECT g.game_pk, ht.abbrev AS home, at.abbrev AS away,
               b.player_id, pl.full_name AS batter,
               b.sp_id AS probable_pitcher_id, sp.full_name AS probable_pitcher,
               b.lineup_slot, b.exp_pa, b.exp_h, b.exp_tb, b.exp_hr, b.exp_bb, b.exp_k,
               b.exp_rbi, b.p_hit, b.p_hr, b.p_tb2, b.p_bb, b.model_version
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
    team = _df(f"""
        SELECT p.model_type, p.model_version, count(*) AS n,
               avg(((p.p_home >= 0.5) = (g.home_score > g.away_score))::int) AS win_acc,
               avg(abs(g.home_score - g.away_score - p.pred_margin)) AS margin_mae,
               avg(abs(g.home_score + g.away_score - p.pred_total)) AS total_mae
        FROM model_predictions p
        JOIN games g USING (game_pk)
        WHERE g.is_final AND g.game_date >= {ET_TODAY} - :days
        GROUP BY 1, 2 ORDER BY 1, 2
    """, days=days)
    batter = _df(f"""
        SELECT b.model_version, count(*) AS n,
               avg(power(b.p_hit - (bg.h >= 1)::int, 2)) AS brier_p_hit,
               avg(power(b.p_hr - (bg.hr >= 1)::int, 2)) AS brier_p_hr,
               avg(abs(bg.h - b.exp_h)) AS mae_h
        FROM batter_predictions b
        JOIN batter_game_lines bg USING (game_pk, player_id)
        JOIN games g ON g.game_pk = b.game_pk
        WHERE g.is_final AND g.game_date >= {ET_TODAY} - :days
        GROUP BY 1
    """, days=days)

    market_df = pd.read_sql(text(f"""
        SELECT p.model_type, p.model_version, p.p_home,
               o.ml_home, o.ml_away,
               g.home_score > g.away_score AS home_won
        FROM model_predictions p
        JOIN games g USING (game_pk)
        JOIN LATERAL (
            SELECT * FROM odds_lines o
            WHERE o.game_pk = p.game_pk AND o.is_closing
              AND o.ml_home IS NOT NULL AND o.ml_away IS NOT NULL
            ORDER BY o.captured_at DESC LIMIT 1
        ) o ON TRUE
        WHERE g.is_final AND g.game_date >= {ET_TODAY} - :days
    """), get_engine(), params={"days": days})
    market = []
    if not market_df.empty:
        market_df["market_p"] = _no_vig(market_df["ml_home"], market_df["ml_away"])
        market_df = market_df[market_df["market_p"].between(0.20, 0.85)]
        for (mtype, mver), grp in market_df.groupby(["model_type", "model_version"]):
            market.append({
                "model_type": mtype, "model_version": mver, "n": int(len(grp)),
                "model_acc": float(((grp["p_home"] >= 0.5) == grp["home_won"]).mean()),
                "market_acc": float(((grp["market_p"] > 0.5) == grp["home_won"]).mean()),
                "pick_agreement": float(((grp["p_home"] >= 0.5)
                                         == (grp["market_p"] > 0.5)).mean()),
            })
    return {"days": days, "team": team, "batter": batter, "market": market}


@app.get("/api/results")
def results(days: int = Query(7, le=60)):
    """Recent finals with the lgbm_runs prediction alongside."""
    return _df(f"""
        SELECT g.game_date::text AS game_date, ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score, p.p_home, p.pred_margin, p.pred_total,
               p.model_version
        FROM games g
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN model_predictions p
          ON p.game_pk = g.game_pk AND p.model_type = 'lgbm_runs'
        WHERE g.is_final AND g.game_date >= {ET_TODAY} - :days
        ORDER BY g.game_date DESC, g.game_pk
    """, days=days)
