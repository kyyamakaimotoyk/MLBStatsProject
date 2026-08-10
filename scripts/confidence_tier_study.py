"""Confidence-tier study — step 1 of the tiered pick surface (2026-08).

Measures, over the stored walk-forward archive, whether picks the model has
conviction about beat the pooled accuracy by enough to publish a tiered track
record (ship gate: a tier that is stable across seasons at >= .59 with usable
daily volume).

Tier signals (both already stored in model_predictions — nothing is fit or
retrained here, and nothing is written):

  conviction  |cal_p - 0.5| from the shipped E11c calibrated probability
              (lgbm_runs+log8; pass-through of raw p before MIN_FIT history)
  agreement   Elo pick (elo+8s, p_home >= .5) matches the lgbm margin pick
              (the E8c diagnostic: agree .5792 / disagree .5074)

The graded pick is always the production rule, sign(pred_margin) of the base
run — at serve the coherence clip makes p_home >= .5 equivalent, but the
stored +log8 probability is UNclipped, which is exactly what lets it disagree
with the pick and carry conviction information.

Tercile cutpoints are computed on the archive and printed so the eventual
production rule can be a FIXED |cal_p - .5| threshold chosen near a boundary
(definable ex ante), not a quantile recomputed on future data.

Usage:
    python scripts/confidence_tier_study.py
    python scripts/confidence_tier_study.py --version v20260716_083741
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validation.ablation import load_predictions  # noqa: E402

DEFAULT_VERSION = "v20260716_083741"
THRESHOLDS = (0.02, 0.04, 0.06, 0.08, 0.10, 0.12)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return center - half, center + half


def tier_row(d: pd.DataFrame, mask: pd.Series, label: str) -> dict:
    sub = d[mask]
    n, k = len(sub), int(sub["correct"].sum())
    lo, hi = wilson(k, n)
    row = {
        "tier": label, "n": n, "coverage": n / len(d),
        "acc": k / n if n else float("nan"),
        "ci95_lo": lo, "ci95_hi": hi,
        "exp_acc": float(sub["exp_acc"].mean()) if n else float("nan"),
    }
    for season, grp in sub.groupby("season"):
        row[str(season)] = f"{grp['correct'].mean():.4f} ({len(grp)})"
    row["mar_jun"] = (f"{sub.loc[sub['early'], 'correct'].mean():.4f}"
                      f" ({int(sub['early'].sum())})")
    row["jul_oct"] = (f"{sub.loc[~sub['early'], 'correct'].mean():.4f}"
                      f" ({int((~sub['early']).sum())})")
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--base", default="lgbm_runs+8s")
    ap.add_argument("--cal", default="lgbm_runs+log8")
    ap.add_argument("--elo", default="elo+8s")
    args = ap.parse_args()

    base = load_predictions(args.base, args.version)
    cal = load_predictions(args.cal, args.version)[["game_pk", "p_home"]].rename(
        columns={"p_home": "cal_p"})
    elo = load_predictions(args.elo, args.version)[["game_pk", "p_home"]].rename(
        columns={"p_home": "elo_p"})
    d = base.merge(cal, on="game_pk").merge(elo, on="game_pk")
    if len(d) != len(base):
        raise SystemExit(f"join lost rows: base {len(base)} -> merged {len(d)}")

    d["win"] = d["actual_margin"] > 0
    d["pick_home"] = d["pred_margin"] > 0
    d["correct"] = d["pick_home"] == d["win"]
    d["conf"] = (d["cal_p"] - 0.5).abs()
    d["agree"] = (d["elo_p"] >= 0.5) == d["pick_home"]
    # What the calibrator believes the PRODUCTION pick's win chance is; in the
    # flip zone (cal_p on the other side of .5 from the margin) this is < .5.
    d["exp_acc"] = np.where(d["pick_home"], d["cal_p"], 1 - d["cal_p"])
    dt = pd.to_datetime(d["game_date"])
    d["season"] = dt.dt.year
    d["early"] = dt.dt.month <= 6  # Mar-Jun, the documented market-gap window

    # --- Sanity anchors: must reproduce documented numbers before anything
    # below is trusted (pooled .5612; E8c agree .5792 / disagree .5074;
    # flip zone 14.9% — model_tuning_log.md:376-377, 726-731).
    flip = ((d["cal_p"] >= 0.5) != d["pick_home"])
    print(f"=== sanity anchors ({args.base}@{args.version}, n={len(d)}) ===")
    print(f"pooled acc      {d['correct'].mean():.4f}   (expect ~.5612)")
    print(f"agree/disagree  {d.loc[d['agree'], 'correct'].mean():.4f} / "
          f"{d.loc[~d['agree'], 'correct'].mean():.4f}   (expect ~.5792 / .5074)")
    print(f"agree coverage  {d['agree'].mean():.4f}   (expect ~.80)")
    print(f"flip-zone share {flip.mean():.4f}   (expect ~.149)")

    # --- Conviction deciles: realized vs calibrator-expected accuracy.
    d["decile"] = pd.qcut(d["conf"], 10, labels=False, duplicates="drop")
    dec = d.groupby("decile").apply(
        lambda g: pd.Series({
            "conf_lo": g["conf"].min(), "conf_hi": g["conf"].max(),
            "n": len(g), "exp_acc": g["exp_acc"].mean(),
            "acc": g["correct"].mean(),
            "ci95_lo": wilson(int(g["correct"].sum()), len(g))[0],
            "ci95_hi": wilson(int(g["correct"].sum()), len(g))[1],
        }), include_groups=False)
    print("\n=== |cal_p - .5| deciles (0 = least conviction) ===")
    print(dec.round(4).to_string())

    # --- Fixed-threshold sweep (the deployable rule shape).
    print("\n=== fixed thresholds: conf >= t ===")
    sweep = pd.DataFrame([tier_row(d, d["conf"] >= t, f"conf>={t:.2f}")
                          for t in THRESHOLDS])
    print(sweep.round(4).to_string(index=False))

    # --- Tercile cutpoints, for choosing a fixed production threshold.
    q1, q2 = d["conf"].quantile([1 / 3, 2 / 3])
    print(f"\ntercile cutpoints: conf {q1:.4f} / {q2:.4f}")

    # --- Candidate tiers (pre-declared): per-season + month-window stability.
    top = d["conf"] >= q2
    candidates = [
        (pd.Series(True, index=d.index), "all games"),
        (d["agree"], "agree"),
        (top, "conf top-tercile"),
        (d["agree"] & top, "agree & top-tercile"),
        (d["agree"] & (d["conf"] >= 0.06), "agree & conf>=0.06"),
        (d["agree"] & (d["conf"] >= 0.08), "agree & conf>=0.08"),
        (d["agree"] & (d["conf"] >= 0.10), "agree & conf>=0.10"),
        # Pick-side probability rule — the deployable formulation: a game is
        # published in the top tier when the calibrated probability OF THE
        # PICK clears the bar. Unlike |cal_p-.5| it can never rank a flip-zone
        # game (calibrator against the pick) as high conviction, and it stays
        # honest by construction as long as exp_acc tracks realized acc.
        (d["exp_acc"] >= 0.56, "pick-prob>=0.56"),
        (d["exp_acc"] >= 0.58, "pick-prob>=0.58"),
        (d["exp_acc"] >= 0.60, "pick-prob>=0.60"),
    ]
    cand = pd.DataFrame([tier_row(d, m, label) for m, label in candidates])
    print("\n=== candidate tiers ===")
    print(cand.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
