"""Per-PA multiclass batter model + aggregation to game-level products.

The model predicts the 8-class PA outcome distribution (OUT/K/BB/HBP/1B/2B/
3B/HR). Game-level products are analytic aggregations:

  expected stat line:  E[stat] = E[n_PA] * per-PA expectation  (linearity)
  P(>=1 hit)        :  1 - sum_k P(n=k) * (1-p_hit)^k  over the empirical
                       PA-count distribution for the batter's lineup slot
  P(>=2 TB)         :  1 - P(TB=0) - P(TB=1), with P(TB=1|k) = exactly one
                       single among k otherwise hitless PAs

A game's PAs are mixed between the known probable starter and unknown relief:
p_game = w * p_vs_SP + (1-w) * p_vs_league, with w = league share of PAs
taken by starters (per-SP workload share is experiment B1 in the tuning log).
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

from features.batter_features import CLASSES

LGBM_PA_PARAMS = dict(
    objective="multiclass", num_class=len(CLASSES),
    n_estimators=300, learning_rate=0.06, num_leaves=31, min_child_samples=200,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
    n_jobs=-1, verbosity=-1,
)

I_1B, I_2B, I_3B, I_HR = (CLASSES.index(c) for c in ("1B", "2B", "3B", "HR"))
I_BB, I_K = CLASSES.index("BB"), CLASSES.index("K")


class BatterPAModel:
    hyperparams = LGBM_PA_PARAMS

    def __init__(self, seed: int = 0):
        self.model = LGBMClassifier(random_state=seed, **LGBM_PA_PARAMS)

    def fit(self, frame: pd.DataFrame, feats: list[str]) -> None:
        self.model.fit(frame[feats], frame["TARGET_CLASS"])

    def predict_proba(self, frame: pd.DataFrame, feats: list[str]) -> np.ndarray:
        return self.model.predict_proba(frame[feats])


def assemble_matchup(rows: pd.DataFrame, comp: dict, league_row: dict | None,
                     park: pd.DataFrame, per_game: bool = True) -> pd.DataFrame:
    """Feature frame for (batter, game, opposing SP) rows.

    comp components are keyed per (player, game) from batter_features.build()
    when per_game=True (historical walk-forward), or per player from
    build_asof() when per_game=False (pregame prediction). If league_row is
    given, pitcher-side features come from it — the 'vs unknown relief'
    variant used in the SP/bullpen mixture.
    """
    gk = ["game_pk"] if per_game else []
    df = rows.merge(comp["b_rates"], left_on=["player_id"] + gk,
                    right_on=["batter_id"] + gk, how="left")
    df = df.merge(comp["b_sc"], left_on=["player_id"] + gk,
                  right_on=["batter_id"] + gk, how="left", suffixes=("", "_sc"))
    df = df.merge(park, on=["season", "venue_id"], how="left")

    sp_left = df["sp_throws"].fillna("R") == "L"
    bats = df["bats"].fillna("R")
    eff_side = np.where(bats == "S", np.where(sp_left, "R", "L"), bats)

    for c in CLASSES:
        df[f"B_RATE_{c}"] = df[f"B_rate_{c}"]
    if league_row is None:
        for c in CLASSES:
            df[f"B_RATE_{c}_VS_HAND"] = np.where(sp_left, df[f"B_rate_{c}_vsL"],
                                                 df[f"B_rate_{c}_vsR"])
        df["B_PA_VS_HAND"] = np.where(sp_left, df["B_pa_vsL"], df["B_pa_vsR"])
        p = comp["p_rates"].merge(comp["arsenal"], on=["pitcher_id"] + gk)
        df = df.merge(p, left_on=["sp_id"] + gk,
                      right_on=["pitcher_id"] + gk, how="left")
        vs_lhb = eff_side == "L"
        for c in CLASSES:
            df[f"P_RATE_{c}"] = df[f"P_rate_{c}"]
            df[f"P_RATE_{c}_VS_SIDE"] = np.where(vs_lhb, df[f"P_rate_{c}_vsL"],
                                                 df[f"P_rate_{c}_vsR"])
        df["P_BF_N"] = df["P_pa"]
        df["P_BF_VS_SIDE"] = np.where(vs_lhb, df["P_pa_vsL"], df["P_pa_vsR"])
        df["SAME_HAND"] = (eff_side == np.where(sp_left, "L", "R")).astype(int)
    else:
        q_r = league_row["q_vs_right"]
        for c in CLASSES:
            df[f"B_RATE_{c}_VS_HAND"] = (q_r * df[f"B_rate_{c}_vsR"]
                                         + (1 - q_r) * df[f"B_rate_{c}_vsL"])
        df["B_PA_VS_HAND"] = q_r * df["B_pa_vsR"] + (1 - q_r) * df["B_pa_vsL"]
        for col, val in league_row["pitcher_means"].items():
            df[col] = val
        df["SAME_HAND"] = league_row["same_hand_mean"]

    df["B_PA_N"] = df["B_pa"]
    # B4 cross — pitcher mix columns exist in both branches by this point
    fb_share = 1.0 - df["P_BREAKING_PCT"] - df["P_OFFSPEED_PCT"]
    df["B_ARSENAL_MATCH"] = (fb_share * df["B_XWOBA_F"]
                             + df["P_BREAKING_PCT"] * df["B_XWOBA_B"]
                             + df["P_OFFSPEED_PCT"] * df["B_XWOBA_O"])
    df["IS_HOME"] = df["is_home"].astype(int)
    df["PARK_PF_RUNS"] = df["pf_runs"].fillna(1.0)
    return df


def blend_k(probs: np.ndarray, marginal: np.ndarray, alpha: float = 0.5) -> np.ndarray:
    """B2 (SHIPPED): the PA model over-trusts matchup strikeout signal —
    blending the K probability halfway back to the batter's own marginal cut
    K MAE 0.678 -> 0.672 (p<.0001, 131k paired batter-games). Other classes
    rescale proportionally so rows still sum to 1."""
    out = probs.copy()
    k = CLASSES.index("K")
    k_new = alpha * probs[:, k] + (1 - alpha) * marginal[:, k]
    scale = (1 - k_new) / np.clip(1 - probs[:, k], 1e-9, None)
    out *= scale[:, None]
    out[:, k] = k_new
    return out


def marginal_probs(frame: pd.DataFrame) -> np.ndarray:
    """Baseline: the batter's own shrunken overall rates, renormalized.
    Isolates what the matchup/arsenal/platoon features add."""
    cols = [f"B_RATE_{c}" for c in CLASSES]
    p = frame[cols].to_numpy(float)
    return p / p.sum(axis=1, keepdims=True)


def per_pa_expectations(probs: np.ndarray) -> dict[str, np.ndarray]:
    p_hit = probs[:, I_1B] + probs[:, I_2B] + probs[:, I_3B] + probs[:, I_HR]
    tb = probs[:, I_1B] + 2 * probs[:, I_2B] + 3 * probs[:, I_3B] + 4 * probs[:, I_HR]
    return {"hit": p_hit, "tb": tb, "hr": probs[:, I_HR],
            "bb": probs[:, I_BB], "k": probs[:, I_K], "p_1b": probs[:, I_1B]}


def aggregate_game(probs: np.ndarray, pa_dist: np.ndarray) -> dict[str, np.ndarray]:
    """probs: (n_batters, 8) per-PA mixed distribution; pa_dist: (n_batters, K)
    where pa_dist[i, k] = P(batter i gets k PAs), k = 0..K-1."""
    per = per_pa_expectations(probs)
    ks = np.arange(pa_dist.shape[1])
    exp_pa = pa_dist @ ks
    out = {
        "exp_pa": exp_pa,
        "exp_h": exp_pa * per["hit"], "exp_tb": exp_pa * per["tb"],
        "exp_hr": exp_pa * per["hr"], "exp_bb": exp_pa * per["bb"],
        "exp_k": exp_pa * per["k"],
    }
    # P(>=1 X) = 1 - E_k[(1-p_X)^k]
    for name, p in (("p_hit", per["hit"]), ("p_hr", per["hr"]), ("p_bb", per["bb"])):
        no_x = (1.0 - p)[:, None] ** ks[None, :]
        out[name] = 1.0 - (pa_dist * no_x).sum(axis=1)
    # P(TB>=2) = 1 - P(TB=0) - P(TB=1); TB=1 requires exactly one single.
    p_hit, p_1b = per["hit"], per["p_1b"]
    no_hit = (1.0 - p_hit)[:, None] ** ks[None, :]
    one_single = (ks[None, :] * p_1b[:, None]
                  * np.where(ks[None, :] > 0,
                             (1.0 - p_hit)[:, None] ** np.maximum(ks[None, :] - 1, 0), 0.0))
    out["p_tb2"] = 1.0 - (pa_dist * (no_hit + one_single)).sum(axis=1)
    return out


def build_pa_dists(train_pa_per_game: pd.DataFrame, max_pa: int = 7) -> dict:
    """Empirical P(n_PA = k) by (lineup_slot, is_home). Plain dict of arrays
    so it can live inside a pickled model bundle."""
    overall = np.bincount(train_pa_per_game["pa"].clip(0, max_pa), minlength=max_pa + 1)
    dists = {"__overall__": overall / overall.sum()}
    for (slot, home), grp in train_pa_per_game.groupby(["lineup_slot", "is_home"]):
        counts = np.bincount(grp["pa"].clip(0, max_pa), minlength=max_pa + 1)
        dists[(slot, home)] = counts / counts.sum()
    return dists


def pa_lookup(dists: dict):
    def lookup(slots, homes) -> np.ndarray:
        return np.vstack([dists.get((s, h), dists["__overall__"])
                          for s, h in zip(slots, homes)])
    return lookup


def pa_count_distribution(train_pa_per_game: pd.DataFrame, max_pa: int = 7):
    return pa_lookup(build_pa_dists(train_pa_per_game, max_pa))


# ---- B8a (shipped 2026-07-23): slot-conditional expected RBI ---------------
# rbar(outcome, slot) = shrunken mean RBI credited when class c occurs from
# lineup slot s; exp_rbi = exp_pa x sum_c p[c] x rbar(c, slot). Shared by
# validation.walkforward_batter and orchestration.daily so the two paths can
# never drift (walk-forward: 0.6331 vs 0.6363 marginal / 0.6367 slot-only
# RBI MAE, p<.0001 at seeds 0/1/2, 158,169 batter-games 2023-2026).
ERA_RBI_PRIOR = {"OUT": 0.025, "K": 0.0, "BB": 0.03, "HBP": 0.03,
                 "1B": 0.30, "2B": 0.45, "3B": 0.50, "HR": 1.57}
RBI_LEAGUE_PRIOR = 0.115   # league RBI per PA, era constant
RBI_SHRINK_SLOT = 300.0
RBI_CLASS_MIN_PA = 10_000


def rbi_events(max_date: str | None = None) -> pd.DataFrame:
    """Starter PAs with credited RBIs, lineup slot, and outcome class — the
    raw material for rbar(outcome, slot). Point-in-time via max_date (the
    daily path passes asof; the harness filters by season instead)."""
    from sqlalchemy import text

    from core.db import get_engine
    from features.batter_features import EVENT_MAP

    sql = """
        SELECT g.season, g.game_date, p.game_pk, p.batter_id, p.rbi,
               p.event_type, l.batting_order AS slot
        FROM plays p
        JOIN games g USING (game_pk)
        LEFT JOIN lineups l ON l.game_pk = p.game_pk AND l.player_id = p.batter_id
        WHERE g.is_final
    """
    params = {}
    if max_date:
        sql += " AND g.game_date <= :max_date"
        params["max_date"] = max_date
    df = pd.read_sql(text(sql), get_engine(), params=params)
    df["outcome"] = df["event_type"].map(EVENT_MAP)
    df["game_date"] = pd.to_datetime(df["game_date"])
    df["rbi"] = df["rbi"].fillna(0).astype(float)
    return df.dropna(subset=["outcome"]).reset_index(drop=True)


def rbi_table(events: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(rbar matrix [slot 0..9 x class], slot-marginal rbar [slot 0..9]).
    Class-global means fall back to fixed era constants below
    RBI_CLASS_MIN_PA — never frame-derived when thin (ERA_PRIOR lesson)."""
    ev = events.dropna(subset=["slot"])
    ev = ev[ev["slot"].between(1, 9)].copy()
    ev["slot"] = ev["slot"].astype(int)
    g_class = ev.groupby("outcome")["rbi"].agg(["sum", "count"])
    rbar_c = {}
    for c in CLASSES:
        if c in g_class.index and g_class.loc[c, "count"] >= RBI_CLASS_MIN_PA:
            rbar_c[c] = float(g_class.loc[c, "sum"] / g_class.loc[c, "count"])
        else:
            rbar_c[c] = ERA_RBI_PRIOR[c]
    g_cell = ev.groupby(["slot", "outcome"])["rbi"].agg(["sum", "count"])
    mat = np.zeros((10, len(CLASSES)))
    for s in range(1, 10):
        for ci, c in enumerate(CLASSES):
            if (s, c) in g_cell.index:
                cell = g_cell.loc[(s, c)]
                mat[s, ci] = ((cell["sum"] + RBI_SHRINK_SLOT * rbar_c[c])
                              / (cell["count"] + RBI_SHRINK_SLOT))
            else:
                mat[s, ci] = rbar_c[c]
    overall = float(ev["rbi"].sum() / max(len(ev), 1)) if len(ev) else RBI_LEAGUE_PRIOR
    g_slot = ev.groupby("slot")["rbi"].agg(["sum", "count"])
    slot_marg = np.full(10, overall)
    for s in range(1, 10):
        if s in g_slot.index:
            cell = g_slot.loc[s]
            slot_marg[s] = ((cell["sum"] + RBI_SHRINK_SLOT * overall)
                            / (cell["count"] + RBI_SHRINK_SLOT))
    return mat, slot_marg
