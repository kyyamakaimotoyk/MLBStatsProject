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
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
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
# E8h model-family suite (the hoopmodel pattern: trees vs RF vs NN vs linear,
# walk-forward decides). Conservative by the same E1 lesson as the GBMs.
RF_PARAMS = dict(n_estimators=500, min_samples_leaf=15, max_features=0.5, n_jobs=-1)
HGB_PARAMS = dict(max_iter=400, learning_rate=0.03, max_leaf_nodes=15,
                  min_samples_leaf=50, l2_regularization=1.0)
RIDGE_PARAMS = dict(alpha=10.0)
NN_PARAMS = dict(hidden=(128, 64, 32), dropout=0.3, lr=1e-3, weight_decay=1e-4,
                 epochs=80, batch_size=256)
FAMILY_PARAMS = {"lgbm": LGBM_PARAMS, "xgb": XGB_PARAMS, "rf": RF_PARAMS,
                 "hgb": HGB_PARAMS, "ridge": RIDGE_PARAMS, "nn": NN_PARAMS}


class _TorchRegressor:
    """PyTorch MLP head with the NBA project's architecture (128-64-32,
    BatchNorm + ReLU + Dropout), wrapped in the sklearn fit/predict shape so
    RunsModel can use it as a drop-in head. Median-imputes and standardizes
    internally (trees tolerate NaN; the net does not). torch is imported
    lazily — it is an experiment-only dependency, deliberately NOT in
    requirements.txt so the Docker images never inherit it."""

    def __init__(self, seed: int, hidden=(128, 64, 32), dropout=0.3, lr=1e-3,
                 weight_decay=1e-4, epochs=80, batch_size=256):
        self.seed = seed
        self.hidden, self.dropout = hidden, dropout
        self.lr, self.weight_decay = lr, weight_decay
        self.epochs, self.batch_size = epochs, batch_size

    def _prep(self, X, fit: bool = False) -> np.ndarray:
        X = np.asarray(X, dtype=np.float64)
        if fit:
            self.med = np.nan_to_num(np.nanmedian(X, axis=0))
            Xi = np.where(np.isnan(X), self.med, X)
            self.mu = Xi.mean(axis=0)
            self.sd = Xi.std(axis=0)
            self.sd[self.sd == 0] = 1.0
        else:
            Xi = np.where(np.isnan(X), self.med, X)
        return ((Xi - self.mu) / self.sd).astype(np.float32)

    def fit(self, X, y) -> None:
        import torch
        from torch import nn
        Xs = self._prep(X, fit=True)
        yv = np.asarray(y, dtype=np.float32).reshape(-1, 1)
        torch.manual_seed(self.seed)
        layers, d = [], Xs.shape[1]
        for h in self.hidden:
            layers += [nn.Linear(d, h), nn.BatchNorm1d(h), nn.ReLU(),
                       nn.Dropout(self.dropout)]
            d = h
        layers.append(nn.Linear(d, 1))
        self.net = nn.Sequential(*layers)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr,
                               weight_decay=self.weight_decay)
        loss_fn = nn.MSELoss()
        ds = torch.utils.data.TensorDataset(torch.from_numpy(Xs), torch.from_numpy(yv))
        gen = torch.Generator().manual_seed(self.seed)
        # drop_last: a trailing batch of size 1 breaks BatchNorm in train mode
        loader = torch.utils.data.DataLoader(ds, batch_size=self.batch_size,
                                             shuffle=True, generator=gen,
                                             drop_last=len(ds) > self.batch_size)
        self.net.train()
        for _ in range(self.epochs):
            for xb, yb in loader:
                opt.zero_grad()
                loss = loss_fn(self.net(xb), yb)
                loss.backward()
                opt.step()

    def predict(self, X) -> np.ndarray:
        import torch
        Xs = self._prep(X)
        self.net.eval()
        with torch.no_grad():
            return self.net(torch.from_numpy(Xs)).numpy().ravel()


