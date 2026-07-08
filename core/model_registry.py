"""Model registry (Phase 3).

Ports the NBA model_registry design: every training/validation run writes one
row with metrics (accuracy/AUC for win, MAE/RMSE for margin and totals, log
loss for the batter per-PA model), hyperparameters, train/test windows, the
feature_set_version it trained on (lineage), and a run_kind
('train' | 'validate' | 'walkforward'). This is what makes results auditable
and the tuning log verifiable.

Table created by a Phase 3 migration; stable signatures below.
"""

from typing import Any


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
    """Insert one registry row; returns its id."""
    raise NotImplementedError("Phase 3")
