"""Model registry: every training/validation run writes one auditable row —
metrics, hyperparameters, train/test windows, and the feature_set_version it
trained on (lineage). run_kind distinguishes walk-forward windows from
summaries from production training runs. This is what makes the tuning log
verifiable (the NBA model_registry design).
"""

import json
from typing import Any

from sqlalchemy import text

from core.db import get_engine


def log_model_run(
    model_type: str,
    target: str,
    run_kind: str,
    metrics: dict[str, float],
    hyperparams: dict[str, Any],
    feature_set_version: str,
    train_window: tuple[str, str],
    test_window: tuple[str, str] | None = None,
    notes: str = "",
) -> int:
    with get_engine().begin() as conn:
        run_id = conn.execute(
            text("""
                INSERT INTO model_registry
                    (model_type, target, run_kind, feature_set_version,
                     train_start, train_end, test_start, test_end,
                     metrics, hyperparams, notes)
                VALUES (:model_type, :target, :run_kind, :fsv,
                        :train_start, :train_end, :test_start, :test_end,
                        CAST(:metrics AS JSONB), CAST(:hyperparams AS JSONB), :notes)
                RETURNING run_id
            """),
            {
                "model_type": model_type, "target": target, "run_kind": run_kind,
                "fsv": feature_set_version,
                "train_start": train_window[0], "train_end": train_window[1],
                "test_start": test_window[0] if test_window else None,
                "test_end": test_window[1] if test_window else None,
                "metrics": json.dumps(metrics), "hyperparams": json.dumps(hyperparams),
                "notes": notes,
            },
        ).scalar_one()
    return run_id
