"""Wave-1 probability suite (E11/E12/E10, 2026-07 cycle): offline transforms
over STORED walk-forward predictions.

Every variant here changes only how p_home (and for the E10 ensemble, the
margin) is derived from predictions that already exist in model_predictions —
the underlying heads are untouched, so nothing needs retraining, and the
transforms are fit per month on STRICTLY PRIOR months' out-of-sample games
only (the B3/B6 growing-history pattern; fixes parked-E8c's in-sample flaw).
Before MIN_FIT prior games exist, the base p_home passes through unchanged.

Variants (sources: docs/literature_review_2026-07.md):
  iso  E11a isotonic recalibration of p_home
  sig  E11b p = Phi(margin / sigma_oos), sigma from prior OOS margin residuals
  log  E11c 2-feature logistic: sigma-scaled margin + logit(stored Elo p)
  sk   E12a Skellam P(H>A) from the two Poisson heads, tie mass renormalized
  hv   E12b hetero-sigma: p = Phi(margin / sqrt(c*(lam_h+lam_a))), c from
       prior OOS residuals — absorbs run overdispersion + score correlation
       (the Karlis-Ntzoufras lambda3 identity)
  rfens E10 lgbm+RF margin average (changes picks); p via sigma_oos

Writes each variant to model_predictions under a derived model_type
(lgbm_runs+8s -> lgbm_runs+iso8, ..., seed suffixes preserved) and logs a
registry summary row. Significance comes from validation.ablation afterward.

Usage:
    python -m validation.recalibrate --base lgbm_runs+8s
    python -m validation.recalibrate --base lgbm_runs+8s_s1   # seed confirm
"""

import argparse
import logging

import numpy as np
import pandas as pd
from scipy.stats import norm, skellam
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sqlalchemy import text

from core import model_registry
from core.db import get_engine
from validation.ablation import load_predictions

log = logging.getLogger("recalibrate")

VERSION = "v20260716_083741"
MIN_FIT = 1500
LAM_CLIP = (0.25, 15.0)
ELO_BASE = "elo+8s"
RF_BASE = "rf_runs+8s"


def _variant_label(base: str, variant: str) -> str:
    """lgbm_runs+8s -> lgbm_runs+iso8; lgbm_runs+8s_s1 -> lgbm_runs+iso8_s1;
    the E10 ensemble gets its own family name."""
    if variant == "rfens":
        return base.replace("lgbm_runs+8s", "lgbm_rf+ens8")
    return base.replace("+8s", f"+{variant}8")


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _metrics(d: pd.DataFrame, p: np.ndarray, margin: np.ndarray) -> dict:
    win = (d["actual_margin"] > 0).to_numpy()
    w = win.astype(float)
    pc = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "n_games": int(len(d)),
        "win_acc": float(np.mean((margin > 0) == win)),
        "win_auc": float(roc_auc_score(win, p)),
        "win_brier": float(np.mean((p - w) ** 2)),
        "win_logloss": float(-np.mean(w * np.log(pc) + (1 - w) * np.log(1 - pc))),
        "margin_mae": float(np.mean(np.abs(d["actual_margin"].to_numpy() - margin))),
    }


def _monthly(d: pd.DataFrame, transform) -> np.ndarray:
    """Apply transform(fit_df, cur_df) -> p per month, fitting on strictly
    prior months pooled; pass-through (base p) while prior < MIN_FIT."""
    month = pd.to_datetime(d["game_date"]).dt.to_period("M")
    out = d["p_home"].to_numpy(float).copy()
    for m in month.drop_duplicates().sort_values():
        fit_mask, cur_mask = (month < m).to_numpy(), (month == m).to_numpy()
        if fit_mask.sum() >= MIN_FIT:
            out[cur_mask] = np.clip(transform(d[fit_mask], d[cur_mask]), 1e-6, 1 - 1e-6)
    return out


