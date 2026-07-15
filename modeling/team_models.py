"""Team-level model suite (Phase 3).

Structural design (docs/PROJECT_PLAN.md §7): the primary model predicts each
team's RUNS SCORED with two heads on the same feature row; margin = home-away
and total = home+away fall out coherently. Direct margin/total regressors are
trained as comparison baselines — walk-forward decides which ships.

Hyperparameters are deliberately conservative (shallow, heavily regularized) —
the NBA project's E1 lesson: tabular sports data overfits fast, constrain first
and loosen only with walk-forward evidence.

Win probability is Phi(pred_margin / sigma) with sigma from train residuals.
In-sample sigma runs slightly hot (overconfident p_home); a proper calibration
layer is a Phase 5 concern once walk-forward says which model ships.
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from scipy.stats import norm
from sklearn.linear_model import LinearRegression
from xgboost import XGBRegressor

LGBM_PARAMS = dict(
    n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=50,
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
    n_jobs=-1, verbosity=-1,
)
XGB_PARAMS = dict(
    n_estimators=400, learning_rate=0.03, max_depth=4, min_child_weight=10,
    subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, verbosity=0,
)


def _regressor(family: str, kind: str, seed: int):
    """kind: 'count' (Poisson, for runs/totals) or 'real' (L2, for margin)."""
    if family == "lgbm":
        return LGBMRegressor(objective="poisson" if kind == "count" else "regression",
                             random_state=seed, **LGBM_PARAMS)
    if family == "xgb":
        return XGBRegressor(objective="count:poisson" if kind == "count" else "reg:squarederror",
                            random_state=seed, **XGB_PARAMS)
    raise ValueError(f"unknown family {family!r}")


def _sigma(residuals: np.ndarray) -> float:
    return max(float(np.std(residuals)), 1.0)


class RunsModel:
    """Two Poisson heads (home runs, away runs) on the shared feature row."""

    def __init__(self, family: str, seed: int = 0):
        self.family = family
        self.seed = seed
        self.hyperparams = {"family": family, "structure": "runs_two_head",
                            **(LGBM_PARAMS if family == "lgbm" else XGB_PARAMS)}

    def fit(self, train: pd.DataFrame, feats: list[str]) -> None:
        X = train[feats]
        self.head_home = _regressor(self.family, "count", self.seed)
        self.head_away = _regressor(self.family, "count", self.seed + 1)
        self.head_home.fit(X, train["TARGET_HOME_RUNS"])
        self.head_away.fit(X, train["TARGET_AWAY_RUNS"])
        pred_margin = self.head_home.predict(X) - self.head_away.predict(X)
        self.margin_sigma = _sigma(train["TARGET_MARGIN"].to_numpy() - pred_margin)

    def predict(self, test: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
        X = test[feats]
        home = self.head_home.predict(X)
        away = self.head_away.predict(X)
        margin = home - away
        return pd.DataFrame({
            "pred_home_runs": home, "pred_away_runs": away,
            "pred_margin": margin, "pred_total": home + away,
            "p_home": norm.cdf(margin / self.margin_sigma),
        }, index=test.index)


class RunsClsModel(RunsModel):
    """E1: margins/totals from the runs heads as usual, but win probability
    from a dedicated binary classifier head instead of Phi(margin/sigma) —
    Elo predicts probability directly and beats the squashed margin; this
    lets the trees do the same."""

    def __init__(self, family: str, seed: int = 0):
        super().__init__(family, seed)
        self.hyperparams = {**self.hyperparams, "structure": "runs_two_head_cls"}

    def fit(self, train: pd.DataFrame, feats: list[str]) -> None:
        super().fit(train, feats)
        self.cls = LGBMClassifier(random_state=self.seed + 2, **LGBM_PARAMS)
        self.cls.fit(train[feats], (train["TARGET_MARGIN"] > 0).astype(int))

    def predict(self, test: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
        out = super().predict(test, feats)
        out["p_home"] = self.cls.predict_proba(test[feats])[:, 1]
        return out


class DirectModel:
    """Direct margin (L2) and total (Poisson) heads — the comparison baseline."""

    def __init__(self, family: str, seed: int = 0):
        self.family = family
        self.seed = seed
        self.hyperparams = {"family": family, "structure": "direct",
                            **(LGBM_PARAMS if family == "lgbm" else XGB_PARAMS)}

    def fit(self, train: pd.DataFrame, feats: list[str]) -> None:
        X = train[feats]
        self.head_margin = _regressor(self.family, "real", self.seed)
        self.head_total = _regressor(self.family, "count", self.seed + 1)
        self.head_margin.fit(X, train["TARGET_MARGIN"])
        self.head_total.fit(X, train["TARGET_TOTAL"])
        self.margin_sigma = _sigma(
            train["TARGET_MARGIN"].to_numpy() - self.head_margin.predict(X))

    def predict(self, test: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
        X = test[feats]
        margin = self.head_margin.predict(X)
        total = self.head_total.predict(X)
        return pd.DataFrame({
            "pred_home_runs": (total + margin) / 2.0,
            "pred_away_runs": (total - margin) / 2.0,
            "pred_margin": margin, "pred_total": total,
            "p_home": norm.cdf(margin / self.margin_sigma),
        }, index=test.index)


class EloBaseline:
    """Elo as the strength floor: margin from a 1-feature linear fit on
    ELO_DIFF, total = train mean, p_home straight from the rating table."""

    hyperparams = {"structure": "elo_baseline"}

    def __init__(self, seed: int = 0):
        pass

    def fit(self, train: pd.DataFrame, feats: list[str]) -> None:
        ok = train[["ELO_DIFF", "TARGET_MARGIN"]].dropna()
        self.margin_fit = LinearRegression().fit(
            ok[["ELO_DIFF"]], ok["TARGET_MARGIN"])
        self.mean_total = float(train["TARGET_TOTAL"].mean())

    def predict(self, test: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
        margin = self.margin_fit.predict(test[["ELO_DIFF"]].fillna(0.0))
        return pd.DataFrame({
            "pred_home_runs": (self.mean_total + margin) / 2.0,
            "pred_away_runs": (self.mean_total - margin) / 2.0,
            "pred_margin": margin,
            "pred_total": self.mean_total,
            "p_home": test["ELO_P_HOME"].fillna(0.54),
        }, index=test.index)


class ConstBaseline:
    """Home-field-only floor: every model must beat this or it learned nothing."""

    hyperparams = {"structure": "const_baseline"}

    def __init__(self, seed: int = 0):
        pass

    def fit(self, train: pd.DataFrame, feats: list[str]) -> None:
        self.mean_margin = float(train["TARGET_MARGIN"].mean())
        self.mean_total = float(train["TARGET_TOTAL"].mean())
        self.home_rate = float((train["TARGET_MARGIN"] > 0).mean())

    def predict(self, test: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
        n = len(test)
        return pd.DataFrame({
            "pred_home_runs": np.full(n, (self.mean_total + self.mean_margin) / 2.0),
            "pred_away_runs": np.full(n, (self.mean_total - self.mean_margin) / 2.0),
            "pred_margin": np.full(n, self.mean_margin),
            "pred_total": np.full(n, self.mean_total),
            "p_home": np.full(n, self.home_rate),
        }, index=test.index)


MODEL_TYPES = {
    "lgbm_runs": lambda seed=0: RunsModel("lgbm", seed),
    "lgbm_runs_cls": lambda seed=0: RunsClsModel("lgbm", seed),
    "lgbm_direct": lambda seed=0: DirectModel("lgbm", seed),
    "xgb_runs": lambda seed=0: RunsModel("xgb", seed),
    "xgb_direct": lambda seed=0: DirectModel("xgb", seed),
    "elo": lambda seed=0: EloBaseline(seed),
    "const": lambda seed=0: ConstBaseline(seed),
}


def make(model_type: str, seed: int = 0):
    if model_type not in MODEL_TYPES:
        raise ValueError(f"unknown model type {model_type!r}; known: {sorted(MODEL_TYPES)}")
    return MODEL_TYPES[model_type](seed)
