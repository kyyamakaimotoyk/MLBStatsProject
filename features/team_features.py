"""Team-level feature builder (Phase 2): one row per game, HOME_/AWAY_/DIFF_
expansion, stamped with data_through_date = day before the game.

Point-in-time rules enforced here:
  - Rolling windows exclude ALL games on the game's own date (a nightcap may
    not see the matinee), implemented via searchsorted on dates, not shift().
  - Windows are scoped to (team, season); April rows are NaN-heavy on purpose
    (carrying prior-season form is a Phase 3 ablation, not a default).
  - The starting-pitcher block uses the ANNOUNCED probable (probable_pitchers),
    never the actual starter — using the actual starter is postgame knowledge.
  - Elo and park factors are point-in-time by construction in their tables.
  - `max_date` truncates every source query; scripts/test_leakage.py asserts
    that truncation does not change features for games before the cutoff.

Usage:
    python -m features.team_features --set-current
    python -m features.team_features --max-date 2024-06-30   # leakage test aid
"""

import argparse
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from core import features_io
from core.db import get_engine

log = logging.getLogger("team_features")

DAY = np.timedelta64(1, "D")


# ---------------------------------------------------------------- loading

def _load_games(max_date):
    sql = """
        SELECT g.game_pk, g.season, g.game_date, g.first_pitch_utc, g.game_type,
               g.home_team_id, g.away_team_id, g.venue_id, g.day_night,
               g.game_number, g.temp_f, g.wind_speed_mph,
               g.home_score, g.away_score
        FROM games g
        WHERE g.is_final AND g.home_score IS NOT NULL
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df.sort_values(["game_date", "first_pitch_utc", "game_pk"]).reset_index(drop=True)


def _load_offense(max_date):
    """Per (game_pk, side) offensive aggregates from Statcast."""
    sql = """
        SELECT s.game_pk,
               CASE WHEN s.inning_topbot = 'Top' THEN 'away' ELSE 'home' END AS side,
               SUM(s.woba_value::float8)  AS woba_num,
               SUM(s.woba_denom::float8)  AS woba_den,
               SUM(s.estimated_woba_using_speedangle::float8) AS xwoba_num,
               COUNT(s.estimated_woba_using_speedangle) AS bbe,
               COUNT(*) FILTER (WHERE s.events IN ('strikeout', 'strikeout_double_play')) AS so,
               COUNT(*) FILTER (WHERE s.events = 'walk') AS bb,
               COUNT(*) FILTER (WHERE s.events IS NOT NULL AND s.events <> '') AS pa
        FROM statcast_pitches s
        JOIN games g ON g.game_pk = s.game_pk
        WHERE g.is_final
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    sql += " GROUP BY 1, 2"
    return pd.read_sql(text(sql), get_engine(), params=params)


def _load_starts(max_date):
    """One row per start: boxscore rates + Statcast quality-against."""
    sql = """
        SELECT p.player_id AS pitcher_id, p.game_pk, g.game_date,
               p.batters_faced AS bf, p.so, p.bb, p.er, p.outs,
               sc.woba_num, sc.woba_den, sc.xwoba_num, sc.bbe
        FROM pitcher_game_lines p
        JOIN games g ON g.game_pk = p.game_pk
        LEFT JOIN (
            SELECT pitcher_id, game_pk,
                   SUM(woba_value::float8) AS woba_num, SUM(woba_denom::float8) AS woba_den,
                   SUM(estimated_woba_using_speedangle::float8) AS xwoba_num,
                   COUNT(estimated_woba_using_speedangle) AS bbe
            FROM statcast_pitches GROUP BY 1, 2
        ) sc ON sc.pitcher_id = p.player_id AND sc.game_pk = p.game_pk
        WHERE p.is_starter AND g.is_final
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df.sort_values(["pitcher_id", "game_date", "game_pk"]).reset_index(drop=True)


def _load_bullpen(max_date):
    sql = """
        SELECT p.team_id, g.game_date,
               SUM(p.pitches) AS pitches, SUM(p.er) AS er, SUM(p.outs) AS outs
        FROM pitcher_game_lines p
        JOIN games g ON g.game_pk = p.game_pk
        WHERE NOT p.is_starter AND g.is_final
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    sql += " GROUP BY 1, 2"
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df.sort_values(["team_id", "game_date"]).reset_index(drop=True)


