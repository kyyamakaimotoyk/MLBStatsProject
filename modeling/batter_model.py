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


def pa_count_distribution(train_pa_per_game: pd.DataFrame, max_pa: int = 7):
    """Empirical P(n_PA = k) and mean by (lineup_slot, is_home) from training
    seasons. Returns lookup(slot_array, is_home_array) -> (n, max_pa+1)."""
    dists = {}
    grouped = train_pa_per_game.groupby(["lineup_slot", "is_home"])
    overall = np.bincount(train_pa_per_game["pa"].clip(0, max_pa), minlength=max_pa + 1)
    overall = overall / overall.sum()
    for (slot, home), grp in grouped:
        counts = np.bincount(grp["pa"].clip(0, max_pa), minlength=max_pa + 1)
        dists[(slot, home)] = counts / counts.sum()

    def lookup(slots, homes) -> np.ndarray:
        return np.vstack([dists.get((s, h), overall) for s, h in zip(slots, homes)])

    return lookup
