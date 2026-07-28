"""Season-level walk-forward for the batter model (Phase 4).

For each test season S in 2023..2025: train the per-PA model on all seasons
before S, then evaluate
  1. per-PA multiclass log loss on S's PAs vs two baselines
     (league marginal, batter shrunken marginal), and
  2. game-level products on S's regular-season games where the announced
     probable actually started: expected stat lines (MAE vs the
     batter-marginal baseline aggregated identically) and calibration/Brier
     for the probability heads.

Game predictions land in batter_predictions (model_version pa_v1) and the
B7 starter heads in pitcher_predictions; every window logs to model_registry.

Experiment arms (E16 pattern): --enable-flags forces FEATURE_FLAGS on for
this run; --compare-base additionally trains a flags-OFF model per season on
identical folds and prints paired verdicts twice — the E8d selection pool
(seasons <= 2025) and 2026 confirm-only — so one invocation serves both
discipline windows. (This generalizes and replaces the old --b4-compare,
which had become a no-op once the arsenal_cross flag stripped B4 columns
from the default feature list.)

Usage: python -m validation.walkforward_batter
       python -m validation.walkforward_batter --seasons 2023 2024 2025 2026 \
           --enable-flags dev_l5 --compare-base --version e16_l5
"""

import argparse
import logging

import numpy as np
import pandas as pd
from scipy.stats import ttest_rel
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss
from sqlalchemy import text

from core import model_registry
from core.db import get_engine
from core.features import select_features
from features import batter_features as bf
from features.batter_features import CLASSES
from modeling import batter_model as bm

log = logging.getLogger("wf_batter")

MODEL_VERSION = "pa_v1"
TEST_SEASONS = (2023, 2024, 2025)


def _load_game_side_data():
    """Lineup starters with the opposing starter attached, plus flags for
    whether the announced probable matched the actual starter."""
    engine = get_engine()
    lineups = pd.read_sql(text("""
        SELECT l.game_pk, l.player_id, l.team_id, l.batting_order AS lineup_slot,
               g.season, g.game_date, g.game_type, g.venue_id,
               (l.team_id = g.home_team_id) AS is_home
        FROM lineups l JOIN games g USING (game_pk)
        WHERE g.is_final AND COALESCE(g.scheduled_innings, 9) = 9
    """), engine)
    starters = pd.read_sql(text("""
        SELECT game_pk, team_id, player_id AS sp_id
        FROM pitcher_game_lines WHERE is_starter
    """), engine)
    probables = pd.read_sql(text("""
        SELECT p.game_pk, g.home_team_id, g.away_team_id,
               p.home_pitcher_id, p.away_pitcher_id
        FROM probable_pitchers p JOIN games g USING (game_pk)
        WHERE p.source = 'backfill'
    """), engine)
    players = pd.read_sql(text("SELECT player_id, bats, throws FROM players"), engine)
    actual_bat = pd.read_sql(text("""
        SELECT game_pk, player_id, pa, h, tb, hr, bb, so AS k, rbi
        FROM batter_game_lines
    """), engine)
    # B7: the starter's actual line, for pitcher-level evaluation
    actual_sp = pd.read_sql(text("""
        SELECT game_pk, player_id AS sp_id, so AS sp_k, bb AS sp_bb, h AS sp_h,
               outs AS sp_outs
        FROM pitcher_game_lines WHERE is_starter
    """), engine)

    # opponent's starter for each lineup row
    lineups["game_date"] = pd.to_datetime(lineups["game_date"])
    home_prob = probables.rename(columns={"home_pitcher_id": "prob_sp"})[
        ["game_pk", "home_team_id", "prob_sp"]].rename(columns={"home_team_id": "sp_team"})
    away_prob = probables.rename(columns={"away_pitcher_id": "prob_sp"})[
        ["game_pk", "away_team_id", "prob_sp"]].rename(columns={"away_team_id": "sp_team"})
    prob_long = pd.concat([home_prob, away_prob], ignore_index=True)
    starters = starters.merge(prob_long, left_on=["game_pk", "team_id"],
                              right_on=["game_pk", "sp_team"], how="left")
    starters["prob_matched"] = starters["sp_id"] == starters["prob_sp"]

    games = pd.read_sql(text(
        "SELECT game_pk, home_team_id, away_team_id FROM games WHERE is_final"), engine)
    lineups = lineups.merge(games, on="game_pk")
    lineups["opp_team_id"] = np.where(lineups["is_home"],
                                      lineups["away_team_id"], lineups["home_team_id"])
    lineups = lineups.merge(
        starters[["game_pk", "team_id", "sp_id", "prob_matched"]],
        left_on=["game_pk", "opp_team_id"], right_on=["game_pk", "team_id"],
        how="inner", suffixes=("", "_sp"))
    lineups = lineups.merge(players.rename(columns={"player_id": "sp_id",
                                                    "throws": "sp_throws"})[["sp_id", "sp_throws"]],
                            on="sp_id", how="left")
    lineups = lineups.merge(players[["player_id", "bats"]], on="player_id", how="left")
    lineups = lineups.merge(actual_bat, on=["game_pk", "player_id"], how="left")
    return lineups, actual_sp


