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
               g.game_number, g.temp_f, g.wind_speed_mph, g.wind_dir,
               g.hp_umpire_id, g.scheduled_innings, g.home_score, g.away_score
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
               COUNT(*) FILTER (WHERE s.events IS NOT NULL AND s.events <> '') AS pa,
               -- B9a defense inputs: balls in play (HR excluded, BABIP
               -- convention), hits on BIP, and Statcast xBA on those BIP
               COUNT(*) FILTER (WHERE s.estimated_ba_using_speedangle IS NOT NULL
                                AND s.events <> 'home_run') AS bip,
               COUNT(*) FILTER (WHERE s.events IN ('single', 'double', 'triple')) AS hits_bip,
               SUM(s.estimated_ba_using_speedangle::float8)
                   FILTER (WHERE s.events <> 'home_run') AS xba_num
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


def _attach_against(team_games: pd.DataFrame, offense: pd.DataFrame) -> pd.DataFrame:
    """Merge the OPPOSING side's ball-in-play offense onto each team row —
    the fielding team's defense inputs (B9a). Shared by the historical build
    and the prediction path."""
    against = offense.rename(columns={"bip": "bip_ag", "hits_bip": "hits_bip_ag",
                                      "xba_num": "xba_ag"})
    against["side"] = against["side"].map({"home": "away", "away": "home"})
    return team_games.merge(
        against[["game_pk", "side", "bip_ag", "hits_bip_ag", "xba_ag"]],
        on=["game_pk", "side"], how="left")


def _group_arrays(g: pd.DataFrame) -> dict:
    return {
        "dates": g["game_date"].to_numpy(),
        "rf": g["runs_for"].to_numpy(float),
        "ra": g["runs_against"].to_numpy(float),
        "wins": (g["runs_for"] > g["runs_against"]).to_numpy(float),
        "nums": {c: g[c].fillna(0).to_numpy(float)
                 for c in ("woba_num", "woba_den", "xwoba_num", "bbe", "so", "bb", "pa",
                           "bip_ag", "hits_bip_ag", "xba_ag")},
    }


def _window_stats(arr: dict, cut: int, asof) -> dict:
    """Rolling stats over games strictly before position `cut` (all games on
    dates < asof). Single implementation shared by the historical build and
    the prediction path so the two can never drift."""
    row = {"N_PRIOR_GAMES": cut}
    if cut > 0:
        dates, rf, ra, nums = arr["dates"], arr["rf"], arr["ra"], arr["nums"]
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
        row["REST_DAYS"] = min(float((asof - dates[cut - 1]) / DAY), 10.0)
        # B9a defense: BABIP-against + xHits-saved (xBA minus actual hits per
        # BIP; positive = the defense converts more than expected), L30 + season
        for lo, tag in ((lo30, "_L30"), (0, "_SEASON")):
            bip = nums["bip_ag"][lo:cut].sum()
            hits = nums["hits_bip_ag"][lo:cut].sum()
            xba = nums["xba_ag"][lo:cut].sum()
            row[f"DEF_BABIP_AGAINST{tag}"] = hits / bip if bip else np.nan
            row[f"DEF_XHITS_SAVED{tag}"] = (xba - hits) / bip if bip else np.nan
        # season-to-date internals for the E9 prior blends and E14 Pyth/Log5 —
        # underscore keys are never emitted as columns (not in SIDE_COLS)
        pa_s = nums["pa"][:cut].sum()
        wd_s = nums["woba_den"][:cut].sum()
        be_s = nums["bbe"][:cut].sum()
        rs, ra_ = arr["rf"][:cut].sum(), arr["ra"][:cut].sum()
        row["_STD_RUNS_PG"] = arr["rf"][:cut].mean()
        row["_STD_RA_PG"] = arr["ra"][:cut].mean()
        row["_STD_WOBA"] = nums["woba_num"][:cut].sum() / wd_s if wd_s else np.nan
        row["_STD_XWOBA_CON"] = nums["xwoba_num"][:cut].sum() / be_s if be_s else np.nan
        row["_STD_K_PCT"] = nums["so"][:cut].sum() / pa_s if pa_s else np.nan
        row["_STD_BB_PCT"] = nums["bb"][:cut].sum() / pa_s if pa_s else np.nan
        row["_STD_WPCT"] = arr["wins"][:cut].mean()
        row["_STD_PYTH"] = (rs * rs / (rs * rs + ra_ * ra_)
                            if (rs or ra_) else np.nan)
    return row


def _team_rolling(team_games: pd.DataFrame, cross_season: bool = False) -> dict:
    """(game_pk, team_id) -> rolling point-in-time stats.

    cross_season=True (experiment E2): windows span season boundaries, so an
    April L30 pulls late-season form from the prior year instead of NaN.
    GAME_NUM stays season-scoped either way.
    """
    out = {}
    tg = team_games.sort_values(["game_date", "first_pitch_utc", "game_pk"]).copy()
    tg["_game_num"] = tg.groupby(["team_id", "season"]).cumcount() + 1
    keys = ["team_id"] if cross_season else ["team_id", "season"]
    for key, grp in tg.groupby(keys, sort=False):
        team_id = key[0] if isinstance(key, tuple) else key
        g = grp.reset_index(drop=True)
        arr = _group_arrays(g)
        for i in range(len(g)):
            cut = int(np.searchsorted(arr["dates"], arr["dates"][i], side="left"))
            row = _window_stats(arr, cut, arr["dates"][i])
            row["GAME_NUM"] = int(g["_game_num"].iat[i])
            out[(g["game_pk"].iat[i], team_id)] = row
    return out


# E9a/b + E14 (2026-07 cycle). Blend ballasts k in GAMES, converted from the
# alpha atlas (docs/alpha_atlas_2026-07.md, ~38 PA/game): K_PCT 515 PA -> ~13,
# BB_PCT 1265 PA -> ~33; wOBA/xwOBA-contact between (HIT k=2584 -> ~68, tempered
# to 45 since wOBA mixes fast K/BB with slow contact); runs/wpct/pyth use the
# design-review grid center 20. w = n/(n+k) on the season-to-date value.
PRIOR_KAPPA = 2.0 / 3.0   # Elo's carryover constant, the E9a precedent
BLEND_K = {"RUNS_PG": 20.0, "RA_PG": 20.0, "WOBA": 45.0, "XWOBA_CON": 45.0,
           "K_PCT": 13.0, "BB_PCT": 33.0}
_PRIOR_STATS = list(BLEND_K) + ["WPCT", "PYTH"]  # WPCT/PYTH stay internal (E14)


