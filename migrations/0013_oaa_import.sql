-- B9b (2026-07 cycle): Savant Outs Above Average imports (player-level files
-- only — the team-level export lacks fielding_runs_prevented; teams are
-- aggregated at feature-build time). month_bucket 0 = full-season file;
-- 4..9 = Savant's per-month slices (4 = combined March/April).
--
-- HARD LEAKAGE RULE (enforced in the feature builder, not here): features
-- for games in season S, month M may use full seasons <= S-1 plus the SUM of
-- current-season buckets strictly before M. Never join an in-progress
-- season's cumulative file — Savant files are point-in-time-unreconstructable
-- below month grain. Season comes from the request params: the CSV's own
-- year column is empty (verified 2026-07-22). Infield OAA exists 2020+ only.
CREATE TABLE IF NOT EXISTS oaa_import (
    season               INT    NOT NULL,
    month_bucket         INT    NOT NULL DEFAULT 0,  -- 0 = full season; 4..9
    player_id            BIGINT NOT NULL,
    position             TEXT   NOT NULL DEFAULT '',
    player_name          TEXT,
    team                 TEXT,
    attempts             INT,
    oaa                  REAL,
    runs_prevented       REAL,
    actual_success_rate  REAL,
    est_success_rate     REAL,
    source_file          TEXT,
    imported_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (season, month_bucket, player_id, position)
);
CREATE INDEX IF NOT EXISTS idx_oaa_player ON oaa_import (player_id, season);
