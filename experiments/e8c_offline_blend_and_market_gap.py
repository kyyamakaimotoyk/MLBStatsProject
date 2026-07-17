"""E8 offline analysis: elo/lgbm blend picks, per-month market gap, agreement splits.

Read-only over stored walk-forward predictions (v20260716_083741) + closing lines.
Writes logs/e8/analysis1.md. No model retraining, no DB writes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sqlalchemy import text

from core.db import get_engine

VERSION = "v20260716_083741"
PLAUSIBLE = (0.20, 0.85)


def no_vig(ml_home, ml_away):
    def imp(ml):
        ml = float(ml)
        return 100.0 / (ml + 100.0) if ml > 0 else -ml / (-ml + 100.0)

    ph, pa = imp(ml_home), imp(ml_away)
    if ph + pa <= 0:
        return np.nan
    return ph / (ph + pa)


def load():
    eng = get_engine()
    q = text(
        """
        SELECT p.game_pk, p.model_type, p.p_home, p.pred_margin, p.pred_total,
               g.game_date, g.season, g.home_score, g.away_score,
               c.ml_home, c.ml_away, c.total AS market_total
        FROM model_predictions p
        JOIN games g ON g.game_pk = p.game_pk AND g.is_final AND g.game_type = 'R'
                    AND g.home_score IS NOT NULL AND g.home_score <> g.away_score
        LEFT JOIN LATERAL (
            SELECT ml_home, ml_away, total FROM odds_lines o
            WHERE o.game_pk = p.game_pk AND o.is_closing
              AND o.ml_home IS NOT NULL AND o.ml_away IS NOT NULL
            ORDER BY o.captured_at DESC LIMIT 1
        ) c ON TRUE
        WHERE p.model_version = :v AND p.model_type IN ('lgbm_runs+8s', 'elo+8s')
        """
    )
    with eng.connect() as cx:
        df = pd.read_sql(q, cx, params={"v": VERSION})
    df["home_won"] = df.home_score > df.away_score
    df["mkt_p"] = [
        no_vig(h, a) if pd.notna(h) and pd.notna(a) else np.nan
        for h, a in zip(df.ml_home, df.ml_away)
    ]
    df.loc[~df.mkt_p.between(*PLAUSIBLE), "mkt_p"] = np.nan
    lg = df[df.model_type == "lgbm_runs+8s"].set_index("game_pk")
    el = df[df.model_type == "elo+8s"].set_index("game_pk")
    j = lg.join(el[["p_home"]], rsuffix="_elo", how="inner")
    return j


def mcnemar(a_right, b_right):
    a_only = int((a_right & ~b_right).sum())
    b_only = int((~a_right & b_right).sum())
    n = a_only + b_only
    return (a_only, b_only, binomtest(a_only, n, 0.5).pvalue if n else 1.0)


def main():
    j = load()
    out = ["# E8 offline analysis 1", "", f"n games (lgbm+elo joined): {len(j)}", ""]

    # ---- 1. probability-blend picks ----
    out += ["## 1. Elo/LGBM p_home blend — pick accuracy by alpha (p = a*lgbm + (1-a)*elo)", ""]
    out += ["| alpha | pooled | 2023 | 2024 | 2025 | 2026 |", "|---|---|---|---|---|---|"]
    won = j.home_won.to_numpy()
    seasons = j.season.to_numpy()
    best = None
    for a in np.round(np.arange(0.0, 1.01, 0.1), 2):
        p = a * j.p_home.to_numpy() + (1 - a) * j.p_home_elo.to_numpy()
        right = (p >= 0.5) == won
        row = [f"{a:.1f}", f"{right.mean():.4f}"]
        for s in (2023, 2024, 2025, 2026):
            m = seasons == s
            row.append(f"{right[m].mean():.4f}")
        out.append("| " + " | ".join(row) + " |")
        if best is None or right.mean() > best[1]:
            best = (a, right.mean(), right)
    a, acc, right = best
    lgbm_right = (j.p_home >= 0.5).to_numpy() == won
    elo_right = (j.p_home_elo >= 0.5).to_numpy() == won
    for name, base in (("lgbm", lgbm_right), ("elo", elo_right)):
        ao, bo, p = mcnemar(pd.Series(right), pd.Series(base))
        out.append(
            f"\nbest alpha={a}: acc {acc:.4f} vs {name} {base.mean():.4f} — "
            f"McNemar discordant {ao}/{bo}, p={p:.4f}"
        )
    # margin-blend picks too (sign of blended margin makes no sense across models; skip)

    # ---- 2. per-month model vs market ----
    lined = j[j.mkt_p.notna()].copy()
    lined["month"] = pd.to_datetime(lined.game_date).dt.to_period("M").astype(str)
    lined["mkt_right"] = (lined.mkt_p >= 0.5) == lined.home_won
    lined["lgbm_right"] = (lined.p_home >= 0.5) == lined.home_won
    lined["mnum"] = pd.to_datetime(lined.game_date).dt.month
    out += ["", f"## 2. Per-month model vs market (lined games n={len(lined)})", ""]
    out += ["| month-of-season | n | lgbm acc | market acc | gap |", "|---|---|---|---|---|"]
    for m, grp in lined.groupby("mnum"):
        gap = grp.lgbm_right.mean() - grp.mkt_right.mean()
        out.append(
            f"| {m} | {len(grp)} | {grp.lgbm_right.mean():.4f} | "
            f"{grp.mkt_right.mean():.4f} | {gap:+.4f} |"
        )
    out += ["", "### by season-month", ""]
    out += ["| month | n | lgbm | market | gap |", "|---|---|---|---|---|"]
    for m, grp in lined.groupby("month"):
        gap = grp.lgbm_right.mean() - grp.mkt_right.mean()
        out.append(
            f"| {m} | {len(grp)} | {grp.lgbm_right.mean():.4f} | "
            f"{grp.mkt_right.mean():.4f} | {gap:+.4f} |"
        )

    # ---- 3. agreement split + confidence ----
    out += ["", "## 3. Agreement split (lgbm vs market favorite)", ""]
    agree = lined[(lined.p_home >= 0.5) == (lined.mkt_p >= 0.5)]
    dis = lined[(lined.p_home >= 0.5) != (lined.mkt_p >= 0.5)]
    out.append(f"- agree: n={len(agree)}, acc {agree.lgbm_right.mean():.4f}")
    out.append(
        f"- disagree: n={len(dis)}, model acc {dis.lgbm_right.mean():.4f} "
        f"(market acc {dis.mkt_right.mean():.4f})"
    )
    dis = dis.assign(conf=np.abs(dis.p_home - 0.5))
    out += ["", "disagree by model confidence |p-0.5|:", ""]
    for lo, hi in ((0.0, 0.03), (0.03, 0.06), (0.06, 0.5)):
        b = dis[(dis.conf >= lo) & (dis.conf < hi)]
        if len(b):
            out.append(f"- conf [{lo},{hi}): n={len(b)}, model acc {b.lgbm_right.mean():.4f}")
    dis = dis.assign(mconf=np.abs(dis.mkt_p - 0.5))
    out += ["", "disagree by MARKET confidence |mkt_p-0.5|:", ""]
    for lo, hi in ((0.0, 0.03), (0.03, 0.06), (0.06, 0.5)):
        b = dis[(dis.mconf >= lo) & (dis.mconf < hi)]
        if len(b):
            out.append(f"- mkt conf [{lo},{hi}): n={len(b)}, model acc {b.lgbm_right.mean():.4f}")

    # elo-agreement as a filter: when lgbm and elo agree vs not
    out += ["", "## 4. lgbm/elo agreement as signal", ""]
    both = lined[(lined.p_home >= 0.5) == (lined.p_home_elo >= 0.5)]
    split = lined[(lined.p_home >= 0.5) != (lined.p_home_elo >= 0.5)]
    out.append(f"- lgbm+elo agree: n={len(both)}, lgbm acc {both.lgbm_right.mean():.4f}, market {both.mkt_right.mean():.4f}")
    out.append(f"- lgbm/elo split: n={len(split)}, lgbm acc {split.lgbm_right.mean():.4f}, market {split.mkt_right.mean():.4f}")

    with open("logs/e8/analysis1.md", "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
