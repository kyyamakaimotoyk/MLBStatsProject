"""E8d: first LightGBM hyperparameter sweep for the team runs model.

Selection window is pooled 2023-04 .. 2025-09 walk-forward ONLY (2026 is held
out untouched; the single winner gets a full validation.walkforward run incl.
2026 + seeds + ablation before any ship decision). No registry/DB writes.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sqlalchemy import text

import modeling.team_models as tm
from core import features_io
from core.db import get_engine
from core.features import select_features
from validation.walkforward import _metrics, _month_starts

BASE = dict(tm.LGBM_PARAMS)

CONFIGS: list[dict] = [
    {},  # incumbent: 400 trees, lr .03, leaves 15, mcs 50, subsample .8, colsample .8
    {"num_leaves": 7},
    {"num_leaves": 31},
    {"num_leaves": 63},
    {"min_child_samples": 100},
    {"min_child_samples": 200},
    {"n_estimators": 800, "learning_rate": 0.015},
    {"n_estimators": 300, "learning_rate": 0.05},
    {"colsample_bytree": 0.6},
    {"colsample_bytree": 0.5, "num_leaves": 31},
    {"reg_lambda": 5.0},
    {"num_leaves": 31, "min_child_samples": 200},
    {"n_estimators": 800, "learning_rate": 0.015, "num_leaves": 31},
    {"num_leaves": 7, "n_estimators": 800, "learning_rate": 0.03},
    {"subsample": 1.0, "colsample_bytree": 1.0},
]


def main():
    version = features_io.current_version("team")
    df = features_io.read_version("team", version)
    feats = select_features(list(df.columns), "team_runs")
    game_types = pd.read_sql(text("SELECT game_pk, game_type FROM games"), get_engine())
    df = df.merge(game_types, on="game_pk")
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    months = [m for m in _month_starts("2023-04", df["game_date"].max())
              if m < pd.Timestamp("2026-01-01")]
    print(f"snapshot {version}: {len(df)} games, {len(feats)} feats, "
          f"{len(months)} selection months (2026 held out)")

    rows = []
    for i, cfg in enumerate(CONFIGS):
        t0 = time.time()
        tm.LGBM_PARAMS.clear()
        tm.LGBM_PARAMS.update({**BASE, **cfg})
        pooled_p, pooled_t = [], []
        for month_start in months:
            month_end = month_start + pd.offsets.MonthEnd(0)
            train = df[df["game_date"] < month_start]
            test = df[(df["game_date"] >= month_start) & (df["game_date"] <= month_end)
                      & (df["game_type"] == "R")]
            if test.empty:
                continue
            model = tm.make("lgbm_runs", seed=0)
            model.fit(train, feats)
            pooled_p.append(model.predict(test, feats))
            pooled_t.append(test)
        m = _metrics(pd.concat(pooled_t), pd.concat(pooled_p).reset_index(drop=True))
        m["cfg"] = repr(cfg) if cfg else "incumbent"
        m["secs"] = round(time.time() - t0, 1)
        rows.append(m)
        print(f"[{i+1}/{len(CONFIGS)}] {m['cfg']}: acc {m['win_acc']:.4f} "
              f"auc {m.get('win_auc', float('nan')):.4f} mMAE {m['margin_mae']:.4f} "
              f"tMAE {m['total_mae']:.4f} ({m['secs']}s)", flush=True)

    tm.LGBM_PARAMS.clear()
    tm.LGBM_PARAMS.update(BASE)
    res = pd.DataFrame(rows).sort_values("win_acc", ascending=False)
    cols = ["cfg", "n_games", "win_acc", "win_auc", "margin_mae", "total_mae", "secs"]
    out = res[cols].to_string(index=False)
    print("\n=== sweep results (sorted by 2023-2025 pooled win_acc) ===\n" + out)
    with open("logs/e8/sweep_hp.md", "w", encoding="utf-8") as f:
        f.write("# E8d sweep (selection = pooled 2023-2025, 2026 held out)\n\n```\n"
                + out + "\n```\n")


if __name__ == "__main__":
    main()
