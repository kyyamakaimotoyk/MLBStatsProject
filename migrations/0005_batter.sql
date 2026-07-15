-- Phase 4: per-batter game predictions (expected stat line + probability heads).

CREATE TABLE IF NOT EXISTS batter_predictions (
    game_pk           BIGINT NOT NULL,
    player_id         INT    NOT NULL,
    model_version     TEXT   NOT NULL,
    data_through_date DATE,
    sp_id             INT,              -- probable starter the prediction conditions on
    lineup_slot       INT,
    exp_pa            REAL,
    exp_h             REAL,
    exp_tb            REAL,
    exp_hr            REAL,
    exp_bb            REAL,
    exp_k             REAL,
    p_hit             REAL,             -- P(>=1 hit)
    p_hr              REAL,             -- P(>=1 HR)
    p_tb2             REAL,             -- P(>=2 total bases)
    p_bb              REAL,             -- P(>=1 walk)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_pk, player_id, model_version)
);
CREATE INDEX IF NOT EXISTS idx_batter_predictions_player
    ON batter_predictions (player_id, model_version);
