-- E15 (2026-07 cycle): per-pitcher-game aggregates of per-pitch run-value
-- model scores (the in-house Stuff+/Location+/Pitching+ analog, R3-P1 in
-- docs/literature_review_2026-07.md). Each season S is scored by models
-- trained strictly on seasons < S (point-in-time by construction; the
-- builder is scripts/build_sp_stuff.py). Values are mean PREDICTED
-- delta_run_exp per pitch — lower = better for the pitcher.
-- stuff_rv: physical characteristics only (velo, movement, spin, extension);
-- loc_rv: location conditioned on count/handedness; pitch_rv: both blocks.
CREATE TABLE IF NOT EXISTS pitch_stuff_games (
    pitcher_id  BIGINT NOT NULL,
    game_pk     BIGINT NOT NULL,
    game_date   DATE   NOT NULL,
    season      INT    NOT NULL,
    n_pitches   INT    NOT NULL,
    stuff_rv    REAL,
    loc_rv      REAL,
    pitch_rv    REAL,
    built_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (pitcher_id, game_pk)
);
CREATE INDEX IF NOT EXISTS idx_pitch_stuff_date
    ON pitch_stuff_games (pitcher_id, game_date);
