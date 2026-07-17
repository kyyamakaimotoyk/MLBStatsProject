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
def player(player_id: int, days: int = Query(250, le=500)):
    """A player's full profile: batting game log + season rates, pitching
    game log + season rates (two-way players show both), our latest model
    numbers, and calls graded per game."""
    engine = get_engine()
    name = pd.read_sql(text(
        "SELECT full_name, primary_position FROM players WHERE player_id = :p"),
        engine, params={"p": player_id})
    if name.empty:
        raise HTTPException(404, "unknown player")

    bat = pd.read_sql(text("""
        SELECT g.game_date::text AS game_date, g.season,
               ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score,
               bg.pa, bg.ab, bg.r, bg.h, bg.doubles, bg.triples, bg.hr, bg.tb,
               bg.rbi, bg.bb, bg.so AS k, bg.hbp, bg.sf, bg.sb,
               bp.exp_h, bp.exp_tb, bp.exp_hr, bp.exp_bb, bp.exp_k,
               bp.p_hit, bp.p_hr
        FROM batter_game_lines bg
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        LEFT JOIN LATERAL (
            SELECT * FROM batter_predictions bp
            WHERE bp.game_pk = bg.game_pk AND bp.player_id = bg.player_id
            ORDER BY (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
            LIMIT 1
        ) bp ON TRUE
        WHERE bg.player_id = :p AND g.is_final
          AND g.game_date >= current_date - :days
        ORDER BY g.game_date DESC
    """), engine, params={"p": player_id, "days": days})

    pit = pd.read_sql(text("""
        SELECT g.game_date::text AS game_date, g.season,
               ht.abbrev AS home, at.abbrev AS away,
               g.home_score, g.away_score,
               pg.is_starter, pg.outs, pg.batters_faced, pg.h, pg.r, pg.er,
               pg.bb, pg.so AS k, pg.hr, pg.pitches
        FROM pitcher_game_lines pg
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        WHERE pg.player_id = :p AND g.is_final
          AND g.game_date >= current_date - :days
        ORDER BY g.game_date DESC
    """), engine, params={"p": player_id, "days": days})

    def batting_season(df: pd.DataFrame) -> dict | None:
        season = df[df["season"] == df["season"].max()] if len(df) else df
        if season.empty:
            return None
        ab = season["ab"].sum()
        h = season["h"].sum()
        bb = season["bb"].sum()
        hbp = season["hbp"].fillna(0).sum()
        sf = season["sf"].fillna(0).sum()
        tb = season["tb"].sum()
        obp_den = ab + bb + hbp + sf
        avg = h / ab if ab else None
        obp = (h + bb + hbp) / obp_den if obp_den else None
        slg = tb / ab if ab else None
        return {
            "season": int(season["season"].max()),
            "games": int(len(season)),
            "pa": int(season["pa"].sum()),
            "avg": float(avg) if avg is not None else None,
            "obp": float(obp) if obp is not None else None,
            "slg": float(slg) if slg is not None else None,
            "ops": float(obp + slg) if obp is not None and slg is not None else None,
            "hr": int(season["hr"].sum()),
            "rbi": int(season["rbi"].sum()),
            "sb": int(season["sb"].fillna(0).sum()),
        }

    def pitching_season(df: pd.DataFrame) -> dict | None:
        season = df[df["season"] == df["season"].max()] if len(df) else df
        if season.empty:
            return None
        outs = season["outs"].fillna(0).sum()
        ip = outs / 3.0
        er = season["er"].fillna(0).sum()
        bb = season["bb"].fillna(0).sum()
        h = season["h"].fillna(0).sum()
        k = season["k"].fillna(0).sum()
        return {
            "season": int(season["season"].max()),
            "games": int(len(season)),
            "starts": int(season["is_starter"].fillna(False).sum()),
            "ip": float(ip),
            "era": float(er / ip * 9) if ip else None,
            "whip": float((bb + h) / ip) if ip else None,
            "k9": float(k / ip * 9) if ip else None,
            "so": int(k),
        }

    latest_pred = pd.read_sql(text("""
        SELECT bp.exp_pa, bp.exp_h, bp.exp_tb, bp.exp_hr, bp.exp_bb, bp.exp_k,
               bp.p_hit, bp.p_hr, g.game_date::text AS for_date
        FROM batter_predictions bp
        JOIN games g ON g.game_pk = bp.game_pk
        WHERE bp.player_id = :p
        ORDER BY g.game_date DESC,
                 (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
        LIMIT 1
    """), engine, params={"p": player_id})

    return {
        "player_id": player_id,
        "name": name["full_name"].iloc[0],
        "position": name["primary_position"].iloc[0],
        "batting": {"season": batting_season(bat), "games": _clean(bat)}
        if len(bat) else None,
        "pitching": {"season": pitching_season(pit), "games": _clean(pit)}
        if len(pit) else None,
        "latest_pred": _clean(latest_pred)[0] if len(latest_pred) else None,
    }


