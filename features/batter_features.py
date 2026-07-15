"""Per-PA feature builder for the batter-vs-pitcher model (Phase 4).

One training row per plate appearance (~740k over 2022-2025), outcome class in
TARGET_CLASS. Features are keyed per (player, game) — every PA a player has in
a game shares the same pregame values — with platoon variants selected per PA
by the opposing hand.

Point-in-time rules match features/team_features.py: rolling windows use
searchsorted on dates and exclude ALL games on the game's own date; league
priors are expanding (data strictly before the date). Raw batter-vs-pitcher
career history is deliberately NOT a feature (hard rule: it's noise) — the
matchup signal comes from shrunken profiles crossed with arsenal quality.

Shrinkage: empirical Bayes toward the expanding league rate,
rate = (count + W * league_rate) / (n + W), with W in PA units
(SHRINK_OVERALL for full profiles, SHRINK_SPLIT for noisier platoon splits).

Not snapshotted to the feature store: 740k rows x 40 features as JSONB is
~700MB per version on a t4g.micro. The build is deterministic from versioned
code + the DB, and scripts/test_leakage.py covers the same point-in-time
mechanics for the team builder; a batter-side leakage spot check lives in
validation/walkforward_batter.py --leakage-check.
"""

import logging

import numpy as np
import pandas as pd
from sqlalchemy import text

from core.db import get_engine

log = logging.getLogger("batter_features")

CLASSES = ["OUT", "K", "BB", "HBP", "1B", "2B", "3B", "HR"]
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}

EVENT_MAP = {
    "strikeout": "K", "strikeout_double_play": "K", "strikeout_triple_play": "K",
    "walk": "BB", "intent_walk": "BB",
    "hit_by_pitch": "HBP",
    "single": "1B", "double": "2B", "triple": "3B", "home_run": "HR",
    "field_out": "OUT", "force_out": "OUT", "grounded_into_double_play": "OUT",
    "double_play": "OUT", "triple_play": "OUT", "sac_fly": "OUT", "sac_bunt": "OUT",
    "sac_fly_double_play": "OUT", "sac_bunt_double_play": "OUT",
    "field_error": "OUT", "fielders_choice": "OUT", "fielders_choice_out": "OUT",
    "batter_interference": "OUT", "other_out": "OUT",
}

B_WINDOW = 60    # batter: last N games (~250 PA for a regular)
P_WINDOW = 30    # pitcher: last N appearances (~750 BF for a starter)
SHRINK_OVERALL = 150.0
SHRINK_SPLIT = 300.0

DAY = np.timedelta64(1, "D")

FASTBALLS = ("FF", "SI", "FC")
BREAKING = ("SL", "ST", "SV", "CU", "KC", "CS", "SC")
OFFSPEED = ("CH", "FS", "FO", "EP", "KN")
WHIFFS = ("swinging_strike", "swinging_strike_blocked")
SWINGS = WHIFFS + ("foul", "foul_tip", "hit_into_play")

from core.features import BATTER_META_COLS  # single source of truth for meta