def _prior_book(team_games: pd.DataFrame) -> dict:
    """(team_id, season) -> the team's FULL PRIOR-SEASON rates, shrunk toward
    that prior season's league mean with kappa=2/3 (E9a). Keyed by the season
    the prior SERVES: book[(t, 2024)] holds shrunk 2023 rates. Seasons with no
    prior season in the data (2019) are simply absent -> NaN downstream, never
    a frame-derived fallback (the E5/ERA_PRIOR leakage lesson). Point-in-time
    is structural: under a mid-season max_date cutoff, the partial season's
    aggregates only ever serve NEXT-season rows, which the cutoff excludes."""
    g = team_games
    agg = g.groupby(["team_id", "season"]).agg(
        rf=("runs_for", "sum"), ra=("runs_against", "sum"),
        n=("runs_for", "size"), wins=("runs_for", lambda s: np.nan),  # placeholder
        woba_num=("woba_num", "sum"), woba_den=("woba_den", "sum"),
        xwoba_num=("xwoba_num", "sum"), bbe=("bbe", "sum"),
        so=("so", "sum"), bb=("bb", "sum"), pa=("pa", "sum"))
    agg["wins"] = g.assign(w=(g["runs_for"] > g["runs_against"]).astype(float)) \
        .groupby(["team_id", "season"])["w"].sum()
    agg = agg.reset_index()
    agg["RUNS_PG"] = agg["rf"] / agg["n"]
    agg["RA_PG"] = agg["ra"] / agg["n"]
    agg["WOBA"] = agg["woba_num"] / agg["woba_den"].replace(0, np.nan)
    agg["XWOBA_CON"] = agg["xwoba_num"] / agg["bbe"].replace(0, np.nan)
    agg["K_PCT"] = agg["so"] / agg["pa"].replace(0, np.nan)
    agg["BB_PCT"] = agg["bb"] / agg["pa"].replace(0, np.nan)
    agg["WPCT"] = agg["wins"] / agg["n"]
    agg["PYTH"] = agg["rf"] ** 2 / (agg["rf"] ** 2 + agg["ra"] ** 2)

    lg = agg.groupby("season")[_PRIOR_STATS].mean()
    book = {}
    for r in agg.itertuples():
        lg_row = lg.loc[r.season]
        book[(r.team_id, r.season + 1)] = {
            s: float(lg_row[s] + PRIOR_KAPPA * (getattr(r, s) - lg_row[s]))
            for s in _PRIOR_STATS if not pd.isna(getattr(r, s))
        }
    return book


def _prior_blend_vals(side_vals: dict, prior: dict | None) -> dict:
    """PRIOR_*/BLEND_* columns for one side (E9a/E9b) + internal blended
    strength for E14. Blend: w*season_to_date + (1-w)*prior, w = n/(n+k);
    no prior (2019 / expansion oddities) -> PRIOR_* NaN and BLEND_* falls
    back to the season-to-date value alone."""
    out = {}
    n = float(side_vals.get("N_PRIOR_GAMES") or 0)
    for stat in BLEND_K:
        pr = (prior or {}).get(stat, np.nan)
        cur = side_vals.get(f"_STD_{stat}", np.nan)
        cur = np.nan if cur is None else cur
        out[f"PRIOR_{stat}"] = pr
        w = n / (n + BLEND_K[stat])
        if pd.isna(pr):
            out[f"BLEND_{stat}"] = cur
        elif pd.isna(cur) or n == 0:
            out[f"BLEND_{stat}"] = pr
        else:
            out[f"BLEND_{stat}"] = w * cur + (1 - w) * pr
    # E14 internals: blended win% and Pythagorean expectation (k=20 games)
    for stat in ("WPCT", "PYTH"):
        pr = (prior or {}).get(stat, np.nan)
        cur = side_vals.get(f"_STD_{stat}", np.nan)
        cur = np.nan if cur is None else cur
        w = n / (n + 20.0)
        if pd.isna(pr):
            out[f"_S_{stat}"] = cur
        elif pd.isna(cur) or n == 0:
            out[f"_S_{stat}"] = pr
        else:
            out[f"_S_{stat}"] = w * cur + (1 - w) * pr
    return out


def _pyth_log5(home_vals: dict, away_vals: dict) -> dict:
    """E14 game-level columns from the two sides' blended strengths."""
    ph, pa_ = home_vals.get("_S_PYTH"), away_vals.get("_S_PYTH")
    wh, wa = home_vals.get("_S_WPCT"), away_vals.get("_S_WPCT")
    out = {"PYTH_EXP_DIFF": np.nan, "LOG5_P_HOME": np.nan}
    if ph is not None and pa_ is not None and not (pd.isna(ph) or pd.isna(pa_)):
        out["PYTH_EXP_DIFF"] = float(ph - pa_)
    if wh is not None and wa is not None and not (pd.isna(wh) or pd.isna(wa)):
        h = float(np.clip(wh, 0.2, 0.8))
        a = float(np.clip(wa, 0.2, 0.8))
        out["LOG5_P_HOME"] = h * (1 - a) / (h * (1 - a) + (1 - h) * a)
    return out


