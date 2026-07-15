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
               g.hp_umpire_id, g.home_score, g.away_score
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


def _group_arrays(g: pd.DataFrame) -> dict:
    return {
        "dates": g["game_date"].to_numpy(),
        "rf": g["runs_for"].to_numpy(float),
        "ra": g["runs_against"].to_numpy(float),
        "nums": {c: g[c].fillna(0).to_numpy(float)
                 for c in ("woba_num", "woba_den", "xwoba_num", "bbe", "so", "bb", "pa")},
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
               "LINEUP_DEV_WOBA", "LINEUP_MISSING_WOBA", "LINEUP_N_REG_OUT"]
SIDE_COLS = TEAM_ROLL_COLS + [
    "GAME_NUM", "BP_PITCHES_L3", "BP_ERA_L30",
    "SP_KNOWN", "SP_N_STARTS", "SP_K_PCT_L10", "SP_BB_PCT_L10", "SP_ERA_L10",
    "SP_WOBA_AGAINST_L10", "SP_XWOBA_CON_AGAINST_L10", "SP_IP_PER_START_L10",
    "SP_DAYS_REST", "SP_THROWS_L",
] + LINEUP_COLS
DIFF_COLS = [
    "RUNS_PG_L10", "RUNS_PG_L30", "RA_PG_L10", "RA_PG_L30",
    "WOBA_L30", "XWOBA_CON_L30", "K_PCT_L30", "BB_PCT_L30", "BP_ERA_L30",
    "SP_K_PCT_L10", "SP_BB_PCT_L10", "SP_ERA_L10", "SP_WOBA_AGAINST_L10",
    "LINEUP_WOBA", "LINEUP_K_RATE", "LINEUP_BB_RATE", "LINEUP_HR_RATE",
    "LINEUP_XWOBA_CON", "LINEUP_DEV_WOBA", "LINEUP_MISSING_WOBA",
    "LINEUP_N_REG_OUT",
]

# Linear wOBA weights (league-era constants) and expected PAs by lineup slot.
WOBA_WEIGHTS = {"BB": 0.69, "HBP": 0.72, "1B": 0.89, "2B": 1.27, "3B": 1.62, "HR": 2.10}
SLOT_PA_WEIGHTS = {1: 4.65, 2: 4.55, 3: 4.43, 4: 4.33, 5: 4.22,
                   6: 4.11, 7: 3.99, 8: 3.87, 9: 3.75}


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
    # deviation from the expanding league wOBA at that date (E5b)
    lg = {d: float(sum(prior(d)[CLASSES.index(c)] * wt
                       for c, wt in WOBA_WEIGHTS.items()))
          for d in b["game_date"].unique()}
    b["woba_dev"] = b["woba"] - b["game_date"].map(lg)

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
    team_roll = _team_rolling(team_games, cross_season=cross_season)
    sp = _sp_lookup(starts)
    bp = _bullpen_lookup(bullpen)
    lineup = _lineup_strength(max_date)

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
            side_vals.update(lineup.get((g.game_pk, team_id), {}))
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


def lineup_strength_asof(asof_date: str, projected: pd.DataFrame) -> dict:
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
    b["woba_dev"] = b["woba"] - lg_woba
    b = b.set_index("batter_id")

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
                          lineups: pd.DataFrame | None = None) -> pd.DataFrame:
    """Feature rows for UNPLAYED games, using only data through asof_date.

    slate columns: game_pk, game_date, season, home_team_id, away_team_id,
    venue_id, day_night, game_number, home_probable_id, away_probable_id.
    Weather is unknown pregame and left NaN (forecast integration is a queued
    upgrade); everything else matches build_features() column-for-column.
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

    team_at = _team_date_lookup(team_games)
    sp = _sp_lookup(starts)
    bp = _bullpen_lookup(bullpen)
    lineup_vals = lineup_strength_asof(asof_date, lineups) if lineups is not None else {}
    ratings, last_season = team_rating.current_state(asof_date)
    park = _load_simple("SELECT season, venue_id, pf_runs FROM park_factors") \
        .set_index(["season", "venue_id"])["pf_runs"]
    roof = _load_simple("SELECT venue_id, roof_type FROM venues").set_index("venue_id")["roof_type"]
    throws = _load_simple("SELECT player_id, throws FROM players").set_index("player_id")["throws"]

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
            "TEMP_F": np.nan,
            "WIND_SPEED_MPH": np.nan,
            "IS_OPEN_AIR": 1 if roof.get(g.venue_id) == "Open" else 0,
            "IS_NIGHT": 1 if g.day_night == "night" else 0,
            "IS_DOUBLEHEADER_G2": 1 if (g.game_number or 1) > 1 else 0,
            # unknown pregame; flag-gated columns kept for schema consistency
            "UMP_K_FACTOR": np.nan,
            "WIND_OUT_MPH": np.nan,
            "ELO_HOME": rh, "ELO_AWAY": ra,
            "ELO_DIFF": rh - ra, "ELO_P_HOME": p_home,
        }
        for side in ("home", "away"):
            prefix = side.upper() + "_"
            team_id = g.home_team_id if side == "home" else g.away_team_id
            side_vals = team_at(team_id, g.season, game_date.to_datetime64())
            side_vals.update(bp(team_id, game_date.to_datetime64()))
            side_vals.update(lineup_vals.get((g.game_pk, team_id), {}))
            pid = getattr(g, f"{side}_probable_id")
            if pid is not None and not pd.isna(pid):
                side_vals["SP_KNOWN"] = 1
                side_vals.update(sp(int(pid), game_date.to_datetime64()))
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