def load_pa(max_date: str | None = None) -> pd.DataFrame:
    sql = """
        SELECT p.game_pk, p.at_bat_index, p.batter_id, p.pitcher_id,
               p.bat_side, p.pitch_hand, p.event_type, p.is_top,
               g.game_date, g.season, g.venue_id
        FROM plays p
        JOIN games g USING (game_pk)
        WHERE g.is_final
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    pa = pd.read_sql(text(sql), get_engine(), params=params)
    pa["game_date"] = pd.to_datetime(pa["game_date"])
    n0 = len(pa)
    pa["outcome"] = pa["event_type"].map(EVENT_MAP)
    pa = pa.dropna(subset=["outcome", "batter_id", "pitcher_id"]).copy()
    log.info("loaded %d PAs (%d dropped: non-PA events %.2f%%)",
             len(pa), n0 - len(pa), 100 * (n0 - len(pa)) / max(n0, 1))
    pa["is_home_batter"] = ~pa["is_top"].astype(bool)
    return pa.sort_values(["game_date", "game_pk", "at_bat_index"]).reset_index(drop=True)


def _per_game_counts(pa: pd.DataFrame, player_col: str, opp_hand_col: str) -> pd.DataFrame:
    """Per (player, game): PA count + per-class counts, overall and per opposing hand."""
    base = pa[[player_col, "game_pk", "game_date", "outcome", opp_hand_col]].copy()
    base["n"] = 1
    out = []
    for suffix, frame in (("", base),
                          ("_vsL", base[base[opp_hand_col] == "L"]),
                          ("_vsR", base[base[opp_hand_col] == "R"])):
        counts = frame.pivot_table(index=[player_col, "game_pk", "game_date"],
                                   columns="outcome", values="n",
                                   aggfunc="sum", fill_value=0)
        counts = counts.reindex(columns=CLASSES, fill_value=0)
        counts.columns = [f"{c}{suffix}" for c in counts.columns]
        counts[f"pa{suffix}"] = counts.sum(axis=1)
        out.append(counts)
    merged = pd.concat(out, axis=1).fillna(0).reset_index()
    return merged.sort_values([player_col, "game_date", "game_pk"]).reset_index(drop=True)


# Era-constant PA outcome rates (2020s MLB), CLASSES order. Used as the
# shrinkage prior before the expanding sample reaches 10k PAs — a FIXED
# constant, never derived from the loaded data: a full-sample fallback here
# leaked future information into early-season rows (caught by the leakage
# test when lineup-strength features surfaced it).
ERA_PRIOR = np.array([0.464, 0.223, 0.082, 0.012, 0.140, 0.043, 0.004, 0.032])


def _league_prior(pa: pd.DataFrame):
    """Expanding league class rates strictly before each date."""
    daily = pd.crosstab(pa["game_date"], pa["outcome"]).reindex(columns=CLASSES, fill_value=0)
    dates = daily.index.to_numpy()
    cum = np.vstack([np.zeros(len(CLASSES)), daily.to_numpy(float).cumsum(axis=0)])
    totals = cum.sum(axis=1)

    def prior(d) -> np.ndarray:
        i = int(np.searchsorted(dates, d, side="left"))
        if totals[i] < 10000:
            return ERA_PRIOR
        return cum[i] / totals[i]

    return prior


def _rolling_rates(per_game: pd.DataFrame, player_col: str, window: int,
                   prior, suffixes: tuple[str, ...] = ("", "_vsL", "_vsR")) -> pd.DataFrame:
    """Shrunken rolling class rates per (player, game).

    per_game must be sorted by (player, game_date, game_pk) — groups are then
    contiguous, so results are filled positionally into preallocated arrays
    (a dict-of-records here costs ~700MB for 200k batter-games).
    """
    n_rows = len(per_game)
    out = {f"rate_{c}{sfx}": np.full(n_rows, np.nan) for sfx in suffixes for c in CLASSES}
    out.update({f"pa{sfx}": np.zeros(n_rows) for sfx in suffixes})
    pos = 0
    for _, grp in per_game.groupby(player_col, sort=False):
        g = grp.reset_index(drop=True)
        dates = g["game_date"].to_numpy()
        cums = {f"{c}{sfx}": np.concatenate([[0.0], g[f"{c}{sfx}"].to_numpy(float).cumsum()])
                for sfx in suffixes for c in CLASSES + ["pa"]}
        for i in range(len(g)):
            cut = int(np.searchsorted(dates, dates[i], side="left"))
            lo = max(0, cut - window)
            league = prior(dates[i])
            row_pos = pos + i
            for sfx in suffixes:
                n = cums[f"pa{sfx}"][cut] - cums[f"pa{sfx}"][lo]
                w = SHRINK_OVERALL if sfx == "" else SHRINK_SPLIT
                out[f"pa{sfx}"][row_pos] = n
                for ci, c in enumerate(CLASSES):
                    cnt = cums[f"{c}{sfx}"][cut] - cums[f"{c}{sfx}"][lo]
                    out[f"rate_{c}{sfx}"][row_pos] = (cnt + w * league[ci]) / (n + w)
        pos += len(g)
    return pd.DataFrame({player_col: per_game[player_col].to_numpy(),
                         "game_pk": per_game["game_pk"].to_numpy(), **out})


def _batter_statcast(max_date):
    sql = """
        SELECT s.batter_id, s.game_pk, g.game_date,
               SUM(s.estimated_woba_using_speedangle::float8) AS xwoba_num,
               COUNT(s.estimated_woba_using_speedangle) AS bbe
        FROM statcast_pitches s JOIN games g USING (game_pk)
        WHERE g.is_final
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    sql += " GROUP BY 1, 2, 3"
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df.sort_values(["batter_id", "game_date", "game_pk"]).reset_index(drop=True)


