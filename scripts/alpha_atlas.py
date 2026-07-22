"""Alpha atlas (W0.4, 2026-07 cycle): per-stat reliability constants from our
own data — the shared input for E9b blend weights, B10 per-class ballasts,
and E13 priors.

Method (Carleton / Dolinar-Pemstein variance-ratio form, R-P1 in
docs/literature_review_2026-07.md): for units i (batter-season /
pitcher-season / team-season) with n_i trials and observed rate p_i,
reliability follows alpha(n) = n / (n + k) with k = pbar(1-pbar) / tau^2,
where tau^2 = var(p_i) - pbar(1-pbar) * mean(1/n_i) is the between-unit
talent variance after subtracting binomial sampling noise. Rates are centered
per season before the variance step so era drift does not inflate tau^2.
Constants describe the population that passes the min-n filter (regulars /
starters / teams) — the population the model's rate features describe.

Usage:
    .venv\\Scripts\\python scripts\\alpha_atlas.py            # full atlas + doc
    .venv\\Scripts\\python scripts\\alpha_atlas.py --no-doc   # print only
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402

log = logging.getLogger("alpha_atlas")

SEASONS = (2021, 2022, 2023, 2024, 2025)  # full post-COVID seasons only
MIN_N = {"batter": 300, "pitcher": 300, "team": 3000}
CLASS_COLS = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "HIT"]
DOC = Path(__file__).resolve().parents[1] / "docs" / "alpha_atlas_2026-07.md"

_PA_SQL = text("""
    SELECT g.season,
           CASE WHEN NOT p.is_top THEN g.home_team_id ELSE g.away_team_id END AS bat_team,
           CASE WHEN NOT p.is_top THEN g.away_team_id ELSE g.home_team_id END AS fld_team,
           p.batter_id, p.pitcher_id, p.event_type
    FROM plays p
    JOIN games g USING (game_pk)
    WHERE g.is_final AND g.game_type = 'R' AND g.season = ANY(:seasons)
""")

EVENT_MAP = {
    "strikeout": "K", "strikeout_double_play": "K", "strikeout_triple_play": "K",
    "walk": "BB", "intent_walk": "BB", "hit_by_pitch": "HBP",
    "single": "1B", "double": "2B", "triple": "3B", "home_run": "HR",
    "field_out": "OUT", "force_out": "OUT", "grounded_into_double_play": "OUT",
    "double_play": "OUT", "triple_play": "OUT", "sac_fly": "OUT", "sac_bunt": "OUT",
    "sac_fly_double_play": "OUT", "sac_bunt_double_play": "OUT",
    "field_error": "OUT", "fielders_choice": "OUT", "fielders_choice_out": "OUT",
    "batter_interference": "OUT", "other_out": "OUT",
}


def _fit(unit_rates: pd.DataFrame, stat: str, min_n: int) -> dict | None:
    """unit_rates: columns [season, n, rate]. Returns the fitted constants."""
    d = unit_rates[unit_rates["n"] >= min_n]
    if len(d) < 30:
        return None
    pbar = float(np.average(d["rate"], weights=d["n"]))
    centered = d["rate"] - d.groupby("season")["rate"].transform("mean")
    sampling = pbar * (1 - pbar) * float(np.mean(1.0 / d["n"]))
    tau2 = float(centered.var(ddof=1)) - sampling
    if tau2 <= 0:
        return {"stat": stat, "pbar": pbar, "tau2": tau2, "k": float("inf"),
                "n_units": len(d), "note": "no detectable talent spread"}
    k = pbar * (1 - pbar) / tau2
    return {"stat": stat, "pbar": pbar, "tau2": tau2, "k": k,
            "n_units": len(d), "note": ""}


def _level(pa: pd.DataFrame, unit_col: str, min_n: int) -> pd.DataFrame:
    grp = pa.groupby([unit_col, "season"])
    counts = grp.size().rename("n")
    rows = []
    for stat in CLASS_COLS:
        flag = (pa["outcome"] == stat) if stat != "HIT" else pa["outcome"].isin(
            ["1B", "2B", "3B", "HR"])
        rate = flag.groupby([pa[unit_col], pa["season"]]).mean().rename("rate")
        d = pd.concat([counts, rate], axis=1).reset_index()
        fit = _fit(d, stat, min_n)
        if fit:
            rows.append(fit)
    return pd.DataFrame(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-doc", action="store_true")
    args = ap.parse_args()

    pa = pd.read_sql(_PA_SQL, get_engine(), params={"seasons": list(SEASONS)})
    pa["outcome"] = pa["event_type"].map(EVENT_MAP)
    pa = pa.dropna(subset=["outcome"])
    log.info("loaded %d regular-season PAs, seasons %s", len(pa), SEASONS)

    tables = {}
    for level, unit_col in (("batter", "batter_id"), ("pitcher", "pitcher_id"),
                            ("team_offense", "bat_team"), ("team_defense", "fld_team")):
        min_n = MIN_N["team" if level.startswith("team") else level]
        tables[level] = _level(pa, unit_col, min_n).assign(level=level)
        log.info("%s done (%d stats)", level, len(tables[level]))

    atlas = pd.concat(tables.values(), ignore_index=True)
    atlas["k"] = atlas["k"].round(0)
    atlas["alpha_at_600"] = (600 / (600 + atlas["k"])).round(3)
    cols = ["level", "stat", "pbar", "tau2", "k", "alpha_at_600", "n_units", "note"]
    out = atlas[cols].round({"pbar": 4, "tau2": 8})
    print(out.to_string(index=False))

    if not args.no_doc:
        lines = [
            "# Alpha atlas — 2026-07 cycle (W0.4)", "",
            "Per-stat reliability constants alpha(n) = n/(n+k) fitted from our own DB",
            f"(regular season {SEASONS[0]}–{SEASONS[-1]}, variance-ratio method per",
            "R-P1 Carleton in docs/literature_review_2026-07.md; per-season centering;",
            f"min n: batter/pitcher {MIN_N['batter']}, team {MIN_N['team']}).",
            "k is in PA (batter/team-offense), BF (pitcher/team-defense).",
            "Blend weight for E9b / B10: w = n/(n+k) on the current-season rate.", "",
            "```", out.to_string(index=False), "```", "",
            "Generated by scripts/alpha_atlas.py — rerun after major data additions.",
        ]
        DOC.write_text("\n".join(lines), encoding="utf-8")
        log.info("wrote %s", DOC)


if __name__ == "__main__":
    main()