def _regressor(family: str, kind: str, seed: int):
    """kind: 'count' (Poisson, for runs/totals) or 'real' (L2, for margin)."""
    if family == "lgbm":
        return LGBMRegressor(objective="poisson" if kind == "count" else "regression",
                             random_state=seed, **LGBM_PARAMS)
    if family == "xgb":
        return XGBRegressor(objective="count:poisson" if kind == "count" else "reg:squarederror",
                            random_state=seed, **XGB_PARAMS)
    if family == "rf":  # no Poisson objective; L2 on counts (sklearn handles NaN)
        return RandomForestRegressor(random_state=seed, **RF_PARAMS)
    if family == "hgb":
        return HistGradientBoostingRegressor(
            loss="poisson" if kind == "count" else "squared_error",
            random_state=seed, **HGB_PARAMS)
    if family == "ridge":  # linear floor; needs imputation + scaling
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                             Ridge(**RIDGE_PARAMS))
    if family == "nn":
        return _TorchRegressor(seed=seed, **NN_PARAMS)
    raise ValueError(f"unknown family {family!r}")


def _sigma(residuals: np.ndarray) -> float:
    return max(float(np.std(residuals)), 1.0)


class RunsModel:
    """Two Poisson heads (home runs, away runs) on the shared feature row."""

    def __init__(self, family: str, seed: int = 0):
        self.family = family
        self.seed = seed
        self.hyperparams = {"family": family, "structure": "runs_two_head",
                            **FAMILY_PARAMS[family]}

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


class RunsPlusTotalsModel(RunsModel):
    """E6: runs heads for margin/p_home unchanged + a DEDICATED totals head.

    The totals head trains on a totals-focused subset: DIFF_* columns and
    ELO_DIFF/ELO_P_HOME are margin information — noise for totals — while
    park/weather/umpire, both starters' quality, both offenses, and both
    lineups are the drivers. Keeping the runs heads for margin/p_home means
    a paired comparison against RunsModel isolates the totals change.
    """

    def __init__(self, family: str, seed: int = 0):
        super().__init__(family, seed)
        self.hyperparams = {**self.hyperparams, "structure": "runs_two_head_totals_head"}

    def fit(self, train: pd.DataFrame, feats: list[str]) -> None:
        super().fit(train, feats)
        self.total_feats = [c for c in feats if not c.startswith("DIFF_")
                            and c not in ("ELO_DIFF", "ELO_P_HOME")]
        self.head_total = _regressor(self.family, "count", self.seed + 3)
        self.head_total.fit(train[self.total_feats], train["TARGET_TOTAL"])

    def predict(self, test: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
        out = super().predict(test, feats)
        out["pred_total"] = self.head_total.predict(test[self.total_feats])
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
    "lgbm_runs_tt": lambda seed=0: RunsPlusTotalsModel("lgbm", seed),
    "lgbm_direct": lambda seed=0: DirectModel("lgbm", seed),
    "xgb_runs": lambda seed=0: RunsModel("xgb", seed),
    "xgb_direct": lambda seed=0: DirectModel("xgb", seed),
    # E8h model-family suite (hoopmodel pattern): RF / sklearn HGB / torch MLP
    # / ridge floor, same runs-two-head structure
    "rf_runs": lambda seed=0: RunsModel("rf", seed),
    "hgb_runs": lambda seed=0: RunsModel("hgb", seed),
    "nn_runs": lambda seed=0: RunsModel("nn", seed),
    "ridge_runs": lambda seed=0: RunsModel("ridge", seed),
    "elo": lambda seed=0: EloBaseline(seed),
    "const": lambda seed=0: ConstBaseline(seed),
}


def make(model_type: str, seed: int = 0):
    if model_type not in MODEL_TYPES:
        raise ValueError(f"unknown model type {model_type!r}; known: {sorted(MODEL_TYPES)}")
    return MODEL_TYPES[model_type](seed)
