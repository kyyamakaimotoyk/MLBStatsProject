"""Season-level walk-forward for the batter model (Phase 4).

For each test season S in 2023..2025: train the per-PA model on all seasons
before S, then evaluate
  1. per-PA multiclass log loss on S's PAs vs two baselines
     (league marginal, batter shrunken marginal), and
  2. game-level products on S's regular-season games where the announced
     probable actually started: expected stat lines (MAE vs the
     batter-marginal baseline aggregated identically) and calibration/Brier
     for the probability heads.

Game predictions land in batter_predictions (model_version pa_v1); every
window logs to model_registry.

Usage: python -m validation.walkforward_batter
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
        SELECT game_pk, player_id, pa, h, tb, hr, bb, so AS k
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


B4_COLS = ("B_XWOBA_F", "B_XWOBA_B", "B_XWOBA_O", "B_ARSENAL_MATCH")


def run(seed: int = 0, write_preds: bool = True, version: str = MODEL_VERSION,
        b4_compare: bool = False, seasons: tuple[int, ...] = TEST_SEASONS) -> None:
    comp = bf.build()
    pa = comp["pa"]
    feats = select_features(list(pa.columns), "batter_pa")
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
                                "b4_ll", "nob4_ll", "nob4_h", "nob4_k",
                                # B7: per-starter absolute errors
                                "spk_m", "spk_base", "spk_board", "spk_wsp",
                                "spbb_m", "spbb_base", "spbb_wsp",
                                "sph_m", "sph_base", "sph_wsp")}
    calib_hist = {"p_hit": [], "p_hr": [], "hit1": [], "hr1": []}
    feats_nob4 = [c for c in feats if c not in B4_COLS]

    for season in seasons:
        train = pa[pa["season"] < season]
        test = pa[pa["season"] == season]
        log.info("season %d: train %d PAs, test %d PAs", season, len(train), len(test))

        model = bm.BatterPAModel(seed=seed)
        model.fit(train, feats)

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
        sp_rows = pd.DataFrame({
            "game_pk": eligible["game_pk"].to_numpy(),
            "sp_id": eligible["sp_id"].to_numpy(),
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
        })
        sp_g = sp_rows.groupby(["game_pk", "sp_id"], as_index=False).agg(
            n=("m_k", "size"), m_k=("m_k", "sum"), m_bb=("m_bb", "sum"),
            m_h=("m_h", "sum"), b_k=("b_k", "sum"), b_bb=("b_bb", "sum"),
            b_h=("b_h", "sum"), board_k=("board_k", "sum"), wsp_k=("wsp_k", "sum"),
            wsp_bb=("wsp_bb", "sum"), wsp_h=("wsp_h", "sum"))
        sp_g = sp_g[sp_g["n"] == 9].merge(actual_sp, on=["game_pk", "sp_id"],
                                          how="inner")
        # the SP faces ~w of each batter's PAs (league constant, as in the
        # game mixture); wsp_k already carries its per-SP share
        for col in ("m_k", "m_bb", "m_h", "b_k", "b_bb", "b_h", "board_k"):
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

        # ---- B2: blend the K probability halfway back to the batter marginal
        i_k = CLASSES.index("K")
        p_b2 = p_mix.copy()
        k_blend = 0.5 * p_mix[:, i_k] + 0.5 * p_base[:, i_k]
        scale = (1 - k_blend) / np.clip(1 - p_mix[:, i_k], 1e-9, None)
        p_b2 *= scale[:, None]
        p_b2[:, i_k] = k_blend
        agg_b2 = bm.aggregate_game(p_b2, pa_dist)

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

        # ---- B4: paired comparison against a model WITHOUT the arsenal cols
        if b4_compare:
            model_nob4 = bm.BatterPAModel(seed=seed)
            model_nob4.fit(train, feats_nob4)
            y_idx = np.arange(len(test))
            probs_nob4 = model_nob4.predict_proba(test, feats_nob4)
            pooled["b4_ll"].append(-np.log(np.clip(probs[y_idx, y], 1e-12, None)))
            pooled["nob4_ll"].append(-np.log(np.clip(probs_nob4[y_idx, y], 1e-12, None)))
            p_mix_n = (w * model_nob4.predict_proba(vs_sp, feats_nob4)
                       + (1 - w) * model_nob4.predict_proba(vs_lg, feats_nob4))
            agg_n = bm.aggregate_game(p_mix_n, pa_dist)
            pooled["nob4_h"].append(np.abs(actual_h - agg_n["exp_h"]))
            pooled["nob4_k"].append(np.abs(actual_k - agg_n["exp_k"]))

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
        log.info("season %d game-level: %s", season,
                 {k: round(v, 4) for k, v in metrics.items() if k.startswith(("mae", "brier"))})

        model_registry.log_model_run(
            model_type="lgbm_pa", target="batter", run_kind="walkforward_window",
            metrics=metrics, hyperparams=bm.LGBM_PA_PARAMS,
            feature_set_version=version,
            train_window=(str(train["game_date"].min().date()),
                          str(train["game_date"].max().date())),
            test_window=(f"{season}-01-01", f"{season}-12-31"),
            notes=f"seed={seed}",
        )

        if write_preds:
            rows = eligible[["game_pk", "player_id", "sp_id", "lineup_slot"]].copy()
            rows["model_version"] = version
            rows["data_through_date"] = (eligible["game_date"]
                                         - pd.Timedelta(days=1)).dt.date.astype(str)
            for k in ("exp_pa", "exp_h", "exp_tb", "exp_hr", "exp_bb", "exp_k",
                      "p_hit", "p_hr", "p_tb2", "p_bb"):
                rows[k] = agg[k]
            insert = text("""
                INSERT INTO batter_predictions
                    (game_pk, player_id, model_version, data_through_date, sp_id,
                     lineup_slot, exp_pa, exp_h, exp_tb, exp_hr, exp_bb, exp_k,
                     p_hit, p_hr, p_tb2, p_bb)
                VALUES (:game_pk, :player_id, :model_version, :data_through_date, :sp_id,
                        :lineup_slot, :exp_pa, :exp_h, :exp_tb, :exp_hr, :exp_bb, :exp_k,
                        :p_hit, :p_hr, :p_tb2, :p_bb)
                ON CONFLICT (game_pk, player_id, model_version) DO UPDATE SET
                    data_through_date = EXCLUDED.data_through_date,
                    sp_id = EXCLUDED.sp_id, lineup_slot = EXCLUDED.lineup_slot,
                    exp_pa = EXCLUDED.exp_pa, exp_h = EXCLUDED.exp_h,
                    exp_tb = EXCLUDED.exp_tb, exp_hr = EXCLUDED.exp_hr,
                    exp_bb = EXCLUDED.exp_bb, exp_k = EXCLUDED.exp_k,
                    p_hit = EXCLUDED.p_hit, p_hr = EXCLUDED.p_hr,
                    p_tb2 = EXCLUDED.p_tb2, p_bb = EXCLUDED.p_bb,
                    created_at = now()
            """)
            records = rows.to_dict("records")
            with get_engine().begin() as conn:
                for i in range(0, len(records), 2000):
                    conn.execute(insert, records[i : i + 2000])
            log.info("wrote %d batter predictions for %d", len(records), season)

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
    if pooled["b4_ll"] and pooled["b4_ll"][0] is not None and len(pooled["b4_ll"]):
        ll_a, ll_b = np.concatenate(pooled["b4_ll"]), np.concatenate(pooled["nob4_ll"])
        t = ttest_rel(ll_a, ll_b)
        print(f"  B4 arsenal cross, per-PA log loss: {ll_a.mean():.5f} (with) vs "
              f"{ll_b.mean():.5f} (without) | paired-t p={t.pvalue:.4f}")
        for label, a_key, b_key in (("B4 hits MAE", "base_h", "nob4_h"),
                                    ("B4 K MAE", "base_k", "nob4_k")):
            t = ttest_rel(P[a_key], P[b_key])
            print(f"  {label}: {P[a_key].mean():.4f} (with) vs {P[b_key].mean():.4f} "
                  f"(without) | paired-t p={t.pvalue:.4f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-preds", action="store_true")
    ap.add_argument("--version", default=MODEL_VERSION, help="model_version for stored preds")
    ap.add_argument("--b4-compare", action="store_true",
                    help="also train a no-arsenal model per season for paired B4 tests")
    ap.add_argument("--seasons", type=int, nargs="+", default=list(TEST_SEASONS),
                    help="test seasons, each trained on all seasons before it "
                         "(e.g. --seasons 2026 backfills the current season)")
    args = ap.parse_args()
    run(seed=args.seed, write_preds=not args.no_preds, version=args.version,
        b4_compare=args.b4_compare, seasons=tuple(args.seasons))


if __name__ == "__main__":
    main()