def _pitcher_arsenal(max_date):
    sql = """
        SELECT s.pitcher_id, s.game_pk, g.game_date,
               COUNT(*) AS pitches,
               SUM(CASE WHEN s.pitch_type IN :fb THEN s.release_speed::float8 END) AS fb_velo_sum,
               COUNT(*) FILTER (WHERE s.pitch_type IN :fb AND s.release_speed IS NOT NULL) AS fb_n,
               COUNT(*) FILTER (WHERE s.pitch_type IN :brk) AS breaking_n,
               COUNT(*) FILTER (WHERE s.pitch_type IN :off) AS offspeed_n,
               COUNT(*) FILTER (WHERE s.description IN :whiffs) AS whiffs,
               COUNT(*) FILTER (WHERE s.description IN :swings) AS swings
        FROM statcast_pitches s JOIN games g USING (game_pk)
        WHERE g.is_final
    """
    from sqlalchemy import bindparam

    params = {"fb": list(FASTBALLS), "brk": list(BREAKING), "off": list(OFFSPEED),
              "whiffs": list(WHIFFS), "swings": list(SWINGS)}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    sql += " GROUP BY 1, 2, 3"
    stmt = text(sql).bindparams(
        *[bindparam(k, expanding=True) for k in ("fb", "brk", "off", "whiffs", "swings")])
    df = pd.read_sql(stmt, get_engine(), params=params)
    df["game_date"] = pd.to_datetime(df["game_date"])
    return df.sort_values(["pitcher_id", "game_date", "game_pk"]).reset_index(drop=True)


def _rolling_ratio_lookup(per_game: pd.DataFrame, player_col: str, window: int,
                          ratios: dict[str, tuple[str, str]]) -> pd.DataFrame:
    """Rolling (num/den) ratios per (player, game) — for statcast quality cols.
    Same contiguous-group positional filling as _rolling_rates."""
    n_rows = len(per_game)
    out = {col: np.full(n_rows, np.nan) for col in ratios}
    pos = 0
    for _, grp in per_game.groupby(player_col, sort=False):
        g = grp.reset_index(drop=True)
        dates = g["game_date"].to_numpy()
        cols = {c for pair in ratios.values() for c in pair}
        cums = {col: np.concatenate([[0.0], g[col].fillna(0).to_numpy(float).cumsum()])
                for col in cols}
        for i in range(len(g)):
            cut = int(np.searchsorted(dates, dates[i], side="left"))
            lo = max(0, cut - window)
            for out_col, (num, den) in ratios.items():
                d = cums[den][cut] - cums[den][lo]
                if d:
                    out[out_col][pos + i] = (cums[num][cut] - cums[num][lo]) / d
        pos += len(g)
    return pd.DataFrame({player_col: per_game[player_col].to_numpy(),
                         "game_pk": per_game["game_pk"].to_numpy(), **out})