def run(base: str) -> pd.DataFrame:
    d = load_predictions(base, VERSION).sort_values("game_date").reset_index(drop=True)
    if d.empty:
        raise SystemExit(f"no stored predictions for {base}@{VERSION}")
    elo = load_predictions(ELO_BASE, VERSION)[["game_pk", "p_home"]].rename(
        columns={"p_home": "elo_p"})
    d = d.merge(elo, on="game_pk", how="left")
    d["elo_p"] = d["elo_p"].fillna(0.54)
    lam_h = np.clip((d["pred_total"] + d["pred_margin"]) / 2.0, *LAM_CLIP)
    lam_a = np.clip((d["pred_total"] - d["pred_margin"]) / 2.0, *LAM_CLIP)
    d["lam_sum"] = lam_h + lam_a
    d["resid"] = d["actual_margin"] - d["pred_margin"]

    variants: dict[str, tuple[np.ndarray, np.ndarray]] = {}  # name -> (p, margin)
    margin = d["pred_margin"].to_numpy()

    # E12a Skellam — closed form, no fitting; tie mass renormalized away.
    p_win = skellam.sf(0, lam_h, lam_a)
    p_tie = skellam.pmf(0, lam_h, lam_a)
    variants["sk"] = (np.clip(p_win / (1 - p_tie), 1e-6, 1 - 1e-6), margin)

    # E12b hetero-sigma: c from prior OOS months.
    variants["hv"] = (_monthly(d, lambda f, c: norm.cdf(
        c["pred_margin"] / np.sqrt(np.maximum(
            (np.mean(f["resid"] ** 2) / f["lam_sum"].mean()) * c["lam_sum"], 1.0))
    )), margin)

    # E11b OOS sigma.
    variants["sig"] = (_monthly(d, lambda f, c: norm.cdf(
        c["pred_margin"] / max(float(f["resid"].std()), 1.0))), margin)

    # E11a isotonic on p_home.
    def _iso(f, c):
        ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        ir.fit(f["p_home"], (f["actual_margin"] > 0).astype(float))
        return ir.predict(c["p_home"])
    variants["iso"] = (_monthly(d, _iso), margin)

    # E11c 2-feature logistic: sigma-scaled margin + logit(Elo p).
    def _log(f, c):
        sig = max(float(f["resid"].std()), 1.0)
        Xf = np.column_stack([f["pred_margin"] / sig, _logit(f["elo_p"].to_numpy())])
        Xc = np.column_stack([c["pred_margin"] / sig, _logit(c["elo_p"].to_numpy())])
        lr = LogisticRegression(C=1e6, max_iter=1000)
        lr.fit(Xf, (f["actual_margin"] > 0).astype(int))
        return lr.predict_proba(Xc)[:, 1]
    variants["log"] = (_monthly(d, _log), margin)

    # E10 lgbm+RF margin ensemble — pairs the lgbm base with the SAME-SEED rf
    # run (rf_runs+8s, rf_runs+8s_s1, ...); skipped when that run is absent.
    if base.startswith("lgbm_runs+8s"):
        rf_label = RF_BASE + base.removeprefix("lgbm_runs+8s")
        rf = load_predictions(rf_label, VERSION)[["game_pk", "pred_margin"]].rename(
            columns={"pred_margin": "rf_margin"})
        de = d.merge(rf, on="game_pk", how="inner")
        if len(de) == len(d):
            ens_margin = ((d["pred_margin"] + de["rf_margin"]) / 2.0).to_numpy()
            de2 = d.assign(pred_margin=ens_margin,
                           resid=d["actual_margin"] - ens_margin)
            p_ens = _monthly(de2, lambda f, c: norm.cdf(
                c["pred_margin"] / max(float(f["resid"].std()), 1.0)))
            variants["rfens"] = (p_ens, ens_margin)
        else:
            log.warning("rf preds cover %d/%d games; skipping rfens", len(de), len(d))

    rows = []
    for name, (p, m) in variants.items():
        label = _variant_label(base, name)
        met = _metrics(d, p, m)
        rows.append({"variant": label, **met})
        records = pd.DataFrame({
            "game_pk": d["game_pk"], "model_type": label, "model_version": VERSION,
            "data_through_date": pd.to_datetime(d["game_date"]).dt.date.astype(str),
            "pred_home_runs": (d["pred_total"] + m) / 2.0,
            "pred_away_runs": (d["pred_total"] - m) / 2.0,
            "pred_margin": m, "pred_total": d["pred_total"], "p_home": p,
        }).to_dict("records")
        with get_engine().begin() as conn:
            insert = text("""
                INSERT INTO model_predictions
                    (game_pk, model_type, model_version, data_through_date,
                     pred_home_runs, pred_away_runs, pred_margin, pred_total, p_home)
                VALUES (:game_pk, :model_type, :model_version, :data_through_date,
                        :pred_home_runs, :pred_away_runs, :pred_margin, :pred_total, :p_home)
                ON CONFLICT (game_pk, model_type, model_version) DO UPDATE SET
                    pred_home_runs = EXCLUDED.pred_home_runs,
                    pred_away_runs = EXCLUDED.pred_away_runs,
                    pred_margin = EXCLUDED.pred_margin,
                    pred_total = EXCLUDED.pred_total,
                    p_home = EXCLUDED.p_home, created_at = now()
            """)
            for i in range(0, len(records), 2000):
                conn.execute(insert, records[i:i + 2000])
        model_registry.log_model_run(
            model_type=label, target="team", run_kind="offline_recalibration",
            metrics=met, hyperparams={"base": base, "variant": name,
                                      "min_fit": MIN_FIT, "protocol": "prior-months-only"},
            feature_set_version=VERSION,
            train_window=("2023-04-01", "2026-06-30"),
            test_window=("2023-04-01", "2026-07-31"),
            notes=f"offline p_home/margin transform of stored {base} predictions; "
                  "fit on strictly-prior months only (rolling)",
        )
        log.info("%-18s acc %.4f auc %.4f brier %.4f logloss %.4f",
                 label, met["win_acc"], met["win_auc"], met["win_brier"], met["win_logloss"])

    base_met = _metrics(d, d["p_home"].to_numpy(float), margin)
    out = pd.DataFrame([{"variant": base + " (base)", **base_met}] + rows)
    print(out.round(4).to_string(index=False))
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="lgbm_runs+8s")
    args = ap.parse_args()
    run(args.base)


if __name__ == "__main__":
    main()
