"""Point-in-time leakage test for the per-PA batter frame (E16 gate).

The per-PA frame is not snapshotted (see features/batter_features.py), so
scripts/test_leakage.py never covered it directly — this is its mirror:
  (a) build from all data, keep PAs with game_date <= CUTOFF
  (b) build with every source query truncated at CUTOFF (max_date path)
and require identity to float tolerance on ALL feature columns (the E16
deviation columns and every pre-existing per-PA feature alike). The same
tolerance argument as the team gate applies: Postgres float8 aggregation
order costs ~1e-12 relative; a real leak (a window gaining or losing a
game, or a prior seeing future data) moves values by ~1e-3.

Usage: python scripts/test_leakage_batter.py
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features import batter_features as bf  # noqa: E402

CUTOFF = "2024-06-30"


def main() -> None:
    print(f"building per-PA frame from full data, filtering to <= {CUTOFF} ...")
    full = bf.build()["pa"]
    full = full[full["game_date"] <= pd.Timestamp(date.fromisoformat(CUTOFF))]
    full = full.sort_values(["game_pk", "at_bat_index"]).reset_index(drop=True)

    print(f"building per-PA frame from data truncated at {CUTOFF} ...")
    trunc = bf.build(max_date=CUTOFF)["pa"]
    trunc = trunc.sort_values(["game_pk", "at_bat_index"]).reset_index(drop=True)

    if len(full) != len(trunc) or not (
            full[["game_pk", "at_bat_index"]].to_numpy()
            == trunc[["game_pk", "at_bat_index"]].to_numpy()).all():
        print(f"FAIL: PA row sets differ ({len(full)} vs {len(trunc)} PAs)")
        sys.exit(1)
    if list(full.columns) != list(trunc.columns):
        print("FAIL: column sets differ")
        print(set(full.columns) ^ set(trunc.columns))
        sys.exit(1)

    try:
        pd.testing.assert_frame_equal(full, trunc, check_dtype=False,
                                      rtol=1e-9, atol=1e-9)
    except AssertionError as exc:
        print("FAIL: per-PA features change when future data is present -- leakage!")
        print(exc)
        sys.exit(1)

    print(f"PASS: {len(full)} PAs x {full.shape[1]} cols identical with and "
          f"without post-{CUTOFF} data")


if __name__ == "__main__":
    main()
