"""Noise-aware model comparison — the port of the NBA e3_noise_ablation
harness, the bar every feature/model change must clear before shipping.

Given two models' walk-forward predictions over the SAME games, runs paired
significance tests so that seed/test-window noise can't masquerade as signal:

  - win accuracy:  exact McNemar (binomial test on discordant picks)
  - margin/total MAE: paired t-test on per-game |error|
  - AUC: paired bootstrap on the delta (n resamples)

Usage:
    python -m validation.ablation --a lgbm_runs --b elo
    python -m validation.ablation --a lgbm_runs --b xgb_runs --version v20260714_121152
"""

import argparse

import numpy as np
import pandas as pd
from scipy.stats import binomtest, ttest_rel
from sklearn.metrics import roc_auc_score
from sqlalchemy import text

from core import features_io
from core.db import get_engine


def mcnemar_accuracy(win: np.ndarray, pick_a: np.ndarray, pick_b: np.ndarray) -> dict:
    correct_a, correct_b = pick_a == win, pick_b == win
    a_only = int(np.sum(correct_a & ~correct_b))
    b_only = int(np.sum(~correct_a & correct_b))
    n = a_only + b_only
    p = binomtest(a_only, n, 0.5).pvalue if n else 1.0
    return {"acc_a": float(correct_a.mean()), "acc_b": float(correct_b.mean()),
            "a_only_correct": a_only, "b_only_correct": b_only, "p_mcnemar": float(p)}


def paired_mae(actual: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray) -> dict:
    err_a, err_b = np.abs(actual - pred_a), np.abs(actual - pred_b)
    p = 1.0 if np.allclose(err_a, err_b) else float(ttest_rel(err_a, err_b).pvalue)
    return {"mae_a": float(err_a.mean()), "mae_b": float(err_b.mean()),
            "p_paired_t": p}


def paired_prob(win: np.ndarray, p_a: np.ndarray, p_b: np.ndarray) -> dict:
    """Paired per-game log-loss and Brier tests on p_home. Probability-only
    changes (calibration, Skellam) leave picks and AUC ranking untouched, so
    these are the metrics that can actually detect them."""
    w = win.astype(float)
    ca, cb = np.clip(p_a, 1e-6, 1 - 1e-6), np.clip(p_b, 1e-6, 1 - 1e-6)
    ll_a = -(w * np.log(ca) + (1 - w) * np.log(1 - ca))
    ll_b = -(w * np.log(cb) + (1 - w) * np.log(1 - cb))
    br_a, br_b = (p_a - w) ** 2, (p_b - w) ** 2
    p_ll = 1.0 if np.allclose(ll_a, ll_b) else float(ttest_rel(ll_a, ll_b).pvalue)
    p_br = 1.0 if np.allclose(br_a, br_b) else float(ttest_rel(br_a, br_b).pvalue)
    return {"logloss_a": float(ll_a.mean()), "logloss_b": float(ll_b.mean()),
            "p_logloss": p_ll,
            "brier_a": float(br_a.mean()), "brier_b": float(br_b.mean()),
            "p_brier": p_br}