def _load_simple(query: str) -> pd.DataFrame:
    return pd.read_sql(text(query), get_engine())


# ---------------------------------------------------------- rolling blocks

TEAM_ROLL_COLS = [
    "RUNS_PG_L10", "RUNS_PG_L30", "RA_PG_L10", "RA_PG_L30",
    "WOBA_L30", "XWOBA_CON_L30", "K_PCT_L30", "BB_PCT_L30",
    "N_PRIOR_GAMES", "REST_DAYS",
]


def _team_rolling(team_games: pd.DataFrame) -> dict:
    """(game_pk, team_id) -> rolling point-in-time stats."""
    out = {}
    grouped = team_games.sort_values(["game_date", "first_pitch_utc", "game_pk"]).groupby(
        ["team_id", "season"], sort=False
    )
    for (team_id, _season), grp in grouped:
        g = grp.reset_index(drop=True)
        dates = g["game_date"].to_numpy()
        rf = g["runs_for"].to_numpy(float)
        ra = g["runs_against"].to_numpy(float)
        nums = {c: g[c].fillna(0).to_numpy(float)
                for c in ("woba_num", "woba_den", "xwoba_num", "bbe", "so", "bb", "pa")}
        for i in range(len(g)):
            cut = int(np.searchsorted(dates, dates[i], side="left"))
            row = {"N_PRIOR_GAMES": cut, "GAME_NUM": i + 1}
            if cut > 0:
                lo10, lo30 = max(0, cut - 10), max(0, cut - 30)
                row["RUNS_PG_L10"] = rf[lo10:cut].mean()
                row["RUNS_PG_L30"] = rf[lo30:cut].mean()
                row["RA_PG_L10"] = ra[lo10:cut].mean()
                row["RA_PG_L30"] = ra[lo30:cut].mean()
                wd = nums["woba_den"][lo30:cut].sum()
                row["WOBA_L30"] = nums["woba_num"][lo30:cut].sum() / wd if wd else np.nan
                be = nums["bbe"][lo30:cut].sum()
                row["XWOBA_CON_L30"] = nums["xwoba_num"][lo30:cut].sum() / be if be else np.nan
                pa = nums["pa"][lo30:cut].sum()
                row["K_PCT_L30"] = nums["so"][lo30:cut].sum() / pa if pa else np.nan
                row["BB_PCT_L30"] = nums["bb"][lo30:cut].sum() / pa if pa else np.nan
                row["REST_DAYS"] = min(float((dates[i] - dates[cut - 1]) / DAY), 10.0)
            out[(g["game_pk"].iat[i], team_id)] = row
    return out


def _sp_lookup(starts: pd.DataFrame):
    """pitcher_id -> arrays; returns lookup(pitcher_id, game_date) -> SP dict."""
    book = {}
    for pid, grp in starts.groupby("pitcher_id", sort=False):
        g = grp.reset_index(drop=True)
        arrays = {c: np.concatenate([[0.0], np.nancumsum(g[c].to_numpy(float))])
                  for c in ("bf", "so", "bb", "er", "outs", "woba_num", "woba_den",
                            "xwoba_num", "bbe")}
        book[pid] = (g["game_date"].to_numpy(), arrays)

    def lookup(pid, game_date):
        if pid not in book:
            return {"SP_N_STARTS": 0}
        dates, cum = book[pid]
        hi = int(np.searchsorted(dates, game_date, side="left"))
        if hi == 0:
            return {"SP_N_STARTS": 0}
        lo = max(0, hi - 10)
        n = hi - lo
        s = {c: cum[c][hi] - cum[c][lo] for c in cum}
        row = {"SP_N_STARTS": hi,
               "SP_DAYS_REST": min(float((game_date - dates[hi - 1]) / DAY), 15.0),
               "SP_IP_PER_START_L10": s["outs"] / 3.0 / n}
        if s["bf"]:
            row["SP_K_PCT_L10"] = s["so"] / s["bf"]
            row["SP_BB_PCT_L10"] = s["bb"] / s["bf"]
        if s["outs"]:
            row["SP_ERA_L10"] = s["er"] / s["outs"] * 27.0
        if s["woba_den"]:
            row["SP_WOBA_AGAINST_L10"] = s["woba_num"] / s["woba_den"]
        if s["bbe"]:
            row["SP_XWOBA_CON_AGAINST_L10"] = s["xwoba_num"] / s["bbe"]
        return row

    return lookup


