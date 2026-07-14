"""Point-in-time leakage test (Phase 2 exit criterion).

Features for games on or before a cutoff date must be identical whether the
source database contains data after the cutoff or not. We build twice:
  (a) from all data, keeping rows with game_date <= CUTOFF
  (b) with every source query truncated at CUTOFF (--max-date path)
and require the frames to match to float tolerance. Statcast SQL sums are
cast to float8 so Postgres parallel-aggregation order costs at most ~1e-12
relative; a real leak (a rolling window gaining or losing a game) moves
values by ~1e-3, so 1e-9 tolerance separates the two cleanly.

team_strength_pregame and park_factors are read as-is in both runs: they are
point-in-time by construction (Elo is sequential; park factors use only prior
seasons), so post-cutoff rows in those tables cannot affect pre-cutoff games.

Usage: python scripts/test_leakage.py
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.team_features import build_features  # noqa: E402

CUTOFF = "2024-06-30"


def main() -> None:
    print(f"building from full data, filtering to games <= {CUTOFF} ...")
    full = build_features()
    full = full[full["game_date"] <= date.fromisoformat(CUTOFF)]
    full = full.sort_values("game_pk").reset_index(drop=True)

    print(f"building from data truncated at {CUTOFF} ...")
    trunc = build_features(max_date=CUTOFF)
    trunc = trunc.sort_values("game_pk").reset_index(drop=True)

    if set(full["game_pk"]) != set(trunc["game_pk"]):
        print(f"FAIL: row sets differ ({len(full)} vs {len(trunc)} games)")
        sys.exit(1)
    if list(full.columns) != list(trunc.columns):
        print("FAIL: column sets differ")
        print(set(full.columns) ^ set(trunc.columns))
        sys.exit(1)

    try:
        pd.testing.assert_frame_equal(full, trunc, check_dtype=False, rtol=1e-9, atol=1e-9)
    except AssertionError as exc:
        print("FAIL: feature values change when future data is present -- leakage!")
        print(exc)
        sys.exit(1)

    print(f"PASS: {len(full)} games x {full.shape[1]} cols identical with and "
          f"without post-{CUTOFF} data")


if __name__ == "__main__":
    main()
