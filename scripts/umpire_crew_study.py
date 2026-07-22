"""Umpire crew study (Wave 4 prep, 2026-07 cycle): three analyses over
retrosheet_gamelogs (1998-2025) + game_officials that gate the umpire
serve-path design (docs/literature_review_2026-07.md, R3-P2/P5).

  1. UMP-ROT-HIST — learn the crew-rotation direction empirically: given an
     umpire's position in his previous game (within 3 days), how often is he
     behind the plate today? Yields the rotation rule, its top-1 accuracy,
     and pregame-predictability coverage by era.
  2. UMP-KBB-STAB — per-HP-umpire K/BB factors vs league-season baseline:
     year-over-year stability by era (is the factor a real, persistent
     trait?) and the implied shrinkage ballast.
  3. UMP-BRIDGE — date-level agreement between Retrosheet HP names and the
     MLB API's game_officials on the 2019+ overlap.

The information used here was obtained free of charge from and is copyrighted
by Retrosheet. Interested parties may contact Retrosheet at
"www.retrosheet.org".

Usage:
    .venv\\Scripts\\python scripts\\umpire_crew_study.py
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402

log = logging.getLogger("umpire_crew_study")
DOC = Path(__file__).resolve().parents[1] / "docs" / "umpire_crew_study_2026-07.md"
POSITIONS = ("hp", "1b", "2b", "3b")


def _load() -> pd.DataFrame:
    df = pd.read_sql(text("""
        SELECT game_date, game_number, away_team, home_team, day_night,
               away_ab, away_bb, away_k, home_ab, home_bb, home_k,
               ump_hp_rid, ump_hp_name, ump_1b_rid, ump_2b_rid, ump_3b_rid
        FROM retrosheet_gamelogs
        ORDER BY game_date, home_team, game_number
    """), get_engine())
    df["game_date"] = pd.to_datetime(df["game_date"])
    df["season"] = df["game_date"].dt.year
    return df


def rotation_study(df: pd.DataFrame, lines: list) -> None:
    """Long frame: one row per (game, umpire, position); per umpire, the
    previous assignment within 3 days predicts today's position."""
    parts = []
    for pos in POSITIONS:
        p = df[["game_date", "season", f"ump_{pos}_rid"]].rename(
            columns={f"ump_{pos}_rid": "rid"})
        p["pos"] = pos
        parts.append(p.dropna(subset=["rid"]))
    lng = pd.concat(parts, ignore_index=True).sort_values(["rid", "game_date"])
    # doubleheaders: an umpire can appear twice on a date; keep one row per
    # (rid, date) with the LAST position that date (rotation advances daily)
    lng = lng.groupby(["rid", "game_date"], as_index=False).last()
    lng["prev_date"] = lng.groupby("rid")["game_date"].shift(1)
    lng["prev_pos"] = lng.groupby("rid")["pos"].shift(1)
    lng["gap"] = (lng["game_date"] - lng["prev_date"]).dt.days
    cont = lng[lng["gap"].between(1, 3)]

    lines.append("## 1. Crew-rotation direction (UMP-ROT-HIST)\n")
    trans = pd.crosstab(cont["prev_pos"], cont["pos"], normalize="index")
    lines.append("Position transition matrix, previous game (rows) -> today "
                 "(cols), gaps of 1-3 days, 1998-2025:\n")
    lines.append("```\n" + trans.round(3).to_string() + "\n```\n")

    # pregame HP predictability: for each game's HP ump, was his previous
    # assignment within 3 days, and does the learned rule call him?
    hp = lng[lng["pos"] == "hp"]
    rule_prev = trans["hp"].idxmax()  # the position that most often precedes HP
    lines.append(f"Learned rule: today's HP umpire was at **{rule_prev.upper()}** "
                 f"in his previous game (P={trans.loc[rule_prev, 'hp']:.3f}).\n")
    by_era = []
    for era, grp in hp.groupby(hp["season"] // 4 * 4):
        n = len(grp)
        covered = grp["gap"].between(1, 3)
        hit = covered & (grp["prev_pos"] == rule_prev)
        by_era.append({"era": f"{era}-{era+3}", "games": n,
                       "coverage": covered.mean(), "rule_hit_given_covered":
                           (hit.sum() / max(covered.sum(), 1))})
    era_df = pd.DataFrame(by_era)
    lines.append("HP predictability by era (coverage = HP ump seen within 3 "
                 "days; hit = the rule names him):\n")
    lines.append("```\n" + era_df.round(3).to_string(index=False) + "\n```\n")
    # invert: of all games, how often does applying the rule to YESTERDAY'S
    # crew identify today's HP ump? (the serve-time question)
    inv = lng[lng["pos"] == rule_prev].copy()
    inv["pred_next_hp_date_ok"] = True  # bookkeeping only
    lines.append(f"Serve-time reading: rotation-predictable share of games = "
                 f"coverage x hit rate above; the remainder (series openers, "
                 f"crew changes, off-day breaks > 3 days) needs the live "
                 f"probe capture instead.\n")


def kbb_stability(df: pd.DataFrame, lines: list) -> None:
    d = df.dropna(subset=["ump_hp_rid"]).copy()
    d["pa"] = (d[["away_ab", "home_ab", "away_bb", "home_bb"]].sum(axis=1))
    d["k"] = d["away_k"] + d["home_k"]
    d["bb"] = d["away_bb"] + d["home_bb"]
    d = d.dropna(subset=["pa", "k", "bb"])
    lg = d.groupby("season")[["k", "bb", "pa"]].sum()
    lg["k_rate"], lg["bb_rate"] = lg["k"] / lg["pa"], lg["bb"] / lg["pa"]
    us = d.groupby(["ump_hp_rid", "season"]).agg(
        k=("k", "sum"), bb=("bb", "sum"), pa=("pa", "sum"), n=("k", "size"))
    us = us[us["n"] >= 20].reset_index().merge(
        lg[["k_rate", "bb_rate"]], on="season")
    us["k_factor"] = (us["k"] / us["pa"]) / us["k_rate"]
    us["bb_factor"] = (us["bb"] / us["pa"]) / us["bb_rate"]

    lines.append("## 2. Per-HP-umpire K/BB factor stability (UMP-KBB-STAB)\n")
    rows = []
    for stat in ("k_factor", "bb_factor"):
        piv = us.pivot_table(index="ump_hp_rid", columns="season", values=stat)
        for era0 in range(1998, 2025, 9):
            cors = []
            for s in range(era0, min(era0 + 8, 2025)):
                if s in piv.columns and s + 1 in piv.columns:
                    pair = piv[[s, s + 1]].dropna()
                    if len(pair) >= 15:
                        cors.append(pair.corr().iloc[0, 1])
            if cors:
                rows.append({"stat": stat, "era": f"{era0}-{min(era0+8, 2025)}",
                             "mean_yoy_r": float(np.mean(cors)),
                             "n_season_pairs": len(cors)})
    sd = us.groupby(us["season"] // 9 * 9)[["k_factor", "bb_factor"]].std()
    lines.append("Year-over-year correlation of per-ump factors (>=20 games "
                 "both seasons):\n")
    lines.append("```\n" + pd.DataFrame(rows).round(3).to_string(index=False) + "\n```\n")
    lines.append("Between-ump factor spread (SD) by era block:\n")
    lines.append("```\n" + sd.round(4).to_string() + "\n```\n")


def bridge_audit(df: pd.DataFrame, lines: list) -> None:
    api = pd.read_sql(text("""
        SELECT g.game_date, o.official_name
        FROM game_officials o JOIN games g USING (game_pk)
        WHERE o.official_type = 'Home Plate' AND g.game_type = 'R'
    """), get_engine())
    api["game_date"] = pd.to_datetime(api["game_date"])
    rs = df[df["season"] >= 2019][["game_date", "ump_hp_name"]].dropna()
    a = api.groupby("game_date")["official_name"].apply(
        lambda s: frozenset(x.strip().lower() for x in s))
    r = rs.groupby("game_date")["ump_hp_name"].apply(
        lambda s: frozenset(x.strip().lower() for x in s))
    both = pd.concat([a.rename("api"), r.rename("rs")], axis=1).dropna()
    both["overlap"] = [len(x & y) / max(len(x | y), 1)
                       for x, y in zip(both["api"], both["rs"])]
    lines.append("## 3. Retrosheet vs MLB API bridge audit (UMP-BRIDGE)\n")
    lines.append(f"Dates compared (2019+ regular season): {len(both)}; mean "
                 f"per-date HP-name Jaccard overlap {both['overlap'].mean():.4f}; "
                 f"dates with perfect agreement "
                 f"{(both['overlap'] == 1.0).mean():.4f}.\n")
    lines.append("(Name-level audit; the Chadwick key_retro->key_mlbam join "
                 "replaces names before any feature ships.)\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = _load()
    log.info("loaded %d retrosheet games %d-%d", len(df),
             df["season"].min(), df["season"].max())
    lines = ["# Umpire crew study — 2026-07 cycle (Wave 4 prep)\n",
             "Generated by scripts/umpire_crew_study.py from retrosheet_gamelogs "
             "(1998-2025) and game_officials (2019+).\n",
             "Retrosheet notice: The information used here was obtained free of "
             "charge from and is copyrighted by Retrosheet. Interested parties "
             "may contact Retrosheet at \"www.retrosheet.org\".\n"]
    rotation_study(df, lines)
    kbb_stability(df, lines)
    bridge_audit(df, lines)
    DOC.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    log.info("wrote %s", DOC)


if __name__ == "__main__":
    main()
