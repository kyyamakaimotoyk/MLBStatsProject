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
        FROM lineups l JOIN games g USING (game_pk) WHERE g.is_final
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
    return lineups


# Matchup assembly lives in modeling.batter_model.assemble_matchup — shared
# with the daily pipeline so the two paths can never drift.


def run(seed: int = 0, write_preds: bool = True) -> None:
    comp = bf.build()
    pa = comp["pa"]
    feats = select_features(list(pa.columns), "batter_pa")
    park = comp["park"]
    sides = _load_game_side_data()

    # league share of PAs taken by the game's starter (mixing weight w)
    starters = pd.read_sql(text(
        "SELECT game_pk, player_id FROM pitcher_game_lines WHERE is_starter"), get_engine())
    starter_keys = set(zip(starters["game_pk"], starters["player_id"]))

    for season in TEST_SEASONS:
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

        metrics = {"n_pa_test": int(len(test)), "n_batter_games": int(len(eligible)),
                   "ll_model": ll_model, "ll_marginal": ll_marginal, "ll_league": ll_league,
                   "sp_pa_share_w": float(w)}
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
        log.info("season %d game-level: %s", season,
                 {k: round(v, 4) for k, v in metrics.items() if k.startswith(("mae", "brier"))})

        model_registry.log_model_run(
            model_type="lgbm_pa", target="batter", run_kind="walkforward_window",
            metrics=metrics, hyperparams=bm.LGBM_PA_PARAMS,
            feature_set_version=MODEL_VERSION,
            train_window=(str(train["game_date"].min().date()),
                          str(train["game_date"].max().date())),
            test_window=(f"{season}-01-01", f"{season}-12-31"),
            notes=f"seed={seed}",
        )

        if write_preds:
            rows = eligible[["game_pk", "player_id", "sp_id", "lineup_slot"]].copy()
            rows["model_version"] = MODEL_VERSION
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-preds", action="store_true")
    args = ap.parse_args()
    run(seed=args.seed, write_preds=not args.no_preds)


if __name__ == "__main__":
    main()
