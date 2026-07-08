"""Versioned feature-store IO (Phase 2).

Ports the NBA core/features_io.py design: each feature build writes a full
snapshot to features_team / features_batter under a UTC version tag recorded
in feature_set_versions, and an atomic pointer row in feature_set_current
names the live version. Consumers read through read_current(); nothing ever
reads a CSV.

Tables are created by migrations in Phase 2; these are the stable signatures
the rest of the codebase programs against.
"""

import pandas as pd

from core.db import get_engine


def write_snapshot(df: pd.DataFrame, kind: str, version: str, description: str = "") -> None:
    """Write one feature snapshot (kind: 'team' | 'batter') under a version tag."""
    raise NotImplementedError("Phase 2")


def set_current(version: str) -> None:
    """Atomically point feature_set_current at an existing version."""
    raise NotImplementedError("Phase 2")


def read_current(kind: str) -> pd.DataFrame:
    """Read the live feature snapshot for 'team' or 'batter'."""
    raise NotImplementedError("Phase 2")


def read_version(kind: str, version: str) -> pd.DataFrame:
    """Read a specific historical snapshot (for reproducing experiments)."""
    raise NotImplementedError("Phase 2")