def bootstrap_auc(win: np.ndarray, score_a: np.ndarray, score_b: np.ndarray,
                  n_boot: int = 2000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    n = len(win)
    deltas = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        w = win[idx]
        if 0 < w.sum() < len(w):
            deltas.append(roc_auc_score(w, score_a[idx]) - roc_auc_score(w, score_b[idx]))
    deltas = np.array(deltas)
    p = float(2 * min((deltas <= 0).mean(), (deltas >= 0).mean()))
    return {"auc_a": float(roc_auc_score(win, score_a)),
            "auc_b": float(roc_auc_score(win, score_b)),
            "auc_delta_ci90": [float(np.percentile(deltas, 5)), float(np.percentile(deltas, 95))],
            "p_bootstrap": p}


def load_predictions(model_type: str, version: str) -> pd.DataFrame:
    return pd.read_sql(
        text("""
            SELECT p.game_pk, p.pred_margin, p.pred_total, p.p_home,
                   g.game_date,
                   g.home_score - g.away_score AS actual_margin,
                   g.home_score + g.away_score AS actual_total
            FROM model_predictions p
            JOIN games g USING (game_pk)
            WHERE p.model_type = :m AND p.model_version = :v
        """),
        get_engine(), params={"m": model_type, "v": version},
    )


def compare(model_a: str, model_b: str, version_a: str, version_b: str,
            months: tuple[int, ...] = (), seasons: tuple[int, ...] = ()) -> None:
    """months, when given, restricts the comparison to games in those calendar
    months (e.g. 3,4,5,6 = the March-June slice where the market gap lives).
    Diagnostic only — the pooled comparison stays the shipping bar.
    seasons restricts to those years — the E8d selection window (2023,2024,
    2025) selects among arms while 2026 stays confirm-only."""
    a = load_predictions(model_a, version_a)
    b = load_predictions(model_b, version_b)
    merged = a.merge(b, on=["game_pk", "game_date", "actual_margin", "actual_total"],
                     suffixes=("_a", "_b"))
    if merged.empty:
        raise SystemExit("no overlapping predictions; run validation.walkforward first")
    slice_note = ""
    if seasons:
        merged = merged[pd.to_datetime(merged["game_date"]).dt.year.isin(seasons)]
        slice_note += f", seasons={sorted(seasons)}"
        if merged.empty:
            raise SystemExit("no overlapping predictions in the requested seasons")
    if months:
        merged = merged[pd.to_datetime(merged["game_date"]).dt.month.isin(months)]
        slice_note += f", months={sorted(months)}"
        if merged.empty:
            raise SystemExit("no overlapping predictions in the requested months")
    win = (merged["actual_margin"] > 0).to_numpy()

    print(f"=== {model_a}@{version_a} (A) vs {model_b}@{version_b} (B), "
          f"{len(merged)} shared games{slice_note} ===")
    acc = mcnemar_accuracy(win, merged["pred_margin_a"].to_numpy() > 0,
                           merged["pred_margin_b"].to_numpy() > 0)
    print(f"accuracy: A {acc['acc_a']:.4f} vs B {acc['acc_b']:.4f} | "
          f"discordant {acc['a_only_correct']}/{acc['b_only_correct']} | "
          f"McNemar p={acc['p_mcnemar']:.4f}")
    m = paired_mae(merged["actual_margin"].to_numpy(float),
                   merged["pred_margin_a"].to_numpy(), merged["pred_margin_b"].to_numpy())
    print(f"margin MAE: A {m['mae_a']:.4f} vs B {m['mae_b']:.4f} | paired-t p={m['p_paired_t']:.4f}")
    t = paired_mae(merged["actual_total"].to_numpy(float),
                   merged["pred_total_a"].to_numpy(), merged["pred_total_b"].to_numpy())
    print(f"total MAE:  A {t['mae_a']:.4f} vs B {t['mae_b']:.4f} | paired-t p={t['p_paired_t']:.4f}")
    auc = bootstrap_auc(win, merged["p_home_a"].to_numpy(), merged["p_home_b"].to_numpy())
    print(f"AUC: A {auc['auc_a']:.4f} vs B {auc['auc_b']:.4f} | "
          f"delta CI90 [{auc['auc_delta_ci90'][0]:+.4f}, {auc['auc_delta_ci90'][1]:+.4f}] | "
          f"bootstrap p={auc['p_bootstrap']:.4f}")
    pr = paired_prob(win, merged["p_home_a"].to_numpy(float),
                     merged["p_home_b"].to_numpy(float))
    print(f"log loss: A {pr['logloss_a']:.4f} vs B {pr['logloss_b']:.4f} | "
          f"paired-t p={pr['p_logloss']:.4f}")
    print(f"Brier:    A {pr['brier_a']:.4f} vs B {pr['brier_b']:.4f} | "
          f"paired-t p={pr['p_brier']:.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--version", default=None, help="defaults to current team feature set")
    ap.add_argument("--version-a", default=None, help="override snapshot for model A")
    ap.add_argument("--version-b", default=None, help="override snapshot for model B")
    ap.add_argument("--months", default="", help="comma list of calendar months to slice "
                    "(diagnostic; e.g. 3,4,5,6 for the early-season window)")
    ap.add_argument("--seasons", default="", help="comma list of years to slice "
                    "(e.g. 2023,2024,2025 = the E8d selection window)")
    args = ap.parse_args()
    version = args.version or features_io.current_version("team")
    months = tuple(int(m) for m in args.months.split(",") if m)
    seasons = tuple(int(s) for s in args.seasons.split(",") if s)
    compare(args.a, args.b, args.version_a or version, args.version_b or version,
            months=months, seasons=seasons)


if __name__ == "__main__":
    main()
