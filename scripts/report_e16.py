"""E16 report: short-window form-deviation arms, tabulated per window x
season, plus star-player slices (top-5 batters by SLG/OBP/AVG, top-5
pitchers by ERA/K-BB%/WHIP, per season).

Reads stored walk-forward output only — model_predictions (team arms),
model_registry (batter per-season metrics), batter_predictions /
pitcher_predictions (star slices) — and emits the markdown report. Paired
significance for team arms is recomputed here through validation.ablation's
test functions (same math as the shipping gate); batter paired verdicts
come from the harness's --compare-base output and are quoted in the tuning
log, not recomputed here (per-PA vectors are not stored).

Usage:
    python scripts/report_e16.py --snap v2026... --out docs/e16_form_deviations_2026-07.md
    python scripts/report_e16.py --snap v2026... --best-arm l5 --wl-note partial
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402
from validation.ablation import (bootstrap_auc, load_predictions,  # noqa: E402
                                 mcnemar_accuracy, paired_mae, paired_prob)

BASELINE_TAG = "lgbm_runs+8s"
BASELINE_VERSION = "v20260716_083741"
ARMS = ("l3", "l5", "l10", "l20", "all")  # tag = lgbm_runs+dv{arm}8
SELECTION_SEASONS = (2023, 2024, 2025)
SEASONS = (2023, 2024, 2025, 2026)
BATTER_ARM_VERSIONS = ["e16_base"] + [f"e16_{a}" for a in ARMS]


def team_tag(arm: str) -> str:
    return f"lgbm_runs+dv{arm}8"


# ------------------------------------------------------------- team tables

def _season_metrics(d: pd.DataFrame) -> dict:
    win = (d["actual_margin"] > 0).to_numpy()
    pick = d["pred_margin"].to_numpy() > 0
    p = np.clip(d["p_home"].to_numpy(float), 1e-6, 1 - 1e-6)
    out = {
        "n": len(d),
        "acc": float((pick == win).mean()),
        "margin_mae": float(np.abs(d["actual_margin"] - d["pred_margin"]).mean()),
        "total_mae": float(np.abs(d["actual_total"] - d["pred_total"]).mean()),
        "logloss": float(-(win * np.log(p) + (1 - win) * np.log(1 - p)).mean()),
        "brier": float(((d["p_home"] - win) ** 2).mean()),
    }
    out["auc"] = (float(roc_auc_score(win, d["p_home"]))
                  if 0 < win.sum() < len(win) else np.nan)
    return out


def team_tables(snap: str) -> tuple[str, dict]:
    base = load_predictions(BASELINE_TAG, BASELINE_VERSION)
    base["season"] = pd.to_datetime(base["game_date"]).dt.year
    frames = {"base": base}
    for arm in ARMS:
        d = load_predictions(team_tag(arm), snap)
        if d.empty:
            continue
        d["season"] = pd.to_datetime(d["game_date"]).dt.year
        frames[arm] = d

    # per-metric season tables, rows = arms, cols = seasons + pooled
    lines = ["## Team model — per-season metrics by arm\n",
             "Baseline = " + f"`{BASELINE_TAG}` @{BASELINE_VERSION}; arms "
             f"@{snap}. Per-season numbers are diagnostic; the pooled "
             "2023-2025 ablation is the shipping bar.\n"]
    metrics = (("acc", "Pick accuracy"), ("auc", "AUC"),
               ("margin_mae", "Margin MAE"), ("total_mae", "Totals MAE"),
               ("logloss", "p_home log loss"))
    for key, title in metrics:
        lines.append(f"### {title}\n")
        header = "| arm | " + " | ".join(str(s) for s in SEASONS) + " | pooled |"
        lines += [header, "|" + "---|" * (len(SEASONS) + 2)]
        for arm, d in frames.items():
            cells = []
            for s in SEASONS:
                ds = d[d["season"] == s]
                cells.append(f"{_season_metrics(ds)[key]:.4f}" if len(ds) else "—")
            cells.append(f"{_season_metrics(d)[key]:.4f}")
            lines.append(f"| {arm} | " + " | ".join(cells) + " |")
        lines.append("")

    # paired verdicts vs baseline, selection window + pooled
    verdicts = {}
    lines.append("## Team paired verdicts vs baseline (validation.ablation math)\n")
    lines.append("| arm | window | n | acc A/B (McNemar p) | margin MAE A/B (p) | "
                 "AUC A/B (p) | log loss A/B (p) |")
    lines.append("|---|---|---|---|---|---|---|")
    for arm in ARMS:
        if arm not in frames:
            continue
        m = frames[arm].merge(base, on=["game_pk", "actual_margin", "actual_total"],
                              suffixes=("_a", "_b"))
        for label, seas in (("selection 23-25", SELECTION_SEASONS),
                            ("pooled", SEASONS)):
            d = m[m["season_a"].isin(seas)]
            if d.empty:
                continue
            win = (d["actual_margin"] > 0).to_numpy()
            acc = mcnemar_accuracy(win, d["pred_margin_a"].to_numpy() > 0,
                                   d["pred_margin_b"].to_numpy() > 0)
            mg = paired_mae(d["actual_margin"].to_numpy(float),
                            d["pred_margin_a"].to_numpy(), d["pred_margin_b"].to_numpy())
            auc = bootstrap_auc(win, d["p_home_a"].to_numpy(), d["p_home_b"].to_numpy())
            pr = paired_prob(win, d["p_home_a"].to_numpy(float),
                             d["p_home_b"].to_numpy(float))
            verdicts[(arm, label)] = {"acc": acc, "margin": mg, "auc": auc, "prob": pr}
            lines.append(
                f"| dv{arm} | {label} | {len(d)} "
                f"| {acc['acc_a']:.4f}/{acc['acc_b']:.4f} (p={acc['p_mcnemar']:.3f}) "
                f"| {mg['mae_a']:.4f}/{mg['mae_b']:.4f} (p={mg['p_paired_t']:.3f}) "
                f"| {auc['auc_a']:.4f}/{auc['auc_b']:.4f} (p={auc['p_bootstrap']:.3f}) "
                f"| {pr['logloss_a']:.4f}/{pr['logloss_b']:.4f} (p={pr['p_logloss']:.3f}) |")
    lines.append("")
    return "\n".join(lines), verdicts


# ------------------------------------------------------------ batter tables

def batter_tables() -> str:
    reg = pd.read_sql(text("""
        SELECT feature_set_version AS arm, test_start, metrics, notes
        FROM model_registry
        WHERE model_type = 'lgbm_pa' AND run_kind = 'walkforward_window'
          AND feature_set_version LIKE 'e16%%'
        ORDER BY run_id
    """), get_engine())
    if reg.empty:
        return "## Batter model\n\n(no e16_* registry rows found)\n"
    reg["season"] = pd.to_datetime(reg["test_start"]).dt.year
    # keep the latest row per (arm, season) — reruns overwrite older attempts
    reg = reg.groupby(["arm", "season"], as_index=False).last()
    lines = ["## Batter model — per-season metrics by arm\n",
             "From model_registry walkforward_window rows (seed 0). Paired "
             "flags-ON/OFF verdicts are printed by the harness "
             "(--compare-base) and quoted in the tuning-log entry.\n"]
    for key, title in (("ll_model", "Per-PA log loss"),
                       ("mae_h", "Hits MAE"), ("mae_k", "K MAE"),
                       ("mae_spk", "Starter-K MAE"),
                       ("brier_p_hit", "Brier p_hit")):
        lines.append(f"### {title}\n")
        header = "| arm | " + " | ".join(str(s) for s in SEASONS) + " |"
        lines += [header, "|" + "---|" * (len(SEASONS) + 1)]
        for arm in BATTER_ARM_VERSIONS:
            sub = reg[reg["arm"] == arm]
            if sub.empty:
                continue
            cells = []
            for s in SEASONS:
                row = sub[sub["season"] == s]
                v = row["metrics"].iloc[0].get(key) if len(row) else None
                cells.append(f"{v:.5f}" if v is not None else "—")
            lines.append(f"| {arm} | " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------- star cohorts

def _team_games(season: int) -> int:
    n = pd.read_sql(text("""
        SELECT MAX(cnt) AS g FROM (
            SELECT team_id, COUNT(*) AS cnt FROM (
                SELECT home_team_id AS team_id FROM games
                WHERE is_final AND game_type = 'R' AND season = :s
                UNION ALL
                SELECT away_team_id FROM games
                WHERE is_final AND game_type = 'R' AND season = :s
            ) t GROUP BY team_id) x
    """), get_engine(), params={"s": season})["g"].iloc[0]
    return int(n or 0)


def star_batters(season: int) -> pd.DataFrame:
    d = pd.read_sql(text("""
        SELECT b.player_id, pl.full_name, SUM(b.pa) AS pa, SUM(b.ab) AS ab,
               SUM(b.h) AS h, SUM(b.tb) AS tb, SUM(b.bb) AS bb,
               SUM(b.hbp) AS hbp, SUM(b.sf) AS sf
        FROM batter_game_lines b
        JOIN games g USING (game_pk)
        JOIN players pl ON pl.player_id = b.player_id
        WHERE g.is_final AND g.game_type = 'R' AND g.season = :s
        GROUP BY 1, 2
    """), get_engine(), params={"s": season})
    d = d[d["pa"] >= 3.1 * _team_games(season)]
    if d.empty:
        return d
    d["avg"] = d["h"] / d["ab"].replace(0, np.nan)
    d["obp"] = (d["h"] + d["bb"] + d["hbp"]) / \
        (d["ab"] + d["bb"] + d["hbp"] + d["sf"]).replace(0, np.nan)
    d["slg"] = d["tb"] / d["ab"].replace(0, np.nan)
    tags = {}
    for metric in ("slg", "obp", "avg"):
        for pid in d.nlargest(5, metric)["player_id"]:
            tags.setdefault(pid, []).append(metric.upper())
    d = d[d["player_id"].isin(tags)].copy()
    d["lists"] = d["player_id"].map(lambda p: ",".join(tags[p]))
    return d.sort_values("slg", ascending=False)


def star_pitchers(season: int) -> pd.DataFrame:
    d = pd.read_sql(text("""
        SELECT p.player_id, pl.full_name,
               SUM(p.outs) AS outs, SUM(p.er) AS er, SUM(p.so) AS so,
               SUM(p.bb) AS bb, SUM(p.h) AS h, SUM(p.batters_faced) AS bf,
               COUNT(*) FILTER (WHERE p.is_starter) AS starts
        FROM pitcher_game_lines p
        JOIN games g USING (game_pk)
        JOIN players pl ON pl.player_id = p.player_id
        WHERE g.is_final AND g.game_type = 'R' AND g.season = :s
        GROUP BY 1, 2
    """), get_engine(), params={"s": season})
    d = d[d["outs"] / 3.0 >= 1.0 * _team_games(season)]
    if d.empty:
        return d
    d["era"] = d["er"] / d["outs"].replace(0, np.nan) * 27.0
    d["whip"] = (d["bb"] + d["h"]) / (d["outs"] / 3.0).replace(0, np.nan)
    d["kbb"] = (d["so"] - d["bb"]) / d["bf"].replace(0, np.nan)
    tags = {}
    for metric, best_low in (("era", True), ("kbb", False), ("whip", True)):
        top = d.nsmallest(5, metric) if best_low else d.nlargest(5, metric)
        for pid in top["player_id"]:
            tags.setdefault(pid, []).append(metric.upper().replace("KBB", "K-BB%"))
    d = d[d["player_id"].isin(tags)].copy()
    d["lists"] = d["player_id"].map(lambda p: ",".join(tags[p]))
    return d.sort_values("era")


# ------------------------------------------------------------- star slices

def star_slice_batters(season: int, cohort: pd.DataFrame,
                       arm_versions: list[str]) -> str:
    if cohort.empty:
        return "(no qualified cohort)\n"
    preds = pd.read_sql(text("""
        SELECT bp.model_version AS arm, bp.player_id, bp.game_pk,
               bp.exp_h, bp.exp_tb, bp.p_hr,
               bg.h, bg.tb, bg.hr
        FROM batter_predictions bp
        JOIN batter_game_lines bg USING (game_pk, player_id)
        JOIN games g ON g.game_pk = bp.game_pk
        WHERE g.season = :s AND g.is_final AND g.game_type = 'R'
          AND bp.model_version = ANY(:arms)
          AND bp.player_id = ANY(:pids)
    """), get_engine(), params={"s": season, "arms": list(arm_versions),
                                "pids": [int(p) for p in cohort["player_id"]]})
    if preds.empty:
        return "(no stored arm predictions for this season)\n"
    lines = ["| player | lists | PA | AVG/OBP/SLG | arm | n | MAE(H) | "
             "MAE(TB) | Brier(HR) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in cohort.itertuples():
        first = True
        for arm in arm_versions:
            d = preds[(preds["player_id"] == r.player_id) & (preds["arm"] == arm)]
            if d.empty:
                continue
            hr1 = (d["hr"].astype(float) >= 1).astype(float)
            head = (f"| {r.full_name} | {r.lists} | {int(r.pa)} "
                    f"| {r.avg:.3f}/{r.obp:.3f}/{r.slg:.3f} "
                    if first else "| | | | ")
            first = False
            lines.append(
                head + f"| {arm} | {len(d)} "
                f"| {np.abs(d['h'] - d['exp_h']).mean():.4f} "
                f"| {np.abs(d['tb'] - d['exp_tb']).mean():.4f} "
                f"| {((d['p_hr'] - hr1) ** 2).mean():.5f} |")
    return "\n".join(lines) + "\n"


def star_slice_pitchers(season: int, cohort: pd.DataFrame,
                        arm_versions: list[str]) -> str:
    if cohort.empty:
        return "(no qualified cohort)\n"
    preds = pd.read_sql(text("""
        SELECT pp.model_version AS arm, pp.sp_id, pp.game_pk,
               pp.exp_k, pp.exp_bb, pp.exp_h AS exp_h_allowed,
               pg.so AS k, pg.bb, pg.h
        FROM pitcher_predictions pp
        JOIN pitcher_game_lines pg
          ON pg.game_pk = pp.game_pk AND pg.player_id = pp.sp_id
        JOIN games g ON g.game_pk = pp.game_pk
        WHERE g.season = :s AND g.is_final AND g.game_type = 'R'
          AND pp.model_version = ANY(:arms)
          AND pp.sp_id = ANY(:pids)
    """), get_engine(), params={"s": season, "arms": list(arm_versions),
                                "pids": [int(p) for p in cohort["player_id"]]})
    if preds.empty:
        return "(no stored arm predictions for this season)\n"
    lines = ["| pitcher | lists | IP | ERA | K-BB% | WHIP | arm | n | "
             "MAE(K) | MAE(BB) | MAE(H) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in cohort.itertuples():
        first = True
        for arm in arm_versions:
            d = preds[(preds["sp_id"] == r.player_id) & (preds["arm"] == arm)]
            if d.empty:
                continue
            head = (f"| {r.full_name} | {r.lists} | {r.outs / 3.0:.0f} "
                    f"| {r.era:.2f} | {r.kbb:.3f} | {r.whip:.2f} "
                    if first else "| | | | | | ")
            first = False
            lines.append(
                head + f"| {arm} | {len(d)} "
                f"| {np.abs(d['k'] - d['exp_k']).mean():.4f} "
                f"| {np.abs(d['bb'] - d['exp_bb']).mean():.4f} "
                f"| {np.abs(d['h'] - d['exp_h_allowed']).mean():.4f} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snap", required=True, help="E16 snapshot version")
    ap.add_argument("--out", default="docs/e16_form_deviations_2026-07.md")
    ap.add_argument("--best-arm", default=None,
                    help="best single window (e.g. l5); star tables show "
                         "base vs best vs all when given, else base vs all")
    args = ap.parse_args()

    slice_arms = ["e16_base"]
    if args.best_arm:
        slice_arms.append(f"e16_{args.best_arm}")
    slice_arms.append("e16_all")

    parts = ["# E16 — short-window form deviations (L3/L5/L10/L20)\n",
             f"Snapshot `{args.snap}`; baseline `{BASELINE_TAG}` "
             f"@{BASELINE_VERSION}. Selection window 2023-2025 (E8d hygiene; "
             "2026 confirm-only, partial through late July). Generated by "
             "scripts/report_e16.py.\n"]
    team_md, _ = team_tables(args.snap)
    parts.append(team_md)
    parts.append(batter_tables())

    parts.append("## Star-player slices\n")
    parts.append("Cohorts: top-5 per season by each of SLG/OBP/AVG (batters; "
                 "PA >= 3.1 x team games) and ERA/K-BB%/WHIP (pitchers; "
                 "IP >= 1.0 x team games), union, tagged with their lists. "
                 "W-L ranking deferred (decisions not ingested this cycle).\n")
    for season in SEASONS:
        note = " (partial)" if season == 2026 else ""
        parts.append(f"### {season}{note} — batters\n")
        parts.append(star_slice_batters(season, star_batters(season), slice_arms))
        parts.append(f"### {season}{note} — starting pitchers\n")
        parts.append(star_slice_pitchers(season, star_pitchers(season), slice_arms))

    out = Path(args.out)
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out} ({sum(len(p) for p in parts)} chars)")


if __name__ == "__main__":
    main()
