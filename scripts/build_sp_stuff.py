"""E15 (2026-07 cycle): build the in-house Stuff/Location/Pitching run-value
scores (R3-P1, docs/literature_review_2026-07.md).

For each scoring season S (2020+): train three LightGBM regressors on
delta_run_exp over ALL pitches from seasons < S, score season S's pitches,
aggregate to per-pitcher-game means in pitch_stuff_games (migration 0014).
Point-in-time is structural — a season is only ever scored by strictly-prior
models — so the feature builder can consume the table with plain as-of
windows and pass the leakage gate.

Inputs (v1, columns curated since 0002 — spin_axis et al. join in v2 once
the B8b reprocess completes):
  stuff:    release_speed, pfx_x (glove/arm-side normalized), pfx_z,
            release_spin_rate, release_extension
  location: plate_x, plate_z, balls, strikes, stand, p_throws
  pitching: both blocks
delta_run_exp is from the BATTER's perspective: lower predicted value =
better pitch. Idempotent: delete-then-insert per scoring season.

Usage:
    .venv\\Scripts\\python scripts\\build_sp_stuff.py                # 2020-2026
    .venv\\Scripts\\python scripts\\build_sp_stuff.py --start 2024 --end 2024
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.db import get_engine  # noqa: E402

log = logging.getLogger("build_sp_stuff")

STUFF_COLS = ["release_speed", "pfx_x_gs", "pfx_z", "release_spin_rate",
              "release_extension"]
LOC_COLS = ["plate_x", "plate_z", "balls", "strikes", "is_lhb", "is_lhp"]
VARIANTS = {"stuff_rv": STUFF_COLS, "loc_rv": LOC_COLS,
            "pitch_rv": STUFF_COLS + LOC_COLS}
# pitch-level n is millions and per-pitch noise is the signal being averaged
# away — deeper than the team models, still regularized
PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=63,
              min_child_samples=200, subsample=0.8, subsample_freq=1,
              colsample_bytree=0.8, reg_lambda=1.0, n_jobs=-1, verbosity=-1)


def _load(seasons: tuple[int, ...]) -> pd.DataFrame:
    df = pd.read_sql(text("""
        SELECT s.pitcher_id, s.game_pk, s.game_date, g.season,
               s.release_speed, s.pfx_x, s.pfx_z, s.release_spin_rate,
               s.release_extension, s.plate_x, s.plate_z, s.balls, s.strikes,
               s.stand, s.p_throws, s.delta_run_exp
        FROM statcast_pitches s
        JOIN games g USING (game_pk)
        WHERE g.is_final AND g.season = ANY(:seasons)
          AND s.delta_run_exp IS NOT NULL
    """), get_engine(), params={"seasons": list(seasons)})
    df["pfx_x_gs"] = df["pfx_x"] * np.where(df["p_throws"] == "L", -1.0, 1.0)
    df["is_lhb"] = (df["stand"] == "L").astype(float)
    df["is_lhp"] = (df["p_throws"] == "L").astype(float)
    return df


def run(start: int, end: int) -> None:
    engine = get_engine()
    all_seasons = pd.read_sql(text(
        "SELECT DISTINCT season FROM games WHERE is_final ORDER BY season"),
        engine)["season"].tolist()
    for season in range(start, end + 1):
        train_seasons = tuple(s for s in all_seasons if s < season)
        if not train_seasons:
            log.warning("season %d: no prior seasons to train on, skipped", season)
            continue
        t0 = time.monotonic()
        train = _load(train_seasons)
        score = _load((season,))
        if score.empty:
            log.info("season %d: no pitches to score", season)
            continue
        log.info("season %d: train %s pitches (%s), score %s",
                 season, f"{len(train):,}", f"{train_seasons[0]}-{train_seasons[-1]}",
                 f"{len(score):,}")
        preds = {}
        for name, cols in VARIANTS.items():
            model = LGBMRegressor(random_state=0, **PARAMS)
            model.fit(train[cols], train["delta_run_exp"])
            preds[name] = model.predict(score[cols])
        out = score[["pitcher_id", "game_pk", "game_date"]].copy()
        out["season"] = season
        for name in VARIANTS:
            out[name] = preds[name]
        agg = out.groupby(["pitcher_id", "game_pk", "game_date", "season"],
                          as_index=False).agg(
            n_pitches=("stuff_rv", "size"), stuff_rv=("stuff_rv", "mean"),
            loc_rv=("loc_rv", "mean"), pitch_rv=("pitch_rv", "mean"))
        records = agg.astype(object).where(agg.notna(), None).to_dict("records")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pitch_stuff_games WHERE season = :s"),
                         {"s": season})
            insert = text("""
                INSERT INTO pitch_stuff_games
                    (pitcher_id, game_pk, game_date, season, n_pitches,
                     stuff_rv, loc_rv, pitch_rv)
                VALUES (:pitcher_id, :game_pk, :game_date, :season, :n_pitches,
                        :stuff_rv, :loc_rv, :pitch_rv)
            """)
            for i in range(0, len(records), 5000):
                conn.execute(insert, records[i:i + 5000])
        log.info("season %d: %s pitcher-games written (%.1f min)",
                 season, f"{len(agg):,}", (time.monotonic() - t0) / 60)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=2020)
    ap.add_argument("--end", type=int, default=2026)
    args = ap.parse_args()
    run(args.start, args.end)


if __name__ == "__main__":
    main()