def _bullpen_lookup(bullpen: pd.DataFrame):
    book = {}
    for team_id, grp in bullpen.groupby("team_id", sort=False):
        g = grp.reset_index(drop=True)
        dates = g["game_date"].to_numpy()
        cums = {c: np.concatenate([[0.0], np.nancumsum(g[c].to_numpy(float))])
                for c in ("pitches", "er", "outs")}
        book[team_id] = (dates, cums)

    def lookup(team_id, game_date):
        if team_id not in book:
            return {}
        dates, cum = book[team_id]
        hi = int(np.searchsorted(dates, game_date, side="left"))
        lo3 = int(np.searchsorted(dates, game_date - 3 * DAY, side="left"))
        lo30 = int(np.searchsorted(dates, game_date - 30 * DAY, side="left"))
        row = {"BP_PITCHES_L3": cum["pitches"][hi] - cum["pitches"][lo3]}
        outs = cum["outs"][hi] - cum["outs"][lo30]
        if outs:
            row["BP_ERA_L30"] = (cum["er"][hi] - cum["er"][lo30]) / outs * 27.0
        return row

    return lookup


# ------------------------------------------------------------- assembly

SIDE_COLS = TEAM_ROLL_COLS + [
    "GAME_NUM", "BP_PITCHES_L3", "BP_ERA_L30",
    "SP_KNOWN", "SP_N_STARTS", "SP_K_PCT_L10", "SP_BB_PCT_L10", "SP_ERA_L10",
    "SP_WOBA_AGAINST_L10", "SP_XWOBA_CON_AGAINST_L10", "SP_IP_PER_START_L10",
    "SP_DAYS_REST", "SP_THROWS_L",
]
DIFF_COLS = [
    "RUNS_PG_L10", "RUNS_PG_L30", "RA_PG_L10", "RA_PG_L30",
    "WOBA_L30", "XWOBA_CON_L30", "K_PCT_L30", "BB_PCT_L30", "BP_ERA_L30",
    "SP_K_PCT_L10", "SP_BB_PCT_L10", "SP_ERA_L10", "SP_WOBA_AGAINST_L10",
]