# Matchup assembly lives in modeling.batter_model.assemble_matchup — shared
# with the daily pipeline so the two paths can never drift.

# ---- B8a (2026-07 cycle): slot-conditional expected RBI --------------------
# The rbar machinery lives in modeling.batter_model (shared with the daily
# pipeline so the two paths can never drift); the harness keeps only the
# marginal-baseline lookup below.
from modeling.batter_model import (RBI_LEAGUE_PRIOR,  # noqa: E402
                                   rbi_events as _load_rbi_events,
                                   rbi_table as _rbi_table)

RBI_SHRINK_BATTER = 150.0  # mirrors the batter model's overall shrinkage W


def _batter_rbi_lookup(events: pd.DataFrame):
    """Batter's shrunken rolling RBI-per-PA as-of a date (last 60 games,
    W=150 toward the expanding league rate) — the marginal baseline,
    mirroring the batter model's own rate-feature construction. Point-in-time
    via searchsorted; the game's own date is excluded."""
    per_game = events.groupby(["batter_id", "game_pk", "game_date"], as_index=False) \
        .agg(rbi=("rbi", "sum"), n=("rbi", "size")).sort_values("game_date")
    daily = per_game.groupby("game_date")[["rbi", "n"]].sum()
    ld = daily.index.to_numpy()
    l_rbi = np.concatenate([[0.0], daily["rbi"].to_numpy(float).cumsum()])
    l_n = np.concatenate([[0.0], daily["n"].to_numpy(float).cumsum()])
    book = {}
    for pid, grp in per_game.groupby("batter_id", sort=False):
        book[pid] = (grp["game_date"].to_numpy(),
                     np.concatenate([[0.0], grp["rbi"].to_numpy(float).cumsum()]),
                     np.concatenate([[0.0], grp["n"].to_numpy(float).cumsum()]))

    def lookup(pid, date64) -> float:
        li = int(np.searchsorted(ld, date64, side="left"))
        lg = l_rbi[li] / l_n[li] if l_n[li] > 50_000 else RBI_LEAGUE_PRIOR
        entry = book.get(pid)
        if entry is None:
            return float(lg)
        dates, crbi, cn = entry
        hi = int(np.searchsorted(dates, date64, side="left"))
        lo = max(0, hi - 60)
        n = cn[hi] - cn[lo]
        return float(((crbi[hi] - crbi[lo]) + RBI_SHRINK_BATTER * lg)
                     / (n + RBI_SHRINK_BATTER))

    return lookup


