"""Walk-forward harness — the core validation methodology.

For each test month M: train on ALL games strictly before M (expanding
window, postseason included in training), test on M's regular-season games.
No in-fold leakage is possible because the feature snapshot itself is
point-in-time (scripts/test_leakage.py) and the split is strictly temporal.

Results: one model_registry row per (model, window), one summary row per
model over the pooled test set, and per-game predictions upserted into
model_predictions keyed by the feature_set_version.

Usage:
    python -m validation.walkforward                      # all model types
    python -m validation.walkforward --models lgbm_runs,elo --start-month 2023-04
"""

import argparse
import logging

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sqlalchemy import text

from core import features_io, model_registry
from core.db import get_engine
from core.features import select_features
from modeling.team_models import MODEL_TYPES, make

log = logging.getLogger("walkforward")

DEFAULT_START_MONTH = "2023-04"  # one full season + a partial in training first


def _metrics(test: pd.DataFrame, preds: pd.DataFrame) -> dict[str, float]:
    margin = test["TARGET_MARGIN"].to_numpy(float)
    total = test["TARGET_TOTAL"].to_numpy(float)
    win = margin > 0
    out = {
        "n_games": int(len(test)),
        "win_acc": float(np.mean((preds["pred_margin"].to_numpy() > 0) == win)),
        "margin_mae": float(np.mean(np.abs(margin - preds["pred_margin"]))),
        "margin_rmse": float(np.sqrt(np.mean((margin - preds["pred_margin"]) ** 2))),
        "total_mae": float(np.mean(np.abs(total - preds["pred_total"]))),
    }
    if 0 < win.sum() < len(win) and preds["p_home"].nunique() > 1:
        out["win_auc"] = float(roc_auc_score(win, preds["p_home"]))
    p = preds["p_home"].to_numpy(float)
    if np.isfinite(p).all():
        w = win.astype(float)
        p_clip = np.clip(p, 1e-6, 1 - 1e-6)
        out["win_brier"] = float(np.mean((p - w) ** 2))
        out["win_logloss"] = float(-np.mean(w * np.log(p_clip) + (1 - w) * np.log(1 - p_clip)))
    return out


def _month_starts(start_month: str, last_date) -> list[pd.Timestamp]:
    first = pd.Timestamp(start_month + "-01")
    months = []
    cur = first
    while cur <= pd.Timestamp(last_date):
        months.append(cur)
        cur = (cur + pd.offsets.MonthBegin(1))
    return months