@router.get("/api/public/team-trends")
def team_trends(stat: str = Query("runs_scored"),
                teams: str = Query(...),
                season: int | None = Query(None)):
    """Per-game team stat with a rolling 10-game mean, for the trends chart."""
    if stat not in ("runs_scored", "runs_allowed", "run_diff", "total_runs"):
        raise HTTPException(400, "unknown stat")
    abbrevs = [t.strip().upper() for t in teams.split(",") if t.strip()][:6]
    engine = get_engine()
    if season is None:
        season = int(pd.read_sql(text(
            "SELECT max(season) AS s FROM games WHERE is_final"), engine)["s"].iloc[0])
    df = pd.read_sql(text("""
        SELECT g.game_date::text AS game_date, g.first_pitch_utc,
               ht.abbrev AS home, at.abbrev AS away, g.home_score, g.away_score
        FROM games g
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        WHERE g.is_final AND g.season = :s
          AND (ht.abbrev = ANY(:teams) OR at.abbrev = ANY(:teams))
        ORDER BY g.game_date, g.first_pitch_utc
    """), engine, params={"s": season, "teams": abbrevs})
    series = []
    for ab in abbrevs:
        mine = df[(df["home"] == ab) | (df["away"] == ab)].copy()
        if mine.empty:
            continue
        is_home = mine["home"] == ab
        scored = np.where(is_home, mine["home_score"], mine["away_score"]).astype(float)
        allowed = np.where(is_home, mine["away_score"], mine["home_score"]).astype(float)
        value = {"runs_scored": scored, "runs_allowed": allowed,
                 "run_diff": scored - allowed,
                 "total_runs": scored + allowed}[stat]
        rolling = pd.Series(value).rolling(10, min_periods=3).mean()
        series.append({
            "team": ab,
            "points": [{"date": d, "value": float(v),
                        "rolling": (float(r) if pd.notna(r) else None)}
                       for d, v, r in zip(mine["game_date"], value, rolling)],
        })
    return {"season": season, "stat": stat, "series": series}


@router.get("/api/public/results")
def results(days: int = Query(1400, le=2000)):
    """Flat graded rows for client-side chart derivation (hoopmodel pattern:
    the browser computes skill/ROC/confusion/error metrics from raw rows).
    Each row also carries the market's pregame view when we have it — the
    no-vig closing win probability and the closing total line — so the
    browser can grade the model against the betting market on the same
    games. Lines are benchmarks only, never model inputs (hard rule)."""
    df = pd.read_sql(text("""
        SELECT g.game_date::text AS game_date, p.p_home, p.pred_margin,
               p.pred_total,
               g.home_score - g.away_score AS margin,
               g.home_score + g.away_score AS total,
               (g.home_score > g.away_score) AS home_won,
               c.ml_home AS close_ml_home, c.ml_away AS close_ml_away,
               c.total AS close_total,
               op.ml_home AS open_ml_home, op.ml_away AS open_ml_away,
               op.total AS open_total
        FROM games g
        JOIN LATERAL (
            SELECT * FROM model_predictions p
            WHERE p.game_pk = g.game_pk AND p.model_type = :m
            ORDER BY (p.model_version = 'daily_v1') DESC, p.created_at DESC
            LIMIT 1
        ) p ON TRUE
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
        WHERE g.is_final AND g.game_date >= current_date - :days
        ORDER BY g.game_date
    """), get_engine(), params={"m": PRIMARY, "days": days})
    if df.empty:
        return []

    # Corruption guard (same as scripts/benchmark_odds.py): pregame MLB win
    # probabilities live in roughly [0.20, 0.85]. An implausible closing
    # capture (in-game contamination) falls back to the opening line; games
    # with neither plausible ship no market fields.
    def no_vig_col(home_col: str, away_col: str) -> pd.Series:
        ok = df[home_col].notna() & df[away_col].notna()
        out = pd.Series(np.nan, index=df.index)
        if ok.any():
            out[ok] = _no_vig(df.loc[ok, home_col], df.loc[ok, away_col])
        return out

    p_close = no_vig_col("close_ml_home", "close_ml_away")
    p_open = no_vig_col("open_ml_home", "open_ml_away")
    close_ok = p_close.between(0.20, 0.85)
    open_ok = p_open.between(0.20, 0.85)
    df["market_p_home"] = np.where(close_ok, p_close,
                                   np.where(open_ok, p_open, np.nan))
    df["market_total"] = np.where(close_ok, df["close_total"],
                                  np.where(open_ok, df["open_total"], np.nan))
    df = df.drop(columns=["close_ml_home", "close_ml_away", "close_total",
                          "open_ml_home", "open_ml_away", "open_total"])
    return _clean(df)