def run(seed: int = 0, write_preds: bool = True, version: str = MODEL_VERSION,
        seasons: tuple[int, ...] = TEST_SEASONS,
        enable_flags: tuple[str, ...] = (), compare_base: bool = False) -> None:
    comp = bf.build()
    pa = comp["pa"]
    feats = select_features(list(pa.columns), "batter_pa", enable_flags=enable_flags)
    feats_cmp = select_features(list(pa.columns), "batter_pa")
    if compare_base and not enable_flags:
        log.warning("--compare-base without --enable-flags compares identical "
                    "models; skipping the compare arm")
        compare_base = False
    park = comp["park"]
    sides, actual_sp = _load_game_side_data()

    # league share of PAs taken by the game's starter (mixing weight w)
    starters = pd.read_sql(text(
        "SELECT game_pk, player_id FROM pitcher_game_lines WHERE is_starter"), get_engine())
    starter_keys = set(zip(starters["game_pk"], starters["player_id"]))

    # B1: per-SP workload share from the team-features SP lookup
    from features.team_features import _load_starts, _sp_lookup
    sp_look = _sp_lookup(_load_starts(None))

    def sp_share(sp_id, date64, fallback: float) -> float:
        d = sp_look(int(sp_id), date64)
        ip = d.get("SP_IP_PER_START_L10", np.nan)
        return fallback if ip is None or np.isnan(ip) else float(np.clip(ip / 9.0, 0.40, 0.85))

    # pooled per-batter-game abs errors for paired tests across variants
    pooled: dict[str, list] = {k: [] for k in
                               ("base_h", "base_k", "b1_h", "b1_k", "b2_k",
                                "hit1", "hr1", "p_hit", "p_hr",
                                "p_hit_cal", "p_hr_cal",
                                # B7: per-starter absolute errors
                                "spk_m", "spk_base", "spk_board", "spk_wsp",
                                "spbb_m", "spbb_base", "spbb_wsp",
                                "sph_m", "sph_base", "sph_wsp",
                                # B8a: expected-RBI absolute errors
                                "rbi_m", "rbi_base", "rbi_slot")}
    # --compare-base: season-keyed paired pools so the verdicts can split the
    # E8d selection window (<=2025) from the 2026 confirm-only view
    cmp_pool: dict[str, dict[int, list]] = {k: {} for k in
        ("ll_on", "ll_off", "h_on", "h_off", "k_on", "k_off",
         "p_hit_on", "p_hit_off", "hit1", "spk_on", "spk_off")}
    rbi_events = _load_rbi_events()
    rbi_lookup = _batter_rbi_lookup(rbi_events)
    calib_hist = {"p_hit": [], "p_hr": [], "hit1": [], "hr1": []}

    for season in seasons:
        train = pa[pa["season"] < season]
        test = pa[pa["season"] == season]
        log.info("season %d: train %d PAs, test %d PAs", season, len(train), len(test))

        model = bm.BatterPAModel(seed=seed)
        model.fit(train, feats)
        if compare_base:
            model_cmp = bm.BatterPAModel(seed=seed)
            model_cmp.fit(train, feats_cmp)

        # --- per-PA log loss vs baselines
        probs = model.predict_proba(test, feats)
        y = test["TARGET_CLASS"].to_numpy()
        league = np.bincount(train["TARGET_CLASS"], minlength=len(CLASSES)).astype(float)
        league /= league.sum()
        ll_model = log_loss(y, probs, labels=range(len(CLASSES)))
        ll_league = log_loss(y, np.tile(league, (len(test), 1)), labels=range(len(CLASSES)))
        ll_marginal = log_loss(y, bm.marginal_probs(test), labels=range(len(CLASSES)))
        log.info("per-PA log loss: model %.5f | batter-marginal %.5f | league %.5f",
                 ll_model, ll_marginal, ll_league)
        if compare_base:
            probs_cmp = model_cmp.predict_proba(test, feats_cmp)
            idx = np.arange(len(test))
            cmp_pool["ll_on"].setdefault(season, []).append(
                -np.log(np.clip(probs[idx, y], 1e-12, None)))
            cmp_pool["ll_off"].setdefault(season, []).append(
                -np.log(np.clip(probs_cmp[idx, y], 1e-12, None)))

        # --- game-level evaluation (probable started, regular season)
        w = np.mean([(g, p) in starter_keys
                     for g, p in zip(train["game_pk"], train["pitcher_id"])])
        league_row = {
            "q_vs_right": float((train["pitch_hand"] == "R").mean()),
            "pitcher_means": {c: float(train[c].mean()) for c in feats
                              if c.startswith("P_")},
            "same_hand_mean": float(train["SAME_HAND"].mean()),
        }
        eligible = sides[(sides["season"] == season) & (sides["game_type"] == "R")
                         & sides["prob_matched"] & sides["pa"].notna()
                         & sides["lineup_slot"].between(1, 9)].reset_index(drop=True)
        vs_sp = bm.assemble_matchup(eligible, comp, None, park, per_game=True)
        vs_lg = bm.assemble_matchup(eligible, comp, league_row, park, per_game=True)
        # Require the merges to have hit (rate cols are never NaN when they
        # did, thanks to shrinkage); other NaNs (e.g. no-BBE xwOBA) are fine.
        ok = (vs_sp[f"B_rate_{CLASSES[0]}"].notna()
              & vs_sp[f"P_rate_{CLASSES[0]}"].notna()).to_numpy()
        vs_sp, vs_lg, eligible = vs_sp[ok], vs_lg[ok], eligible[ok]
        p_mix = (w * model.predict_proba(vs_sp, feats)
                 + (1 - w) * model.predict_proba(vs_lg, feats))
        p_base = bm.marginal_probs(vs_sp)

        train_pa_dist = sides[(sides["season"] < season) & sides["pa"].notna()
                              & sides["lineup_slot"].between(1, 9)][
            ["lineup_slot", "is_home", "pa"]].astype({"pa": int})
        pa_lookup = bm.pa_count_distribution(train_pa_dist)
        pa_dist = pa_lookup(eligible["lineup_slot"].to_numpy(),
                            eligible["is_home"].to_numpy())
        agg = bm.aggregate_game(p_mix, pa_dist)
        agg_base = bm.aggregate_game(p_base, pa_dist)
        if compare_base:
            p_sp_cmp = model_cmp.predict_proba(vs_sp, feats_cmp)
            p_lg_cmp = model_cmp.predict_proba(vs_lg, feats_cmp)
            agg_cmp = bm.aggregate_game(w * p_sp_cmp + (1 - w) * p_lg_cmp, pa_dist)

        # ---- B1: per-SP workload share instead of the league constant
        p_sp = model.predict_proba(vs_sp, feats)
        p_lg = model.predict_proba(vs_lg, feats)
        w_sp = np.array([sp_share(s, d.to_datetime64(), w)
                         for s, d in zip(eligible["sp_id"], eligible["game_date"])])
        agg_b1 = bm.aggregate_game(w_sp[:, None] * p_sp + (1 - w_sp[:, None]) * p_lg,
                                   pa_dist)

        # ---- B7: starter-scoped pitcher heads by aggregation. Predicted
        # starter K = sum over the opposing nine of (expected PAs x SP share)
        # x P(K | vs this SP per PA); same construction for BB and hits
        # allowed. Baselines: the SP's own shrunken marginal rates aggregated
        # identically, and the whole-game mixed sum the pitchers board shows
        # today (w-scaled). Only (game, SP) groups with all nine batters
        # predicted are evaluated.
        i_k7 = CLASSES.index("K")
        i_bb7 = CLASSES.index("BB")
        hit_idx = [CLASSES.index(c) for c in ("1B", "2B", "3B", "HR")]
        sp_data = {
            "game_pk": eligible["game_pk"].to_numpy(),
            "sp_id": eligible["sp_id"].to_numpy(),
            "game_date": eligible["game_date"].to_numpy(),
            "w_sp_val": w_sp,
            "m_k": agg["exp_pa"] * p_sp[:, i_k7],
            "m_bb": agg["exp_pa"] * p_sp[:, i_bb7],
            "m_h": agg["exp_pa"] * p_sp[:, hit_idx].sum(axis=1),
            "b_k": agg["exp_pa"] * vs_sp["P_rate_K"].to_numpy(float),
            "b_bb": agg["exp_pa"] * vs_sp["P_rate_BB"].to_numpy(float),
            "b_h": agg["exp_pa"] * vs_sp[["P_rate_1B", "P_rate_2B", "P_rate_3B",
                                          "P_rate_HR"]].to_numpy(float).sum(axis=1),
            "board_k": agg["exp_k"],
            "wsp_k": w_sp * agg["exp_pa"] * p_sp[:, i_k7],
            "wsp_bb": w_sp * agg["exp_pa"] * p_sp[:, i_bb7],
            "wsp_h": w_sp * agg["exp_pa"] * p_sp[:, hit_idx].sum(axis=1),
        }
        if compare_base:
            sp_data["cmp_k"] = agg["exp_pa"] * p_sp_cmp[:, i_k7]
        sp_rows = pd.DataFrame(sp_data)
        agg_spec = dict(
            n=("m_k", "size"), game_date=("game_date", "first"),
            w_sp_val=("w_sp_val", "first"),
            m_k=("m_k", "sum"), m_bb=("m_bb", "sum"),
            m_h=("m_h", "sum"), b_k=("b_k", "sum"), b_bb=("b_bb", "sum"),
            b_h=("b_h", "sum"), board_k=("board_k", "sum"), wsp_k=("wsp_k", "sum"),
            wsp_bb=("wsp_bb", "sum"), wsp_h=("wsp_h", "sum"))
        if compare_base:
            agg_spec["cmp_k"] = ("cmp_k", "sum")
        sp_g = sp_rows.groupby(["game_pk", "sp_id"], as_index=False).agg(**agg_spec)
        sp_g = sp_g[sp_g["n"] == 9].merge(actual_sp, on=["game_pk", "sp_id"],
                                          how="inner")
        # the SP faces ~w of each batter's PAs (league constant, as in the
        # game mixture); wsp_k already carries its per-SP share
        for col in ("m_k", "m_bb", "m_h", "b_k", "b_bb", "b_h", "board_k") + \
                (("cmp_k",) if compare_base else ()):
            sp_g[col] = w * sp_g[col]
        pooled["spk_m"].append(np.abs(sp_g["sp_k"] - sp_g["m_k"]).to_numpy())
        pooled["spk_base"].append(np.abs(sp_g["sp_k"] - sp_g["b_k"]).to_numpy())
        pooled["spk_board"].append(np.abs(sp_g["sp_k"] - sp_g["board_k"]).to_numpy())
        pooled["spk_wsp"].append(np.abs(sp_g["sp_k"] - sp_g["wsp_k"]).to_numpy())
        pooled["spbb_m"].append(np.abs(sp_g["sp_bb"] - sp_g["m_bb"]).to_numpy())
        pooled["spbb_base"].append(np.abs(sp_g["sp_bb"] - sp_g["b_bb"]).to_numpy())
        pooled["spbb_wsp"].append(np.abs(sp_g["sp_bb"] - sp_g["wsp_bb"]).to_numpy())
        pooled["sph_m"].append(np.abs(sp_g["sp_h"] - sp_g["m_h"]).to_numpy())
        pooled["sph_base"].append(np.abs(sp_g["sp_h"] - sp_g["b_h"]).to_numpy())
        pooled["sph_wsp"].append(np.abs(sp_g["sp_h"] - sp_g["wsp_h"]).to_numpy())
        if compare_base:
            cmp_pool["spk_on"].setdefault(season, []).append(
                np.abs(sp_g["sp_k"] - sp_g["m_k"]).to_numpy())
            cmp_pool["spk_off"].setdefault(season, []).append(
                np.abs(sp_g["sp_k"] - sp_g["cmp_k"]).to_numpy())

        # ---- B2: blend the K probability halfway back to the batter marginal
        i_k = CLASSES.index("K")
        p_b2 = p_mix.copy()
        k_blend = 0.5 * p_mix[:, i_k] + 0.5 * p_base[:, i_k]
        scale = (1 - k_blend) / np.clip(1 - p_mix[:, i_k], 1e-9, None)
        p_b2 *= scale[:, None]
        p_b2[:, i_k] = k_blend
        agg_b2 = bm.aggregate_game(p_b2, pa_dist)

        # ---- B8a: slot-conditional expected RBI (2026-07 cycle). rbar from
        # seasons strictly before S (matching the model's own train split;
        # the daily path will use full as-of, so the backtest understates
        # live value — the safe direction).
        rmat, rslot = _rbi_table(rbi_events[rbi_events["season"] < season])
        slots8 = eligible["lineup_slot"].to_numpy(int)
        exp_rbi = agg["exp_pa"] * (p_mix * rmat[slots8]).sum(axis=1)
        exp_rbi_slot = agg["exp_pa"] * rslot[slots8]
        b_rbi_rate = np.array([rbi_lookup(pid, d.to_datetime64())
                               for pid, d in zip(eligible["player_id"],
                                                 eligible["game_date"])])
        exp_rbi_base = agg["exp_pa"] * b_rbi_rate
        actual_rbi = eligible["rbi"].to_numpy(float)
        m8 = ~np.isnan(actual_rbi)
        pooled["rbi_m"].append(np.abs(actual_rbi - exp_rbi)[m8])
        pooled["rbi_base"].append(np.abs(actual_rbi - exp_rbi_base)[m8])
        pooled["rbi_slot"].append(np.abs(actual_rbi - exp_rbi_slot)[m8])

        # ---- B3: isotonic calibration of the probability heads, fit on the
        # PREVIOUS test season's predictions (walk-forward safe)
        cal = {}
        for head, key_p, key_y in (("p_hit", "p_hit", "hit1"), ("p_hr", "p_hr", "hr1")):
            if calib_hist[key_p]:
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
                iso.fit(np.concatenate(calib_hist[key_p]), np.concatenate(calib_hist[key_y]))
                cal[head] = iso.predict(agg[head])
            else:
                cal[head] = agg[head]

        actual_h = eligible["h"].to_numpy(float)
        actual_k = eligible["k"].to_numpy(float)
        hit1 = (actual_h >= 1).astype(float)
        hr1 = (eligible["hr"].to_numpy(float) >= 1).astype(float)
        pooled["base_h"].append(np.abs(actual_h - agg["exp_h"]))
        pooled["base_k"].append(np.abs(actual_k - agg["exp_k"]))
        pooled["b1_h"].append(np.abs(actual_h - agg_b1["exp_h"]))
        pooled["b1_k"].append(np.abs(actual_k - agg_b1["exp_k"]))
        pooled["b2_k"].append(np.abs(actual_k - agg_b2["exp_k"]))
        pooled["hit1"].append(hit1)
        pooled["hr1"].append(hr1)
        pooled["p_hit"].append(agg["p_hit"])
        pooled["p_hr"].append(agg["p_hr"])
        pooled["p_hit_cal"].append(cal["p_hit"])
        pooled["p_hr_cal"].append(cal["p_hr"])
        calib_hist["p_hit"].append(agg["p_hit"])
        calib_hist["p_hr"].append(agg["p_hr"])
        calib_hist["hit1"].append(hit1)
        calib_hist["hr1"].append(hr1)

        # ---- compare-base: paired flags-ON vs flags-OFF pools, season-keyed
        if compare_base:
            for key, arr in (("h_on", np.abs(actual_h - agg["exp_h"])),
                             ("h_off", np.abs(actual_h - agg_cmp["exp_h"])),
                             ("k_on", np.abs(actual_k - agg["exp_k"])),
                             ("k_off", np.abs(actual_k - agg_cmp["exp_k"])),
                             ("p_hit_on", agg["p_hit"]),
                             ("p_hit_off", agg_cmp["p_hit"]),
                             ("hit1", hit1)):
                cmp_pool[key].setdefault(season, []).append(np.asarray(arr))

        metrics = {"n_pa_test": int(len(test)), "n_batter_games": int(len(eligible)),
                   "ll_model": ll_model, "ll_marginal": ll_marginal, "ll_league": ll_league,
                   "sp_pa_share_w": float(w),
                   "mae_h_b1": float(np.mean(np.abs(actual_h - agg_b1["exp_h"]))),
                   "mae_k_b1": float(np.mean(np.abs(actual_k - agg_b1["exp_k"]))),
                   "mae_k_b2": float(np.mean(np.abs(actual_k - agg_b2["exp_k"]))),
                   "brier_p_hit_cal": float(np.mean((cal["p_hit"] - hit1) ** 2)),
                   "brier_p_hr_cal": float(np.mean((cal["p_hr"] - hr1) ** 2))}
        for stat in ("h", "tb", "hr", "bb", "k"):
            actual = eligible[stat].to_numpy(float)
            metrics[f"mae_{stat}"] = float(np.mean(np.abs(actual - agg[f"exp_{stat}"])))
            metrics[f"mae_{stat}_base"] = float(np.mean(np.abs(actual - agg_base[f"exp_{stat}"])))
        for head, actual_col, thresh in (("p_hit", "h", 1), ("p_hr", "hr", 1)):
            hit = (eligible[actual_col].to_numpy(float) >= thresh).astype(float)
            metrics[f"brier_{head}"] = float(np.mean((agg[head] - hit) ** 2))
            metrics[f"brier_{head}_base"] = float(np.mean((agg_base[head] - hit) ** 2))
            metrics[f"obs_rate_{head}"] = float(hit.mean())
            metrics[f"pred_rate_{head}"] = float(agg[head].mean())
        # B7 per-starter heads
        metrics["n_sp_games"] = int(len(sp_g))
        for name, pred_col, act_col in (("spk", "m_k", "sp_k"), ("spbb", "m_bb", "sp_bb"),
                                        ("sph", "m_h", "sp_h")):
            metrics[f"mae_{name}"] = float(np.mean(np.abs(sp_g[act_col] - sp_g[pred_col])))
        metrics["mae_spk_base"] = float(np.mean(np.abs(sp_g["sp_k"] - sp_g["b_k"])))
        metrics["mae_spk_board"] = float(np.mean(np.abs(sp_g["sp_k"] - sp_g["board_k"])))
        metrics["mae_spk_wsp"] = float(np.mean(np.abs(sp_g["sp_k"] - sp_g["wsp_k"])))
        metrics["mae_spbb_base"] = float(np.mean(np.abs(sp_g["sp_bb"] - sp_g["b_bb"])))
        metrics["mae_sph_base"] = float(np.mean(np.abs(sp_g["sp_h"] - sp_g["b_h"])))
        # B8a expected RBI
        metrics["mae_rbi"] = float(np.mean(np.abs(actual_rbi - exp_rbi)[m8]))
        metrics["mae_rbi_base"] = float(np.mean(np.abs(actual_rbi - exp_rbi_base)[m8]))
        metrics["mae_rbi_slot"] = float(np.mean(np.abs(actual_rbi - exp_rbi_slot)[m8]))
        metrics["pred_rbi_mean"] = float(np.mean(exp_rbi[m8]))
        metrics["obs_rbi_mean"] = float(np.mean(actual_rbi[m8]))
        log.info("season %d game-level: %s", season,
                 {k: round(v, 4) for k, v in metrics.items() if k.startswith(("mae", "brier"))})

        model_registry.log_model_run(
            model_type="lgbm_pa", target="batter", run_kind="walkforward_window",
            metrics=metrics, hyperparams=bm.LGBM_PA_PARAMS,
            feature_set_version=version,
            train_window=(str(train["game_date"].min().date()),
                          str(train["game_date"].max().date())),
            test_window=(f"{season}-01-01", f"{season}-12-31"),
            notes=f"seed={seed}, flags={list(enable_flags)}",
        )

        if write_preds:
            rows = eligible[["game_pk", "player_id", "sp_id", "lineup_slot"]].copy()
            rows["model_version"] = version
            rows["data_through_date"] = (eligible["game_date"]
                                         - pd.Timedelta(days=1)).dt.date.astype(str)
            for k in ("exp_pa", "exp_h", "exp_tb", "exp_hr", "exp_bb", "exp_k",
                      "p_hit", "p_hr", "p_tb2", "p_bb"):
                rows[k] = agg[k]
            rows["exp_rbi"] = exp_rbi
            insert = text("""
                INSERT INTO batter_predictions
                    (game_pk, player_id, model_version, data_through_date, sp_id,
                     lineup_slot, exp_pa, exp_h, exp_tb, exp_hr, exp_bb, exp_k,
                     p_hit, p_hr, p_tb2, p_bb, exp_rbi)
                VALUES (:game_pk, :player_id, :model_version, :data_through_date, :sp_id,
                        :lineup_slot, :exp_pa, :exp_h, :exp_tb, :exp_hr, :exp_bb, :exp_k,
                        :p_hit, :p_hr, :p_tb2, :p_bb, :exp_rbi)
                ON CONFLICT (game_pk, player_id, model_version) DO UPDATE SET
                    data_through_date = EXCLUDED.data_through_date,
                    sp_id = EXCLUDED.sp_id, lineup_slot = EXCLUDED.lineup_slot,
                    exp_pa = EXCLUDED.exp_pa, exp_h = EXCLUDED.exp_h,
                    exp_tb = EXCLUDED.exp_tb, exp_hr = EXCLUDED.exp_hr,
                    exp_bb = EXCLUDED.exp_bb, exp_k = EXCLUDED.exp_k,
                    p_hit = EXCLUDED.p_hit, p_hr = EXCLUDED.p_hr,
                    p_tb2 = EXCLUDED.p_tb2, p_bb = EXCLUDED.p_bb,
                    exp_rbi = EXCLUDED.exp_rbi,
                    created_at = now()
            """)
            records = rows.to_dict("records")
            with get_engine().begin() as conn:
                for i in range(0, len(records), 2000):
                    conn.execute(insert, records[i : i + 2000])
            log.info("wrote %d batter predictions for %d", len(records), season)

            # B7 starter heads -> pitcher_predictions (per-SP workload w, the
            # daily_v1 semantics), so star-pitcher slices are queryable per arm
            sp_out = sp_g[["game_pk", "sp_id"]].copy()
            sp_out["model_version"] = version
            sp_out["data_through_date"] = (pd.to_datetime(sp_g["game_date"])
                                           - pd.Timedelta(days=1)).dt.date.astype(str)
            sp_out["w_sp"] = sp_g["w_sp_val"].astype(float)
            sp_out["n_batters"] = 9
            sp_out["exp_k"] = sp_g["wsp_k"].astype(float)
            sp_out["exp_bb"] = sp_g["wsp_bb"].astype(float)
            sp_out["exp_h"] = sp_g["wsp_h"].astype(float)
            insert_sp = text("""
                INSERT INTO pitcher_predictions
                    (game_pk, sp_id, model_version, data_through_date,
                     w_sp, n_batters, exp_k, exp_bb, exp_h)
                VALUES (:game_pk, :sp_id, :model_version, :data_through_date,
                        :w_sp, :n_batters, :exp_k, :exp_bb, :exp_h)
                ON CONFLICT (game_pk, sp_id, model_version) DO UPDATE SET
                    data_through_date = EXCLUDED.data_through_date,
                    w_sp = EXCLUDED.w_sp, n_batters = EXCLUDED.n_batters,
                    exp_k = EXCLUDED.exp_k, exp_bb = EXCLUDED.exp_bb,
                    exp_h = EXCLUDED.exp_h, created_at = now()
            """)
            sp_records = sp_out.to_dict("records")
            with get_engine().begin() as conn:
                for i in range(0, len(sp_records), 2000):
                    conn.execute(insert_sp, sp_records[i : i + 2000])
            log.info("wrote %d starter predictions for %d", len(sp_records), season)

    # ---- pooled paired verdicts (B1/B2/B3), all seasons together
    P = {k: np.concatenate(v) for k, v in pooled.items() if v}
    print("\n=== B1/B2/B3 pooled paired verdicts "
          f"({len(P['base_h'])} batter-games, {min(seasons)}-{max(seasons)}) ===")
    for label, a_key, b_key in (("B1 per-SP w, hits MAE", "b1_h", "base_h"),
                                ("B1 per-SP w, K MAE", "b1_k", "base_k"),
                                ("B2 K-blend, K MAE", "b2_k", "base_k")):
        t = ttest_rel(P[a_key], P[b_key])
        print(f"  {label}: {P[a_key].mean():.4f} vs {P[b_key].mean():.4f} "
              f"| paired-t p={t.pvalue:.4f}")
    for head, y_key in (("p_hit", "hit1"), ("p_hr", "hr1")):
        raw = np.mean((P[head] - P[y_key]) ** 2)
        calb = np.mean((P[f"{head}_cal"] - P[y_key]) ** 2)
        t = ttest_rel((P[f"{head}_cal"] - P[y_key]) ** 2, (P[head] - P[y_key]) ** 2)
        print(f"  B3 isotonic, Brier {head}: {calb:.5f} vs {raw:.5f} "
              f"| paired-t p={t.pvalue:.4f} (2023 uncalibrated either way)")
    if pooled["rbi_m"]:
        n8 = len(np.concatenate(pooled["rbi_m"]))
        print(f"\n=== B8a expected-RBI pooled paired verdicts ({n8} batter-games) ===")
        for label, a_key, b_key in (
                ("RBI: outcome-x-slot model vs batter-marginal", "rbi_m", "rbi_base"),
                ("RBI: outcome-x-slot model vs slot-only", "rbi_m", "rbi_slot")):
            a, b = np.concatenate(pooled[a_key]), np.concatenate(pooled[b_key])
            t = ttest_rel(a, b)
            print(f"  {label}: {a.mean():.4f} vs {b.mean():.4f} "
                  f"| paired-t p={t.pvalue:.4f}")
    if len(pooled["spk_m"]):
        print(f"\n=== B7 starter heads, pooled paired verdicts "
              f"({len(np.concatenate(pooled['spk_m']))} starter-games) ===")
        for label, a_key, b_key in (
                ("K: model vs SP-marginal", "spk_m", "spk_base"),
                ("K: model vs whole-game board sum (w-scaled)", "spk_m", "spk_board"),
                ("K: per-SP workload w vs league w", "spk_wsp", "spk_m"),
                ("BB: model vs SP-marginal", "spbb_m", "spbb_base"),
                ("BB: per-SP workload w vs league w", "spbb_wsp", "spbb_m"),
                ("H allowed: model vs SP-marginal", "sph_m", "sph_base"),
                ("H allowed: per-SP workload w vs league w", "sph_wsp", "sph_m")):
            a, b = np.concatenate(pooled[a_key]), np.concatenate(pooled[b_key])
            t = ttest_rel(a, b)
            print(f"  {label}: {a.mean():.4f} vs {b.mean():.4f} "
                  f"| paired-t p={t.pvalue:.4f}")
    # ---- compare-base verdicts: flags-ON vs flags-OFF, selection pool split
    # from the 2026 confirm-only view (E8d hygiene — never select on 2026)
    if compare_base and cmp_pool["ll_on"]:
        flags_note = "+".join(enable_flags)
        for title, keep in (("selection pool (<=2025)", lambda s: s <= 2025),
                            ("2026 confirm-only", lambda s: s == 2026)):
            seas = sorted(s for s in cmp_pool["ll_on"] if keep(s))
            if not seas:
                continue

            def _cat(key):
                arrs = [a for s in seas for a in cmp_pool[key].get(s, [])]
                return np.concatenate(arrs) if arrs else np.array([])

            C = {k: _cat(k) for k in cmp_pool}
            print(f"\n=== [{flags_note}] flags-ON vs flags-OFF -- {title} "
                  f"({len(C['ll_on'])} PAs, {len(C['h_on'])} batter-games) ===")
            t = ttest_rel(C["ll_on"], C["ll_off"])
            print(f"  per-PA log loss: {C['ll_on'].mean():.5f} vs "
                  f"{C['ll_off'].mean():.5f} | paired-t p={t.pvalue:.4f}")
            for label, ka, kb in (("hits MAE", "h_on", "h_off"),
                                  ("K MAE", "k_on", "k_off")):
                t = ttest_rel(C[ka], C[kb])
                print(f"  {label}: {C[ka].mean():.4f} vs {C[kb].mean():.4f} "
                      f"| paired-t p={t.pvalue:.4f}")
            t = ttest_rel((C["p_hit_on"] - C["hit1"]) ** 2,
                          (C["p_hit_off"] - C["hit1"]) ** 2)
            print(f"  Brier p_hit: {np.mean((C['p_hit_on'] - C['hit1']) ** 2):.5f} vs "
                  f"{np.mean((C['p_hit_off'] - C['hit1']) ** 2):.5f} "
                  f"| paired-t p={t.pvalue:.4f}")
            if len(C["spk_on"]):
                t = ttest_rel(C["spk_on"], C["spk_off"])
                print(f"  starter K MAE: {C['spk_on'].mean():.4f} vs "
                      f"{C['spk_off'].mean():.4f} | paired-t p={t.pvalue:.4f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-preds", action="store_true")
    ap.add_argument("--version", default=MODEL_VERSION, help="model_version for stored preds")
    ap.add_argument("--seasons", type=int, nargs="+", default=list(TEST_SEASONS),
                    help="test seasons, each trained on all seasons before it "
                         "(e.g. --seasons 2026 backfills the current season)")
    ap.add_argument("--enable-flags", default="",
                    help="comma list of FEATURE_FLAGS to force ON for this run "
                         "(experiment arms, e.g. dev_l5)")
    ap.add_argument("--compare-base", action="store_true",
                    help="also train a flags-OFF model per season for paired "
                         "ON-vs-OFF verdicts (selection <=2025 and 2026 split)")
    args = ap.parse_args()
    run(seed=args.seed, write_preds=not args.no_preds, version=args.version,
        seasons=tuple(args.seasons),
        enable_flags=tuple(f for f in args.enable_flags.split(",") if f),
        compare_base=args.compare_base)


if __name__ == "__main__":
    main()