def run(model_names: list[str], start_month: str = DEFAULT_START_MONTH,
        write_preds: bool = True, seed: int = 0, version: str | None = None,
        profile: str = "full", enable_flags: tuple[str, ...] = (),
        tag: str = "") -> pd.DataFrame:
    """tag is appended to the stored model_type so experiment variants
    (profiles, flags, alternate snapshots) coexist in the registry and
    model_predictions without colliding with the baselines."""
    version = version or features_io.current_version("team")
    df = features_io.read_version("team", version)
    # Feature list comes from the pristine snapshot columns — game_type is
    # merged in afterward purely as a test-window filter, never a feature.
    feats = select_features(list(df.columns), "team_runs",
                            profile=profile, enable_flags=enable_flags)
    game_types = pd.read_sql(text("SELECT game_pk, game_type FROM games"), get_engine())
    df = df.merge(game_types, on="game_pk")
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.sort_values(["game_date", "game_pk"]).reset_index(drop=True)
    log.info("snapshot team/%s: %d games, %d features", version, len(df), len(feats))

    summaries = []
    for name in model_names:
        label = name + tag
        pooled_preds, pooled_actual = [], []
        for month_start in _month_starts(start_month, df["game_date"].max()):
            month_end = month_start + pd.offsets.MonthEnd(0)
            train = df[df["game_date"] < month_start]
            test = df[(df["game_date"] >= month_start) & (df["game_date"] <= month_end)
                      & (df["game_type"] == "R")]
            if test.empty:
                continue
            model = make(name, seed=seed)
            model.fit(train, feats)
            preds = model.predict(test, feats)
            window_metrics = _metrics(test, preds)
            model_registry.log_model_run(
                model_type=label, target="team", run_kind="walkforward_window",
                metrics=window_metrics, hyperparams=model.hyperparams,
                feature_set_version=version,
                train_window=(str(train["game_date"].min().date()),
                              str(train["game_date"].max().date())),
                test_window=(str(month_start.date()), str(month_end.date())),
            )
            keep = preds.copy()
            keep["game_pk"] = test["game_pk"].to_numpy()
            keep["data_through_date"] = test["data_through_date"].to_numpy()
            pooled_preds.append(keep)
            pooled_actual.append(test)

        all_preds = pd.concat(pooled_preds, ignore_index=True)
        all_actual = pd.concat(pooled_actual, ignore_index=True)
        # all_actual and all_preds share positional index (same append order,
        # both ignore_index), so a season's row labels select matching preds.
        summary = _metrics(all_actual, all_preds)
        per_season = {
            str(int(season)): _metrics(grp, all_preds.loc[grp.index])
            for season, grp in all_actual.groupby("season")
        }
        model_registry.log_model_run(
            model_type=label, target="team", run_kind="walkforward_summary",
            metrics={**summary, "per_season": per_season},
            hyperparams=make(name, seed=seed).hyperparams, feature_set_version=version,
            train_window=(str(df["game_date"].min().date()), start_month + "-01"),
            test_window=(start_month + "-01", str(df["game_date"].max().date())),
            notes=f"expanding monthly walk-forward, seed={seed}, "
                  f"profile={profile}, flags={list(enable_flags)}",
        )
        summaries.append({"model": label, **summary})
        log.info("%-12s acc %.3f | auc %s | margin MAE %.3f | total MAE %.3f | n=%d",
                 label, summary["win_acc"],
                 f"{summary.get('win_auc', float('nan')):.3f}",
                 summary["margin_mae"], summary["total_mae"], summary["n_games"])

        if write_preds:
            rows = all_preds.assign(model_type=label, model_version=version)
            rows["data_through_date"] = rows["data_through_date"].astype(str)
            with get_engine().begin() as conn:
                records = rows[["game_pk", "model_type", "model_version",
                                "data_through_date", "pred_home_runs", "pred_away_runs",
                                "pred_margin", "pred_total", "p_home"]].to_dict("records")
                insert = text("""
                    INSERT INTO model_predictions
                        (game_pk, model_type, model_version, data_through_date,
                         pred_home_runs, pred_away_runs, pred_margin, pred_total, p_home)
                    VALUES (:game_pk, :model_type, :model_version, :data_through_date,
                            :pred_home_runs, :pred_away_runs, :pred_margin, :pred_total, :p_home)
                    ON CONFLICT (game_pk, model_type, model_version) DO UPDATE SET
                        data_through_date = EXCLUDED.data_through_date,
                        pred_home_runs = EXCLUDED.pred_home_runs,
                        pred_away_runs = EXCLUDED.pred_away_runs,
                        pred_margin = EXCLUDED.pred_margin,
                        pred_total = EXCLUDED.pred_total,
                        p_home = EXCLUDED.p_home,
                        created_at = now()
                """)
                for i in range(0, len(records), 2000):
                    conn.execute(insert, records[i : i + 2000])

    result = pd.DataFrame(summaries).set_index("model")
    print("\n=== walk-forward summary (regular season, "
          f"{start_month} onward, feature set {version}) ===")
    print(result.round(4).to_string())
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", default=",".join(MODEL_TYPES))
    ap.add_argument("--start-month", default=DEFAULT_START_MONTH)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-preds", action="store_true")
    ap.add_argument("--version", default=None, help="snapshot version (default: current)")
    ap.add_argument("--profile", default="full", help="feature profile (full|slim)")
    ap.add_argument("--enable-flags", default="", help="comma list of FEATURE_FLAGS to force on")
    ap.add_argument("--tag", default="", help="suffix appended to stored model_type")
    args = ap.parse_args()
    flags = tuple(f for f in args.enable_flags.split(",") if f)
    run(args.models.split(","), start_month=args.start_month,
        write_preds=not args.no_preds, seed=args.seed, version=args.version,
        profile=args.profile, enable_flags=flags, tag=args.tag)


if __name__ == "__main__":
    main()
