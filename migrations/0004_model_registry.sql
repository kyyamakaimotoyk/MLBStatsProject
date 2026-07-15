-- Phase 3: model registry (auditable runs) and prediction storage.

CREATE TABLE IF NOT EXISTS model_registry (
    run_id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_type          TEXT NOT NULL,   -- lgbm_runs, xgb_direct, elo, const, ...
    target              TEXT NOT NULL,   -- 'team' for the game-level suite
    run_kind            TEXT NOT NULL,   -- walkforward_window | walkforward_summary | train
    feature_set_version TEXT,
    train_start         DATE,
    train_end           DATE,
    test_start          DATE,
    test_end            DATE,
    metrics             JSONB,
    hyperparams         JSONB,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_model_registry_type ON model_registry (model_type, run_kind);

-- One row per game per model per feature-set version. Walk-forward backfills
-- and (later) the daily pipeline both write here; data_through_date makes the
-- point-in-time guarantee explicit per prediction.
CREATE TABLE IF NOT EXISTS model_predictions (
    game_pk           BIGINT NOT NULL,
    model_type        TEXT   NOT NULL,
    model_version     TEXT   NOT NULL,   -- feature_set_version that drove the run
    data_through_date DATE,
    pred_home_runs    REAL,
    pred_away_runs    REAL,
    pred_margin       REAL,
    pred_total        REAL,
    p_home            REAL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_pk, model_type, model_version)
);
CREATE INDEX IF NOT EXISTS idx_model_predictions_type
    ON model_predictions (model_type, model_version);
