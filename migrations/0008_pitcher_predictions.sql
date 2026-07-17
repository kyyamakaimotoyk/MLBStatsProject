-- B7: starter-scoped prediction heads, aggregated from the per-PA batter
-- model: exp_k/exp_bb/exp_h = w_sp x sum over the opposing nine of
-- (expected PAs x P(outcome | vs this SP)), where w_sp is the starter's own
-- expected share of PAs (clip(SP_IP_PER_START_L10 / 9, 0.40, 0.85)).
-- Walk-forward result (2026-07-17, pooled 2023-2026, 17,374 starter-games):
-- K MAE 1.812 vs 1.888 for the SP-marginal baseline, p<.0001.
CREATE TABLE IF NOT EXISTS pitcher_predictions (
    game_pk           BIGINT      NOT NULL,
    sp_id             BIGINT      NOT NULL,
    model_version     TEXT        NOT NULL,
    data_through_date DATE        NOT NULL,
    w_sp              REAL,
    n_batters         INT,
    exp_k             REAL,
    exp_bb            REAL,
    exp_h             REAL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_pk, sp_id, model_version)
);
CREATE INDEX IF NOT EXISTS idx_pitcher_preds_date
    ON pitcher_predictions (data_through_date);