def build(max_date: str | None = None) -> dict:
    """Returns dict with 'pa' (training frame incl. TARGET_CLASS + features)
    and the keyed component frames for prediction-time assembly."""
    pa = load_pa(max_date)
    prior = _league_prior(pa)

    log.info("rolling batter rates ...")
    b_counts = _per_game_counts(pa, "batter_id", "pitch_hand")
    b_rates = _rolling_rates(b_counts, "batter_id", B_WINDOW, prior)
    b_rates = b_rates.add_prefix("B_").rename(
        columns={"B_batter_id": "batter_id", "B_game_pk": "game_pk"})

    log.info("rolling pitcher rates ...")
    p_counts = _per_game_counts(pa, "pitcher_id", "bat_side")
    p_rates = _rolling_rates(p_counts, "pitcher_id", P_WINDOW, prior)
    p_rates = p_rates.add_prefix("P_").rename(
        columns={"P_pitcher_id": "pitcher_id", "P_game_pk": "game_pk"})

    log.info("statcast quality blocks ...")
    b_sc = _rolling_ratio_lookup(_batter_statcast(max_date), "batter_id", B_WINDOW,
                                 {"B_XWOBA_CON": ("xwoba_num", "bbe")})
    ars = _rolling_ratio_lookup(
        _pitcher_arsenal(max_date), "pitcher_id", P_WINDOW,
        {"P_FB_VELO": ("fb_velo_sum", "fb_n"),
         "P_BREAKING_PCT": ("breaking_n", "pitches"),
         "P_OFFSPEED_PCT": ("offspeed_n", "pitches"),
         "P_WHIFF_RATE": ("whiffs", "swings")})

    park = pd.read_sql(text("SELECT season, venue_id, pf_runs FROM park_factors"),
                       get_engine())

    frame = (pa.merge(b_rates, on=["batter_id", "game_pk"], how="left")
               .merge(p_rates, on=["pitcher_id", "game_pk"], how="left")
               .merge(b_sc, on=["batter_id", "game_pk"], how="left")
               .merge(ars, on=["pitcher_id", "game_pk"], how="left")
               .merge(park, on=["season", "venue_id"], how="left"))

    # Select platoon variant by this PA's opposing hand; drop the raw splits.
    vs_l = frame["pitch_hand"] == "L"
    for c in CLASSES:
        frame[f"B_RATE_{c}_VS_HAND"] = np.where(
            vs_l, frame[f"B_rate_{c}_vsL"], frame[f"B_rate_{c}_vsR"])
    frame["B_PA_VS_HAND"] = np.where(vs_l, frame["B_pa_vsL"], frame["B_pa_vsR"])
    vs_lhb = frame["bat_side"] == "L"
    for c in CLASSES:
        frame[f"P_RATE_{c}_VS_SIDE"] = np.where(
            vs_lhb, frame[f"P_rate_{c}_vsL"], frame[f"P_rate_{c}_vsR"])
    frame["P_BF_VS_SIDE"] = np.where(vs_lhb, frame["P_pa_vsL"], frame["P_pa_vsR"])

    for c in CLASSES:
        frame[f"B_RATE_{c}"] = frame[f"B_rate_{c}"]
        frame[f"P_RATE_{c}"] = frame[f"P_rate_{c}"]
    frame["B_PA_N"] = frame["B_pa"]
    frame["P_BF_N"] = frame["P_pa"]
    frame["SAME_HAND"] = (frame["bat_side"] == frame["pitch_hand"]).astype(int)
    frame["IS_HOME"] = frame["is_home_batter"].astype(int)
    frame["PARK_PF_RUNS"] = frame["pf_runs"].fillna(1.0)
    frame["TARGET_CLASS"] = frame["outcome"].map(CLASS_INDEX)

    feature_cols = feature_columns()
    keep = BATTER_META_COLS + ["TARGET_CLASS"] + feature_cols
    out = frame[keep].copy()
    log.info("PA frame: %d rows x %d features", len(out), len(feature_cols))
    return {"pa": out, "b_rates": b_rates, "p_rates": p_rates,
            "b_sc": b_sc, "arsenal": ars, "park": park, "league_prior": prior}