def build_features(max_date: str | None = None) -> pd.DataFrame:
    games = _load_games(max_date)
    offense = _load_offense(max_date)
    starts = _load_starts(max_date)
    bullpen = _load_bullpen(max_date)
    log.info("loaded %d games, %d offense rows, %d starts", len(games), len(offense), len(starts))

    # Long frame: one row per team per game, with Statcast offense merged in.
    side_rows = []
    for side in ("home", "away"):
        part = games[["game_pk", "season", "game_date", "first_pitch_utc"]].copy()
        part["team_id"] = games[f"{side}_team_id"]
        part["runs_for"] = games[f"{side}_score"]
        part["runs_against"] = games["away_score" if side == "home" else "home_score"]
        part["side"] = side
        side_rows.append(part)
    team_games = pd.concat(side_rows, ignore_index=True).merge(
        offense, on=["game_pk", "side"], how="left"
    )
    team_roll = _team_rolling(team_games)
    sp = _sp_lookup(starts)
    bp = _bullpen_lookup(bullpen)

    probables = _load_simple("""
        SELECT game_pk, home_pitcher_id, away_pitcher_id
        FROM probable_pitchers WHERE source = 'backfill'
    """).set_index("game_pk")
    ratings = _load_simple(
        "SELECT game_pk, home_rating, away_rating, p_home FROM team_strength_pregame"
    ).set_index("game_pk")
    park = _load_simple("SELECT season, venue_id, pf_runs FROM park_factors") \
        .set_index(["season", "venue_id"])["pf_runs"]
    roof = _load_simple("SELECT venue_id, roof_type FROM venues").set_index("venue_id")["roof_type"]
    throws = _load_simple("SELECT player_id, throws FROM players").set_index("player_id")["throws"]

    rows = []
    for g in games.itertuples():
        row = {
            "game_pk": g.game_pk,
            "game_date": g.game_date.date(),
            "season": g.season,
            "data_through_date": (g.game_date - pd.Timedelta(days=1)).date(),
            "PARK_PF_RUNS": float(park.get((g.season, g.venue_id), 1.0)),
            "TEMP_F": g.temp_f,
            "WIND_SPEED_MPH": g.wind_speed_mph,
            "IS_OPEN_AIR": 1 if roof.get(g.venue_id) == "Open" else 0,
            "IS_NIGHT": 1 if g.day_night == "night" else 0,
            "IS_DOUBLEHEADER_G2": 1 if (g.game_number or 1) > 1 else 0,
            "TARGET_HOME_RUNS": g.home_score,
            "TARGET_AWAY_RUNS": g.away_score,
            "TARGET_MARGIN": g.home_score - g.away_score,
            "TARGET_TOTAL": g.home_score + g.away_score,
        }
        if g.game_pk in ratings.index:
            r = ratings.loc[g.game_pk]
            row["ELO_HOME"] = r["home_rating"]
            row["ELO_AWAY"] = r["away_rating"]
            row["ELO_DIFF"] = r["home_rating"] - r["away_rating"]
            row["ELO_P_HOME"] = r["p_home"]

        prob = probables.loc[g.game_pk] if g.game_pk in probables.index else None
        for side in ("home", "away"):
            prefix = side.upper() + "_"
            team_id = g.home_team_id if side == "home" else g.away_team_id
            side_vals = dict(team_roll.get((g.game_pk, team_id), {}))
            side_vals.update(bp(team_id, g.game_date.to_datetime64()))
            pid = prob[f"{side}_pitcher_id"] if prob is not None else None
            if pid is not None and not pd.isna(pid):
                side_vals["SP_KNOWN"] = 1
                side_vals.update(sp(int(pid), g.game_date.to_datetime64()))
                side_vals["SP_THROWS_L"] = 1 if throws.get(int(pid)) == "L" else 0
            else:
                side_vals["SP_KNOWN"] = 0
            for col in SIDE_COLS:
                row[prefix + col] = side_vals.get(col)
        for col in DIFF_COLS:
            h, a = row.get("HOME_" + col), row.get("AWAY_" + col)
            row["DIFF_" + col] = (h - a) if h is not None and a is not None else None
        rows.append(row)

    df = pd.DataFrame(rows)
    log.info("built %d rows x %d cols; NaN rate %.1f%%",
             len(df), df.shape[1],
             100 * df.isna().to_numpy().mean())
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set-current", action="store_true")
    ap.add_argument("--description", default="")
    ap.add_argument("--max-date", help="truncate all source data (leakage testing)")
    args = ap.parse_args()

    version = "v" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    df = build_features(max_date=args.max_date)
    features_io.write_snapshot(df, "team", version, args.description)
    log.info("wrote snapshot team/%s (%d rows)", version, len(df))
    if args.set_current:
        features_io.set_current("team", version)
        log.info("feature_set_current -> team/%s", version)


if __name__ == "__main__":
    main()
