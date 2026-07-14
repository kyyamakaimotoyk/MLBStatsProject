"""Versioned feature-store IO (the NBA core/features_io.py design).

Each build writes a full snapshot to feature_snapshots under a version tag;
feature_set_current atomically names the live version per kind. Meta columns
(game_pk, game_date, season, data_through_date) are real columns; everything
else — features and TARGET_* — lives in a JSONB payload, so feature-set
evolution never needs a schema migration. Nothing ever reads a CSV.
"""

import json
import math

import pandas as pd
from sqlalchemy import text

from core.db import get_engine

META_COLS = ["game_pk", "game_date", "season", "data_through_date"]


def _py(v):
    """JSON-safe scalar: numpy -> python, NaN -> None."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def write_snapshot(df: pd.DataFrame, kind: str, version: str, description: str = "") -> None:
    feature_cols = [c for c in df.columns if c not in META_COLS]
    records = [
        {
            "kind": kind,
            "version": version,
            "game_pk": _py(row["game_pk"]),
            "game_date": str(row["game_date"])[:10],
            "season": _py(row["season"]),
            "data_through_date": str(row["data_through_date"])[:10],
            "payload": json.dumps({c: _py(row[c]) for c in feature_cols}),
        }
        for row in df.to_dict("records")
    ]
    with get_engine().begin() as conn:
        conn.execute(
            text("DELETE FROM feature_snapshots WHERE kind = :k AND version = :v"),
            {"k": kind, "v": version},
        )
        insert = text("""
            INSERT INTO feature_snapshots (kind, version, game_pk, game_date, season,
                                           data_through_date, payload)
            VALUES (:kind, :version, :game_pk, :game_date, :season,
                    :data_through_date, CAST(:payload AS JSONB))
        """)
        for i in range(0, len(records), 1000):
            conn.execute(insert, records[i : i + 1000])
        conn.execute(
            text("""
                INSERT INTO feature_set_versions (kind, version, description, n_rows, n_features)
                VALUES (:kind, :version, :description, :n_rows, :n_features)
                ON CONFLICT (kind, version) DO UPDATE SET
                    description = EXCLUDED.description, n_rows = EXCLUDED.n_rows,
                    n_features = EXCLUDED.n_features
            """),
            {"kind": kind, "version": version, "description": description,
             "n_rows": len(records), "n_features": len(feature_cols)},
        )


def set_current(kind: str, version: str) -> None:
    with get_engine().begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM feature_set_versions WHERE kind = :k AND version = :v"),
            {"k": kind, "v": version},
        ).first()
        if not exists:
            raise ValueError(f"unknown feature set version {kind}/{version}")
        conn.execute(
            text("""
                INSERT INTO feature_set_current (kind, version)
                VALUES (:k, :v)
                ON CONFLICT (kind) DO UPDATE SET version = EXCLUDED.version, updated_at = now()
            """),
            {"k": kind, "v": version},
        )


def current_version(kind: str) -> str | None:
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT version FROM feature_set_current WHERE kind = :k"), {"k": kind}
        ).first()
    return row[0] if row else None


def read_version(kind: str, version: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT game_pk, game_date, season, data_through_date, payload::text AS payload
                FROM feature_snapshots
                WHERE kind = :k AND version = :v
                ORDER BY game_date, game_pk
            """),
            {"k": kind, "v": version},
        ).mappings().all()
    if not rows:
        raise ValueError(f"no snapshot {kind}/{version}")
    meta = pd.DataFrame([{c: r[c] for c in META_COLS} for r in rows])
    payload = pd.DataFrame([json.loads(r["payload"]) for r in rows])
    return pd.concat([meta, payload], axis=1)


def read_current(kind: str) -> pd.DataFrame:
    version = current_version(kind)
    if version is None:
        raise ValueError(f"no current feature set for kind {kind!r}")
    return read_version(kind, version)