@router.get("/api/public/pitchers")
def pitchers_board(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Probable starters for a date (default today) with season-to-date form
    and what our hitter model expects the opposing lineup to do in that game
    (per-hitter calls summed — the whole game, not just the starter's
    innings). Freshest probables win: the daily capture beats the backfill."""
    engine = get_engine()
    board = pd.read_sql(text("""
        WITH probs AS (
            SELECT DISTINCT ON (p.game_pk)
                   p.game_pk, p.home_pitcher_id, p.away_pitcher_id
            FROM probable_pitchers p
            JOIN games g USING (game_pk)
            WHERE g.game_date = COALESCE(CAST(:date AS date), current_date)
            ORDER BY p.game_pk, (p.source = 'daily') DESC, p.captured_at DESC
        )
        SELECT g.game_pk, g.game_date::text AS game_date, g.season,
               ht.abbrev AS home, at.abbrev AS away,
               x.pitcher_id, x.team, pl.full_name AS pitcher, pl.throws
        FROM probs p
        JOIN games g USING (game_pk)
        JOIN teams ht ON ht.team_id = g.home_team_id
        JOIN teams at ON at.team_id = g.away_team_id
        CROSS JOIN LATERAL (
            VALUES (p.home_pitcher_id, ht.abbrev), (p.away_pitcher_id, at.abbrev)
        ) AS x(pitcher_id, team)
        JOIN players pl ON pl.player_id = x.pitcher_id
        ORDER BY g.game_pk, x.team
    """), engine, params={"date": date})
    if board.empty:
        raise HTTPException(404, "no probable starters posted for that date")

    season = int(board["season"].iloc[0])
    stats = pd.read_sql(text("""
        SELECT pg.player_id AS pitcher_id,
               count(*) FILTER (WHERE pg.is_starter) AS starts,
               sum(pg.outs) AS outs, sum(pg.er) AS er, sum(pg.so) AS k,
               sum(pg.bb) AS bb, sum(pg.h) AS h
        FROM pitcher_game_lines pg
        JOIN games g USING (game_pk)
        WHERE g.is_final AND g.season = :season
          AND g.game_date < COALESCE(CAST(:date AS date), current_date)
          AND pg.player_id = ANY(:ids)
        GROUP BY 1
    """), engine, params={"season": season, "date": date,
                          "ids": [int(i) for i in board["pitcher_id"]]})
    ip = stats["outs"].fillna(0) / 3.0
    stats["ip"] = ip
    stats["era"] = np.where(ip > 0, stats["er"].fillna(0) / ip * 9, np.nan)
    stats["whip"] = np.where(ip > 0, (stats["bb"].fillna(0) + stats["h"].fillna(0)) / ip,
                             np.nan)
    stats["k9"] = np.where(ip > 0, stats["k"].fillna(0) / ip * 9, np.nan)
    stats = stats[["pitcher_id", "starts", "ip", "era", "whip", "k9"]]

    vs = pd.read_sql(text("""
        SELECT d.sp_id AS pitcher_id, d.game_pk, count(*) AS batters_predicted,
               sum(d.exp_h) AS opp_exp_h, sum(d.exp_k) AS opp_exp_k,
               sum(d.exp_hr) AS opp_exp_hr
        FROM (
            SELECT DISTINCT ON (bp.game_pk, bp.player_id) bp.*
            FROM batter_predictions bp
            WHERE bp.game_pk = ANY(:pks)
            ORDER BY bp.game_pk, bp.player_id,
                     (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
        ) d
        WHERE d.sp_id IS NOT NULL AND d.lineup_slot BETWEEN 1 AND 9
        GROUP BY 1, 2
    """), engine, params={"pks": [int(i) for i in board["game_pk"].unique()]})

    out = (board.drop(columns=["season"])
           .merge(stats, on="pitcher_id", how="left")
           .merge(vs, on=["game_pk", "pitcher_id"], how="left"))
    return _clean(out)


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