def _asof_rates(per_game: pd.DataFrame, player_col: str, window: int,
                league: np.ndarray) -> pd.DataFrame:
    """One shrunken-rate row per player over their last `window` games
    through the data cutoff — for predicting games AFTER that cutoff."""
    cols = [f"{c}{sfx}" for sfx in ("", "_vsL", "_vsR") for c in CLASSES + ["pa"]]
    tail = per_game.groupby(player_col, sort=False).tail(window)
    sums = tail.groupby(player_col, sort=False)[cols].sum()
    out = pd.DataFrame(index=sums.index)
    for sfx in ("", "_vsL", "_vsR"):
        n = sums[f"pa{sfx}"]
        w = SHRINK_OVERALL if sfx == "" else SHRINK_SPLIT
        out[f"pa{sfx}"] = n
        for ci, c in enumerate(CLASSES):
            out[f"rate_{c}{sfx}"] = (sums[f"{c}{sfx}"] + w * league[ci]) / (n + w)
    return out.reset_index()


def _asof_ratios(per_game: pd.DataFrame, player_col: str, window: int,
                 ratios: dict[str, tuple[str, str]]) -> pd.DataFrame:
    tail = per_game.groupby(player_col, sort=False).tail(window)
    cols = list({c for pair in ratios.values() for c in pair})
    sums = tail.groupby(player_col, sort=False)[cols].sum()
    out = pd.DataFrame(index=sums.index)
    for out_col, (num, den) in ratios.items():
        out[out_col] = np.where(sums[den] > 0, sums[num] / sums[den], np.nan)
    return out.reset_index()


def build_asof(asof_date: str) -> dict:
    """Per-player components (through asof_date) for pregame prediction.
    Same column names as build()'s per-game components, minus game_pk."""
    pa = load_pa(max_date=asof_date)
    prior = _league_prior(pa)
    league = prior(np.datetime64(pd.Timestamp(asof_date) + pd.Timedelta(days=1)))

    b = _asof_rates(_per_game_counts(pa, "batter_id", "pitch_hand"),
                    "batter_id", B_WINDOW, league)
    b = b.add_prefix("B_").rename(columns={"B_batter_id": "batter_id"})
    p = _asof_rates(_per_game_counts(pa, "pitcher_id", "bat_side"),
                    "pitcher_id", P_WINDOW, league)
    p = p.add_prefix("P_").rename(columns={"P_pitcher_id": "pitcher_id"})
    b_sc = _asof_ratios(_batter_statcast(asof_date), "batter_id", B_WINDOW,
                        {"B_XWOBA_CON": ("xwoba_num", "bbe")})
    ars = _asof_ratios(_pitcher_arsenal(asof_date), "pitcher_id", P_WINDOW,
                       {"P_FB_VELO": ("fb_velo_sum", "fb_n"),
                        "P_BREAKING_PCT": ("breaking_n", "pitches"),
                        "P_OFFSPEED_PCT": ("offspeed_n", "pitches"),
                        "P_WHIFF_RATE": ("whiffs", "swings")})
    park = pd.read_sql(text("SELECT season, venue_id, pf_runs FROM park_factors"),
                       get_engine())
    return {"pa": pa, "b_rates": b, "p_rates": p, "b_sc": b_sc,
            "arsenal": ars, "park": park}


def feature_columns() -> list[str]:
    cols = [f"B_RATE_{c}" for c in CLASSES] + [f"B_RATE_{c}_VS_HAND" for c in CLASSES]
    cols += [f"P_RATE_{c}" for c in CLASSES] + [f"P_RATE_{c}_VS_SIDE" for c in CLASSES]
    cols += ["B_PA_N", "B_PA_VS_HAND", "B_XWOBA_CON",
             "P_BF_N", "P_BF_VS_SIDE",
             "P_FB_VELO", "P_BREAKING_PCT", "P_OFFSPEED_PCT", "P_WHIFF_RATE",
             "SAME_HAND", "IS_HOME", "PARK_PF_RUNS"]
    return cols