def _ump_factors(max_date) -> dict:
    """game_pk -> HP umpire strikeout factor (shrunken ump K rate before the
    game / expanding league K rate). 1.0 for unknown or debut umpires."""
    sql = """
        SELECT g.game_pk, g.game_date, g.hp_umpire_id, k.so, k.pa
        FROM games g
        JOIN (SELECT game_pk,
                     COUNT(*) FILTER (WHERE event_type IN
                         ('strikeout', 'strikeout_double_play')) AS so,
                     COUNT(*) AS pa
              FROM plays GROUP BY 1) k USING (game_pk)
        WHERE g.is_final AND g.hp_umpire_id IS NOT NULL
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(["game_date", "game_pk"]).reset_index(drop=True)

    daily = df.groupby("game_date")[["so", "pa"]].sum()
    lg_dates = daily.index.to_numpy()
    lg_so = np.concatenate([[0.0], daily["so"].to_numpy(float).cumsum()])
    lg_pa = np.concatenate([[0.0], daily["pa"].to_numpy(float).cumsum()])

    out = {}
    df = df.sort_values(["hp_umpire_id", "game_date", "game_pk"]).reset_index(drop=True)
    for _, grp in df.groupby("hp_umpire_id", sort=False):
        g = grp.reset_index(drop=True)
        dates = g["game_date"].to_numpy()
        so = np.concatenate([[0.0], g["so"].to_numpy(float).cumsum()])
        pa = np.concatenate([[0.0], g["pa"].to_numpy(float).cumsum()])
        for i in range(len(g)):
            cut = int(np.searchsorted(dates, dates[i], side="left"))
            li = int(np.searchsorted(lg_dates, dates[i], side="left"))
            league_rate = lg_so[li] / lg_pa[li] if lg_pa[li] > 5000 else None
            if league_rate and cut:
                n_games = cut
                ump_rate = so[cut] / pa[cut]
                shrunk = (ump_rate * n_games + league_rate * 30) / (n_games + 30)
                out[g["game_pk"].iat[i]] = shrunk / league_rate
            else:
                out[g["game_pk"].iat[i]] = 1.0
    return out


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return float(2 * 6371.0 * np.arcsin(np.sqrt(a)))


def _travel_lookup(games: pd.DataFrame):
    """Travel burden from the team's PREVIOUS final game (E8e): great-circle
    km and signed time-zone shift approximated from longitude (+ = eastward).
    Season-scoped — a team's first game of the season is NaN. One
    implementation shared by the historical build and the prediction path.
    Returns lookup(team_id, season, date64, venue_id) -> dict."""
    coords = _load_simple(
        "SELECT venue_id, latitude, longitude FROM venues").set_index("venue_id")
    lat = coords["latitude"].to_dict()
    lon = coords["longitude"].to_dict()

    side_rows = []
    for side in ("home", "away"):
        part = games[["game_pk", "season", "game_date", "first_pitch_utc",
                      "venue_id"]].copy()
        part["team_id"] = games[f"{side}_team_id"]
        side_rows.append(part)
    tg = pd.concat(side_rows, ignore_index=True).sort_values(
        ["game_date", "first_pitch_utc", "game_pk"])
    book = {}
    for (team_id, season), grp in tg.groupby(["team_id", "season"], sort=False):
        book[(team_id, season)] = (grp["game_date"].to_numpy(),
                                   grp["venue_id"].to_numpy())

    def lookup(team_id, season, date64, venue_id) -> dict:
        out = {"TRAVEL_KM": np.nan, "TRAVEL_TZ_DELTA": np.nan}
        arr = book.get((team_id, season))
        if arr is None:
            return out
        dates, venues = arr
        cut = int(np.searchsorted(dates, date64, side="left"))
        if cut == 0:
            return out
        prev = venues[cut - 1]
        vals = (lat.get(prev), lon.get(prev), lat.get(venue_id), lon.get(venue_id))
        if any(v is None or pd.isna(v) for v in vals):
            return out
        out["TRAVEL_KM"] = _haversine_km(vals[0], vals[1], vals[2], vals[3])
        out["TRAVEL_TZ_DELTA"] = float((vals[3] - vals[1]) / 15.0)
        return out

    return lookup


def _venue_env_lookup(games: pd.DataFrame):
    """Rolling venue scoring environment (E8f): mean total runs over the last
    40 final 9-inning-scheduled games at the venue, divided by the league mean
    total over the trailing 365 days. NaN below 10 venue games or 200 league
    games. Point-in-time via searchsorted (games on the date itself excluded).
    Returns lookup(venue_id, date64) -> float."""
    g = games[(games["scheduled_innings"].fillna(9) != 7)
              & games["home_score"].notna()].sort_values(
        ["game_date", "first_pitch_utc", "game_pk"])
    totals = (g["home_score"] + g["away_score"]).astype(float)
    daily = pd.DataFrame({"d": g["game_date"].to_numpy(), "t": totals.to_numpy()}) \
        .groupby("d")["t"].agg(["sum", "count"])
    ld = daily.index.to_numpy()
    csum = np.concatenate([[0.0], daily["sum"].to_numpy().cumsum()])
    ccnt = np.concatenate([[0.0], daily["count"].to_numpy().cumsum()])

    vbook = {}
    for venue_id, grp in g.groupby("venue_id", sort=False):
        vbook[venue_id] = (grp["game_date"].to_numpy(),
                           (grp["home_score"] + grp["away_score"]).to_numpy(float))

    def lookup(venue_id, date64) -> float:
        arr = vbook.get(venue_id)
        if arr is None:
            return np.nan
        vd, vt = arr
        cut = int(np.searchsorted(vd, date64, side="left"))
        if cut < 10:
            return np.nan
        vmean = vt[max(0, cut - 40):cut].mean()
        hi = int(np.searchsorted(ld, date64, side="left"))
        lo = int(np.searchsorted(ld, date64 - np.timedelta64(365, "D"), side="left"))
        n = ccnt[hi] - ccnt[lo]
        if n < 200:
            return np.nan
        lmean = (csum[hi] - csum[lo]) / n
        return float(vmean / lmean) if lmean else np.nan

    return lookup


def _team_date_lookup(team_games: pd.DataFrame):
    """(team_id, season, date) -> the same rolling stats, for UNPLAYED games."""
    book = {}
    grouped = team_games.sort_values(["game_date", "first_pitch_utc", "game_pk"]).groupby(
        ["team_id", "season"], sort=False
    )
    for (team_id, season), grp in grouped:
        book[(team_id, season)] = _group_arrays(grp.reset_index(drop=True))

    def lookup(team_id, season, date64) -> dict:
        arr = book.get((team_id, season))
        if arr is None:
            return {"N_PRIOR_GAMES": 0, "GAME_NUM": 1}
        cut = int(np.searchsorted(arr["dates"], date64, side="left"))
        row = _window_stats(arr, cut, date64)
        row["GAME_NUM"] = cut + 1
        return row

    return lookup


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


SP_STUFF_MIN_PITCHES = 80     # the primer's stabilization claim
SP_STUFF_WINDOW = 1500        # ~15 starts; crosses season boundaries by design
                              # (process metrics are sticky year-over-year,
                              # unlike the season-scoped results rates)


def _sp_stuff_lookup(max_date):
    """pitcher_id -> as-of mean predicted run values from pitch_stuff_games
    (E15, flag-gated 'sp_stuff'). Window = the trailing games covering the
    last ~SP_STUFF_WINDOW scored pitches; NaN below SP_STUFF_MIN_PITCHES.
    The table is point-in-time by construction (season S scored by models
    trained on < S), so max_date truncation is a plain date filter."""
    sql = "SELECT pitcher_id, game_date, n_pitches, stuff_rv, loc_rv, pitch_rv " \
          "FROM pitch_stuff_games"
    params = {}
    if max_date:
        sql += " WHERE game_date <= :max_date"
        params["max_date"] = max_date
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(["pitcher_id", "game_date"]).reset_index(drop=True)
    book = {}
    for pid, grp in df.groupby("pitcher_id", sort=False):
        n = grp["n_pitches"].to_numpy(float)
        cums = {"n": np.concatenate([[0.0], n.cumsum()])}
        for c in ("stuff_rv", "loc_rv", "pitch_rv"):
            cums[c] = np.concatenate(
                [[0.0], np.nancumsum(grp[c].to_numpy(float) * n)])
        book[pid] = (grp["game_date"].to_numpy(), cums)

    def lookup(pid, date64) -> dict:
        entry = book.get(pid)
        if entry is None:
            return {}
        dates, cum = entry
        hi = int(np.searchsorted(dates, date64, side="left"))
        if hi == 0:
            return {}
        lo = int(np.searchsorted(cum["n"], cum["n"][hi] - SP_STUFF_WINDOW,
                                 side="left"))
        lo = min(lo, hi - 1)
        n = cum["n"][hi] - cum["n"][lo]
        if n < SP_STUFF_MIN_PITCHES:
            return {}
        return {"SP_STUFF_RV": (cum["stuff_rv"][hi] - cum["stuff_rv"][lo]) / n,
                "SP_LOC_RV": (cum["loc_rv"][hi] - cum["loc_rv"][lo]) / n,
                "SP_PITCH_RV": (cum["pitch_rv"][hi] - cum["pitch_rv"][lo]) / n}

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

LINEUP_COLS = ["LINEUP_WOBA", "LINEUP_K_RATE", "LINEUP_BB_RATE",
               "LINEUP_HR_RATE", "LINEUP_XWOBA_CON", "LINEUP_SAMPLE_PA",
               "LINEUP_DEV_WOBA", "LINEUP_MISSING_WOBA", "LINEUP_N_REG_OUT",
               "LINEUP_VS_HAND_WOBA", "LINEUP_VS_HAND_DEV",
               "LINEUP_SAME_HAND_SHARE",
               "LINEUP_XR"]  # 2026-07 Wave 2, flag-gated 'lineup_xr'
# 2026-07 cycle Wave 2 blocks (all flag-gated off by default)
PRIOR_COLS = ["PRIOR_RUNS_PG", "PRIOR_RA_PG", "PRIOR_WOBA", "PRIOR_XWOBA_CON",
              "PRIOR_K_PCT", "PRIOR_BB_PCT"]
BLEND_COLS = ["BLEND_RUNS_PG", "BLEND_RA_PG", "BLEND_WOBA", "BLEND_XWOBA_CON",
              "BLEND_K_PCT", "BLEND_BB_PCT"]
DEF_COLS = ["DEF_BABIP_AGAINST_L30", "DEF_BABIP_AGAINST_SEASON",
            "DEF_XHITS_SAVED_L30", "DEF_XHITS_SAVED_SEASON"]
SP_STUFF_COLS = ["SP_STUFF_RV", "SP_LOC_RV", "SP_PITCH_RV"]  # E15, flag 'sp_stuff'
SIDE_COLS = TEAM_ROLL_COLS + [
    "GAME_NUM", "BP_PITCHES_L3", "BP_ERA_L30",
    "SP_KNOWN", "SP_N_STARTS", "SP_K_PCT_L10", "SP_BB_PCT_L10", "SP_ERA_L10",
    "SP_WOBA_AGAINST_L10", "SP_XWOBA_CON_AGAINST_L10", "SP_IP_PER_START_L10",
    "SP_DAYS_REST", "SP_THROWS_L",
    "TRAVEL_KM", "TRAVEL_TZ_DELTA",  # E8e, flag-gated 'travel'
] + SP_STUFF_COLS + PRIOR_COLS + BLEND_COLS + DEF_COLS + LINEUP_COLS
DIFF_COLS = [
    "RUNS_PG_L10", "RUNS_PG_L30", "RA_PG_L10", "RA_PG_L30",
    "WOBA_L30", "XWOBA_CON_L30", "K_PCT_L30", "BB_PCT_L30", "BP_ERA_L30",
    "SP_K_PCT_L10", "SP_BB_PCT_L10", "SP_ERA_L10", "SP_WOBA_AGAINST_L10",
    "TRAVEL_KM", "TRAVEL_TZ_DELTA",
    "LINEUP_WOBA", "LINEUP_K_RATE", "LINEUP_BB_RATE", "LINEUP_HR_RATE",
    "LINEUP_XWOBA_CON", "LINEUP_DEV_WOBA", "LINEUP_MISSING_WOBA",
    "LINEUP_N_REG_OUT", "LINEUP_VS_HAND_WOBA", "LINEUP_VS_HAND_DEV",
    "LINEUP_SAME_HAND_SHARE",
    "LINEUP_XR",
] + SP_STUFF_COLS + PRIOR_COLS + BLEND_COLS + DEF_COLS

# Linear wOBA weights (league-era constants) and expected PAs by lineup slot.
WOBA_WEIGHTS = {"BB": 0.69, "HBP": 0.72, "1B": 0.89, "2B": 1.27, "3B": 1.62, "HR": 2.10}
SLOT_PA_WEIGHTS = {1: 4.65, 2: 4.55, 3: 4.43, 4: 4.33, 5: 4.22,
                   6: 4.11, 7: 3.99, 8: 3.87, 9: 3.75}

# ---- LINEUP_XR (2026-07 Wave 2): 24-state Markov expected runs -------------
# Bukiet 1997 structure with D'Esopo-Lefkowitz deterministic advancement:
# out/K no advance; BB/HBP force; 1B scores 2nd+3rd, 1st->2nd; 2B scores
# 2nd+3rd, 1st->3rd; 3B/HR clear. Known ~7% conservative bias (no steals,
# errors, or advancement on outs) — acceptable for a relative feature.
_XR_EVENTS = ("OUT", "K", "BB", "HBP", "1B", "2B", "3B", "HR")


def _xr_tables():
    """Per event: arrays over base-states 0..7 (bitmask 1st|2nd<<1|3rd<<2) of
    (new_base_state, runs_scored)."""
    tables = {}
    for ev in _XR_EVENTS:
        nb, runs = np.zeros(8, int), np.zeros(8, int)
        for b in range(8):
            b1, b2, b3 = b & 1, (b >> 1) & 1, (b >> 2) & 1
            if ev in ("OUT", "K"):
                nb[b], runs[b] = b, 0
            elif ev in ("BB", "HBP"):
                runs[b] = b1 & b2 & b3
                nb[b] = 1 | ((b1 | b2) << 1) | (((b1 & b2) | b3) << 2)
            elif ev == "1B":
                runs[b] = b2 + b3
                nb[b] = 1 | (b1 << 1)
            elif ev == "2B":
                runs[b] = b2 + b3
                nb[b] = 2 | (b1 << 2)
            elif ev == "3B":
                runs[b], nb[b] = b1 + b2 + b3, 4
            else:  # HR
                runs[b], nb[b] = b1 + b2 + b3 + 1, 0
        tables[ev] = (nb, runs)
    return tables


_XR_TABLES = _xr_tables()
_XR_MAX_PA = 30


def _markov_xr(slot_probs: list[np.ndarray]) -> float:
    """Expected runs over nine innings for a batting order of nine, each an
    8-vector of outcome probabilities ordered like _XR_EVENTS. The chain is
    solved once per leadoff slot (E[runs | leadoff] + the next-leadoff
    distribution), then nine innings chain the leadoff distribution forward."""
    probs = []
    for p in slot_probs:
        p = np.clip(np.asarray(p, float), 0.0, None)
        s = p.sum()
        probs.append(p / s if s > 0 else np.full(8, 1 / 8))

    exp_runs = np.zeros(9)
    next_lead = np.zeros((9, 9))
    for lead in range(9):
        dist = np.zeros((3, 8))
        dist[0, 0] = 1.0
        for t in range(_XR_MAX_PA):
            live = dist.sum()
            if live < 1e-4:
                break
            p8 = probs[(lead + t) % 9]
            new = np.zeros((3, 8))
            absorbed = 0.0
            for ei, ev in enumerate(_XR_EVENTS):
                pe = p8[ei]
                if pe <= 0:
                    continue
                nb, runs = _XR_TABLES[ev]
                if ev in ("OUT", "K"):
                    for o in range(3):
                        mass = dist[o] * pe
                        if o < 2:
                            new[o + 1] += mass
                        else:
                            absorbed += mass.sum()
                else:
                    for o in range(3):
                        mass = dist[o] * pe
                        exp_runs[lead] += float((mass * runs).sum())
                        np.add.at(new[o], nb, mass)
            next_lead[lead, (lead + t + 1) % 9] += absorbed
            dist = new
        leftover = dist.sum()  # chain cap: treat as inning over, no more runs
        if leftover > 0:
            next_lead[lead, (lead + _XR_MAX_PA) % 9] += leftover

    lead_dist = np.zeros(9)
    lead_dist[0] = 1.0
    total = 0.0
    for _ in range(9):
        total += float(lead_dist @ exp_runs)
        lead_dist = lead_dist @ next_lead
    return total


def _lineup_strength(max_date) -> dict:
    """(game_pk, team_id) -> aggregates of the posted starting nine's shrunken
    rolling rates (experiment E5).

    Lineup composition is pregame-posted information — the same standing as
    announced probables. The rates come from features/batter_features.py and
    are point-in-time by construction (windows exclude the game's own date).
    """
    from features import batter_features as bf
    from features.batter_features import CLASSES

    comp = bf.build(max_date=max_date)
    prior = comp["league_prior"]
    b = comp["b_rates"].merge(comp["b_sc"], on=["batter_id", "game_pk"], how="left")
    game_dates = pd.read_sql(text(
        "SELECT game_pk, game_date, first_pitch_utc FROM games WHERE is_final"),
        get_engine())
    game_dates["game_date"] = pd.to_datetime(game_dates["game_date"])
    b = b.merge(game_dates[["game_pk", "game_date"]], on="game_pk")
    b["woba"] = sum(b[f"B_rate_{c}"] * wt for c, wt in WOBA_WEIGHTS.items())
    for h in ("L", "R"):  # E5c: vs-hand lineup wOBA
        b[f"woba_vs{h}"] = sum(b[f"B_rate_{c}_vs{h}"] * wt
                               for c, wt in WOBA_WEIGHTS.items())
    # deviation from the expanding league wOBA at that date (E5b)
    lg = {d: float(sum(prior(d)[CLASSES.index(c)] * wt
                       for c, wt in WOBA_WEIGHTS.items()))
          for d in b["game_date"].unique()}
    b["woba_dev"] = b["woba"] - b["game_date"].map(lg)
    # league 8-class vector per date, for filling LINEUP_XR's missing slots
    lg_vec = {pd.Timestamp(d): np.array([prior(d)[CLASSES.index(c)]
                                         for c in _XR_EVENTS])
              for d in b["game_date"].unique()}

    # as-of lookup: a player's latest deviation strictly before a date
    dev_book = {}
    b_sorted = b.sort_values(["batter_id", "game_date"])
    for pid, grp in b_sorted.groupby("batter_id", sort=False):
        dev_book[pid] = (grp["game_date"].to_numpy(), grp["woba_dev"].to_numpy(float))

    def dev_asof(pid, date64) -> float:
        if pid not in dev_book:
            return 0.0
        dates, devs = dev_book[pid]
        i = int(np.searchsorted(dates, date64, side="left"))
        return float(devs[i - 1]) if i else 0.0

    lineups = pd.read_sql(text("""
        SELECT game_pk, player_id, team_id, batting_order
        FROM lineups WHERE batting_order BETWEEN 1 AND 9
    """), get_engine())
    df = lineups.merge(b, left_on=["player_id", "game_pk"],
                       right_on=["batter_id", "game_pk"], how="inner")
    df = df.merge(game_dates[["game_pk", "first_pitch_utc"]], on="game_pk")
    df["w"] = df["batting_order"].map(SLOT_PA_WEIGHTS)

    # E5c: the opposing probable's hand per (game, team) and batter handedness
    players_hand = pd.read_sql(text("SELECT player_id, bats, throws FROM players"),
                               get_engine())
    throws_map = players_hand.set_index("player_id")["throws"]
    bats_map = players_hand.set_index("player_id")["bats"]
    prob = pd.read_sql(text("""
        SELECT p.game_pk, g.home_team_id, g.away_team_id,
               p.home_pitcher_id, p.away_pitcher_id
        FROM probable_pitchers p JOIN games g USING (game_pk)
        WHERE p.source = 'backfill'
    """), get_engine())
    opp_hand = {}
    for r in prob.itertuples():
        if not pd.isna(r.away_pitcher_id):
            opp_hand[(r.game_pk, r.home_team_id)] = throws_map.get(int(r.away_pitcher_id))
        if not pd.isna(r.home_pitcher_id):
            opp_hand[(r.game_pk, r.away_team_id)] = throws_map.get(int(r.home_pitcher_id))
    df["bats"] = df["player_id"].map(bats_map)

    src = {"LINEUP_WOBA": "woba", "LINEUP_K_RATE": "B_rate_K",
           "LINEUP_BB_RATE": "B_rate_BB", "LINEUP_HR_RATE": "B_rate_HR",
           "LINEUP_XWOBA_CON": "B_XWOBA_CON", "LINEUP_SAMPLE_PA": "B_pa"}
    out = {}
    for (game_pk, team_id), grp in df.groupby(["game_pk", "team_id"], sort=False):
        w = grp["w"].to_numpy(float)
        row = {}
        for feat, col in src.items():
            v = grp[col].to_numpy(float)
            m = ~np.isnan(v)
            row[feat] = float((v[m] * w[m]).sum() / w[m].sum()) if m.any() else np.nan
        # E5b: slot-PA-weighted SUM of deviations — magnitude preserved
        dev = grp["woba_dev"].to_numpy(float)
        m = ~np.isnan(dev)
        row["LINEUP_DEV_WOBA"] = float((dev[m] * w[m]).sum()) if m.any() else np.nan
        # E5c: platoon block vs the opposing probable's hand
        hand = opp_hand.get((game_pk, team_id))
        if hand in ("L", "R"):
            v = grp[f"woba_vs{hand}"].to_numpy(float)
            m = ~np.isnan(v)
            lg_here = float(grp["game_date"].map(lg).iloc[0])
            row["LINEUP_VS_HAND_WOBA"] = (float((v[m] * w[m]).sum() / w[m].sum())
                                          if m.any() else np.nan)
            row["LINEUP_VS_HAND_DEV"] = (float(((v[m] - lg_here) * w[m]).sum())
                                         if m.any() else np.nan)
            same = (grp["bats"] == hand).to_numpy(float)
            row["LINEUP_SAME_HAND_SHARE"] = float((same * w).sum() / w.sum())
        else:
            row["LINEUP_VS_HAND_WOBA"] = np.nan
            row["LINEUP_VS_HAND_DEV"] = np.nan
            row["LINEUP_SAME_HAND_SHARE"] = np.nan
        # LINEUP_XR (flag-gated 'lineup_xr'): Markov expected runs of the
        # posted nine; slots missing shrunken rates fall back to the league
        # vector at that date
        vec = lg_vec.get(pd.Timestamp(grp["game_date"].iloc[0]))
        if vec is not None:
            rate_cols = [f"B_rate_{c}" for c in _XR_EVENTS]
            by_slot = {}
            for slot, rates in zip(grp["batting_order"], grp[rate_cols].to_numpy()):
                if not np.isnan(rates).any():
                    by_slot[int(slot)] = rates
            row["LINEUP_XR"] = _markov_xr(
                [by_slot.get(s, vec) for s in range(1, 10)])
        else:
            row["LINEUP_XR"] = np.nan
        out[(game_pk, team_id)] = row

    # E5b missing-regular indicator: regulars = >=60% of the team's previous
    # 15 posted lineups (all strictly past information); their absence today,
    # weighted by appearance share and their as-of deviation.
    hist = df[["game_pk", "game_date", "first_pitch_utc", "team_id", "player_id"]]
    ordered = hist.sort_values(["game_date", "first_pitch_utc", "game_pk"])
    for team_id, grp in ordered.groupby("team_id", sort=False):
        entries = [(pk, d, set(g["player_id"]))
                   for (pk, d), g in grp.groupby(["game_pk", "game_date"], sort=False)]
        entries.sort(key=lambda e: (e[1], e[0]))
        for i, (pk, date, players) in enumerate(entries):
            window = entries[max(0, i - 15):i]
            row = out.get((pk, team_id))
            if row is None:
                continue
            if len(window) < 5:
                row["LINEUP_MISSING_WOBA"] = np.nan
                row["LINEUP_N_REG_OUT"] = np.nan
                continue
            counts: dict = {}
            for _, _, past in window:
                for p in past:
                    counts[p] = counts.get(p, 0) + 1
            missing_val, n_out = 0.0, 0
            for p, cnt in counts.items():
                share = cnt / len(window)
                if share >= 0.6 and p not in players:
                    n_out += 1
                    missing_val += share * dev_asof(p, date.to_datetime64())
            row["LINEUP_MISSING_WOBA"] = missing_val
            row["LINEUP_N_REG_OUT"] = n_out
    log.info("lineup strength computed for %d team-games", len(out))
    return out


def build_features(max_date: str | None = None, cross_season: bool = False) -> pd.DataFrame:
    games = _load_games(max_date)
    offense = _load_offense(max_date)
    starts = _load_starts(max_date)
    bullpen = _load_bullpen(max_date)
    ump = _ump_factors(max_date)
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
    team_games = _attach_against(team_games, offense)
    team_roll = _team_rolling(team_games, cross_season=cross_season)
    prior_book = _prior_book(team_games)
    sp = _sp_lookup(starts)
    sp_stuff = _sp_stuff_lookup(max_date)
    bp = _bullpen_lookup(bullpen)
    lineup = _lineup_strength(max_date)
    travel = _travel_lookup(games)
    venue_env = _venue_env_lookup(games)

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
        # 2020-21 seven-inning doubleheaders: deflated totals must not become
        # training targets. They still contribute to rolling-form inputs
        # above (a small, unavoidable bias confined to those seasons).
        if g.scheduled_innings == 7:
            continue
        wd = g.wind_dir if isinstance(g.wind_dir, str) else ""
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
            "UMP_K_FACTOR": ump.get(g.game_pk, 1.0),
            "WIND_OUT_MPH": (
                (1 if "Out" in wd else -1 if "In" in wd else 0)
                * (0 if pd.isna(g.wind_speed_mph) else g.wind_speed_mph)
                * (1 if roof.get(g.venue_id) == "Open" else 0)
            ),
            "VENUE_ENV_L40": venue_env(g.venue_id, g.game_date.to_datetime64()),
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
        side_dicts = {}
        for side in ("home", "away"):
            prefix = side.upper() + "_"
            team_id = g.home_team_id if side == "home" else g.away_team_id
            side_vals = dict(team_roll.get((g.game_pk, team_id), {}))
            side_vals.update(bp(team_id, g.game_date.to_datetime64()))
            side_vals.update(lineup.get((g.game_pk, team_id), {}))
            side_vals.update(travel(team_id, g.season,
                                    g.game_date.to_datetime64(), g.venue_id))
            side_vals.update(_prior_blend_vals(
                side_vals, prior_book.get((team_id, g.season))))
            pid = prob[f"{side}_pitcher_id"] if prob is not None else None
            if pid is not None and not pd.isna(pid):
                side_vals["SP_KNOWN"] = 1
                side_vals.update(sp(int(pid), g.game_date.to_datetime64()))
                side_vals.update(sp_stuff(int(pid), g.game_date.to_datetime64()))
                side_vals["SP_THROWS_L"] = 1 if throws.get(int(pid)) == "L" else 0
            else:
                side_vals["SP_KNOWN"] = 0
            for col in SIDE_COLS:
                row[prefix + col] = side_vals.get(col)
            side_dicts[side] = side_vals
        row.update(_pyth_log5(side_dicts["home"], side_dicts["away"]))
        for col in DIFF_COLS:
            h, a = row.get("HOME_" + col), row.get("AWAY_" + col)
            row["DIFF_" + col] = (h - a) if h is not None and a is not None else None
        rows.append(row)

    df = pd.DataFrame(rows)
    log.info("built %d rows x %d cols; NaN rate %.1f%%",
             len(df), df.shape[1],
             100 * df.isna().to_numpy().mean())
    return df


def lineup_strength_asof(asof_date: str, projected: pd.DataFrame,
                         opp_hand: dict | None = None) -> dict:
    """(game_pk, team_id) -> LINEUP_* values for the daily path.

    projected columns: game_pk, team_id, player_id, lineup_slot — one lineup
    per (game, team), either the POSTED nine (once lineups land ~2-4h
    pregame) or the team's projection as fallback. Rates come from
    batter_features.build_asof (data through asof_date); missing-regular
    compares against the team's last 15 posted lineups. With a posted
    lineup this reflects today's actual scratches.
    """
    from features import batter_features as bf
    from features.batter_features import CLASSES

    comp = bf.build_asof(asof_date)
    pa = comp["pa"]
    league = pa["outcome"].value_counts(normalize=True).reindex(CLASSES).fillna(0)
    lg_woba = float(sum(league[c] * wt for c, wt in WOBA_WEIGHTS.items()))
    b = comp["b_rates"].merge(comp["b_sc"], on="batter_id", how="left")
    b["woba"] = sum(b[f"B_rate_{c}"] * wt for c, wt in WOBA_WEIGHTS.items())
    for h in ("L", "R"):
        b[f"woba_vs{h}"] = sum(b[f"B_rate_{c}_vs{h}"] * wt
                               for c, wt in WOBA_WEIGHTS.items())
    b["woba_dev"] = b["woba"] - lg_woba
    b = b.set_index("batter_id")
    bats_map = pd.read_sql(text("SELECT player_id, bats FROM players"),
                           get_engine()).set_index("player_id")["bats"]
    opp_hand = opp_hand or {}

    hist = pd.read_sql(text("""
        SELECT l.team_id, l.game_pk, g.game_date, l.player_id
        FROM lineups l JOIN games g USING (game_pk)
        WHERE g.is_final AND g.game_date <= :asof
          AND l.batting_order BETWEEN 1 AND 9
    """), get_engine(), params={"asof": asof_date})

    out = {}
    for (game_pk, team_id), nine in projected.groupby(["game_pk", "team_id"]):
        rows = nine.merge(b, left_on="player_id", right_index=True, how="left")
        w = rows["lineup_slot"].map(SLOT_PA_WEIGHTS).to_numpy(float)
        vals = {}
        for feat, col in (("LINEUP_WOBA", "woba"), ("LINEUP_K_RATE", "B_rate_K"),
                          ("LINEUP_BB_RATE", "B_rate_BB"), ("LINEUP_HR_RATE", "B_rate_HR"),
                          ("LINEUP_XWOBA_CON", "B_XWOBA_CON"), ("LINEUP_SAMPLE_PA", "B_pa")):
            v = rows[col].to_numpy(float)
            m = ~np.isnan(v)
            vals[feat] = float((v[m] * w[m]).sum() / w[m].sum()) if m.any() else np.nan
        dev = rows["woba_dev"].to_numpy(float)
        m = ~np.isnan(dev)
        vals["LINEUP_DEV_WOBA"] = float((dev[m] * w[m]).sum()) if m.any() else np.nan

        hand = opp_hand.get((game_pk, team_id))
        if hand in ("L", "R"):
            v = rows[f"woba_vs{hand}"].to_numpy(float)
            m = ~np.isnan(v)
            vals["LINEUP_VS_HAND_WOBA"] = (float((v[m] * w[m]).sum() / w[m].sum())
                                           if m.any() else np.nan)
            vals["LINEUP_VS_HAND_DEV"] = (float(((v[m] - lg_woba) * w[m]).sum())
                                          if m.any() else np.nan)
            same = (nine["player_id"].map(bats_map) == hand).to_numpy(float)
            vals["LINEUP_SAME_HAND_SHARE"] = float((same * w).sum() / w.sum())
        else:
            vals["LINEUP_VS_HAND_WOBA"] = np.nan
            vals["LINEUP_VS_HAND_DEV"] = np.nan
            vals["LINEUP_SAME_HAND_SHARE"] = np.nan

        # LINEUP_XR, serve path — league vector fills missing slots
        lg_vec8 = league.to_numpy(float)
        rate_cols = [f"B_rate_{c}" for c in _XR_EVENTS]
        by_slot = {}
        for slot, rates in zip(rows["lineup_slot"], rows[rate_cols].to_numpy()):
            if not np.isnan(rates).any():
                by_slot[int(slot)] = rates
        vals["LINEUP_XR"] = _markov_xr([by_slot.get(s, lg_vec8)
                                        for s in range(1, 10)])

        team_hist = hist[hist["team_id"] == team_id]
        recent = (team_hist.groupby(["game_pk", "game_date"])["player_id"].agg(set)
                  .reset_index().sort_values(["game_date", "game_pk"]).tail(15))
        if len(recent) < 5:
            vals["LINEUP_MISSING_WOBA"] = np.nan
            vals["LINEUP_N_REG_OUT"] = np.nan
        else:
            counts: dict = {}
            for past in recent["player_id"]:
                for p in past:
                    counts[p] = counts.get(p, 0) + 1
            today = set(nine["player_id"])
            missing_val, n_out = 0.0, 0
            for p, cnt in counts.items():
                share = cnt / len(recent)
                if share >= 0.6 and p not in today:
                    n_out += 1
                    if p in b.index:
                        missing_val += share * float(b.loc[p, "woba_dev"])
            vals["LINEUP_MISSING_WOBA"] = missing_val
            vals["LINEUP_N_REG_OUT"] = n_out
        out[(game_pk, team_id)] = vals
    return out


def build_prediction_rows(slate: pd.DataFrame, asof_date: str,
                          lineups: pd.DataFrame | None = None,
                          weather: dict | None = None) -> pd.DataFrame:
    """Feature rows for UNPLAYED games, using only data through asof_date.

    slate columns: game_pk, game_date, season, home_team_id, away_team_id,
    venue_id, day_night, game_number, home_probable_id, away_probable_id.
    TEMP_F/WIND_SPEED_MPH come from the E6b forecast dict when provided (NaN
    otherwise); UMP_K_FACTOR and WIND_OUT_MPH stay NaN pregame. Everything
    else matches build_features() column-for-column.
    """
    from features import team_rating

    offense = _load_offense(asof_date)
    starts = _load_starts(asof_date)
    bullpen = _load_bullpen(asof_date)
    games = _load_games(asof_date)

    side_rows = []
    for side in ("home", "away"):
        part = games[["game_pk", "season", "game_date", "first_pitch_utc"]].copy()
        part["team_id"] = games[f"{side}_team_id"]
        part["runs_for"] = games[f"{side}_score"]
        part["runs_against"] = games["away_score" if side == "home" else "home_score"]
        part["side"] = side
        side_rows.append(part)
    team_games = pd.concat(side_rows, ignore_index=True).merge(
        offense, on=["game_pk", "side"], how="left")
    team_games = _attach_against(team_games, offense)

    team_at = _team_date_lookup(team_games)
    prior_book = _prior_book(team_games)
    sp = _sp_lookup(starts)
    sp_stuff = _sp_stuff_lookup(asof_date)
    bp = _bullpen_lookup(bullpen)
    travel = _travel_lookup(games)
    venue_env = _venue_env_lookup(games)
    ratings, last_season = team_rating.current_state(asof_date)
    park = _load_simple("SELECT season, venue_id, pf_runs FROM park_factors") \
        .set_index(["season", "venue_id"])["pf_runs"]
    roof = _load_simple("SELECT venue_id, roof_type FROM venues").set_index("venue_id")["roof_type"]
    throws = _load_simple("SELECT player_id, throws FROM players").set_index("player_id")["throws"]

    lineup_vals = {}
    if lineups is not None:
        opp_hand = {}
        for g in slate.itertuples():
            if not pd.isna(g.away_probable_id):
                opp_hand[(g.game_pk, g.home_team_id)] = throws.get(int(g.away_probable_id))
            if not pd.isna(g.home_probable_id):
                opp_hand[(g.game_pk, g.away_team_id)] = throws.get(int(g.home_probable_id))
        lineup_vals = lineup_strength_asof(asof_date, lineups, opp_hand=opp_hand)

    rows = []
    for g in slate.itertuples():
        game_date = pd.Timestamp(g.game_date)
        rh, ra, p_home = team_rating.pregame(ratings, last_season,
                                             g.home_team_id, g.away_team_id, g.season)
        row = {
            "game_pk": g.game_pk,
            "game_date": game_date.date(),
            "season": g.season,
            "data_through_date": pd.Timestamp(asof_date).date(),
            "PARK_PF_RUNS": float(park.get((g.season, g.venue_id), 1.0)),
            # E6b: forecast when available; NaN otherwise (wind DIRECTION
            # still unavailable pregame — WIND_OUT_MPH stays NaN, see E6c)
            "TEMP_F": (weather or {}).get(g.game_pk, {}).get("temp_f", np.nan),
            "WIND_SPEED_MPH": (weather or {}).get(g.game_pk, {}).get("wind_mph", np.nan),
            "IS_OPEN_AIR": 1 if roof.get(g.venue_id) == "Open" else 0,
            "IS_NIGHT": 1 if g.day_night == "night" else 0,
            "IS_DOUBLEHEADER_G2": 1 if (g.game_number or 1) > 1 else 0,
            # unknown pregame; flag-gated columns kept for schema consistency
            "UMP_K_FACTOR": np.nan,
            "WIND_OUT_MPH": np.nan,
            "VENUE_ENV_L40": venue_env(g.venue_id, game_date.to_datetime64()),
            "ELO_HOME": rh, "ELO_AWAY": ra,
            "ELO_DIFF": rh - ra, "ELO_P_HOME": p_home,
        }
        side_dicts = {}
        for side in ("home", "away"):
            prefix = side.upper() + "_"
            team_id = g.home_team_id if side == "home" else g.away_team_id
            side_vals = team_at(team_id, g.season, game_date.to_datetime64())
            side_vals.update(bp(team_id, game_date.to_datetime64()))
            side_vals.update(lineup_vals.get((g.game_pk, team_id), {}))
            side_vals.update(travel(team_id, g.season,
                                    game_date.to_datetime64(), g.venue_id))
            side_vals.update(_prior_blend_vals(
                side_vals, prior_book.get((team_id, g.season))))
            pid = getattr(g, f"{side}_probable_id")
            if pid is not None and not pd.isna(pid):
                side_vals["SP_KNOWN"] = 1
                side_vals.update(sp(int(pid), game_date.to_datetime64()))
                side_vals.update(sp_stuff(int(pid), game_date.to_datetime64()))
                side_vals["SP_THROWS_L"] = 1 if throws.get(int(pid)) == "L" else 0
            else:
                side_vals["SP_KNOWN"] = 0
            for col in SIDE_COLS:
                row[prefix + col] = side_vals.get(col)
            side_dicts[side] = side_vals
        row.update(_pyth_log5(side_dicts["home"], side_dicts["away"]))
        for col in DIFF_COLS:
            h, a = row.get("HOME_" + col), row.get("AWAY_" + col)
            row["DIFF_" + col] = (h - a) if h is not None and a is not None else None
        rows.append(row)
    df = pd.DataFrame(rows)
    # A small slate with e.g. no announced probables yields all-None feature
    # columns -> object dtype, which LightGBM rejects. Force numeric.
    for c in df.columns:
        if c not in ("game_pk", "game_date", "season", "data_through_date"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set-current", action="store_true")
    ap.add_argument("--description", default="")
    ap.add_argument("--max-date", help="truncate all source data (leakage testing)")
    ap.add_argument("--cross-season", action="store_true", help="E2: windows span seasons")
    args = ap.parse_args()

    version = "v" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    df = build_features(max_date=args.max_date, cross_season=args.cross_season)
    features_io.write_snapshot(df, "team", version, args.description)
    log.info("wrote snapshot team/%s (%d rows)", version, len(df))
    if args.set_current:
        features_io.set_current("team", version)
        log.info("feature_set_current -> team/%s", version)


if __name__ == "__main__":
    main()
