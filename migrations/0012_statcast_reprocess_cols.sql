-- B8b (2026-07 cycle): columns recovered by re-parsing the S3 raw Statcast
-- archive (scripts/reprocess_statcast.py) — no re-fetch, Savant retro-revises.
-- Unlocks: true per-PA base-out state (B8b RBI conditioning), score state,
-- called-strike zone bounds (own-data umpire/framing metrics with the
-- already-curated plate_x/z + description), spray + fielder identities
-- (future defense attribution; fielder_2 = catcher, the framing unlock),
-- and E15 Stuff+ inputs (spin_axis, effective_speed).
-- Deliberately skipped (locked design): 9-DOF trajectory (vx0..az,
-- release_pos), bat_speed/swing_length (2024+ only), delta_home_win_exp,
-- the deprecated empty umpire column.
ALTER TABLE statcast_pitches
    ADD COLUMN IF NOT EXISTS on_1b                 BIGINT,
    ADD COLUMN IF NOT EXISTS on_2b                 BIGINT,
    ADD COLUMN IF NOT EXISTS on_3b                 BIGINT,
    ADD COLUMN IF NOT EXISTS bat_score             INT,
    ADD COLUMN IF NOT EXISTS fld_score             INT,
    ADD COLUMN IF NOT EXISTS sz_top                REAL,
    ADD COLUMN IF NOT EXISTS sz_bot                REAL,
    ADD COLUMN IF NOT EXISTS hc_x                  REAL,
    ADD COLUMN IF NOT EXISTS hc_y                  REAL,
    ADD COLUMN IF NOT EXISTS if_fielding_alignment TEXT,
    ADD COLUMN IF NOT EXISTS of_fielding_alignment TEXT,
    ADD COLUMN IF NOT EXISTS fielder_2             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_3             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_4             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_5             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_6             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_7             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_8             BIGINT,
    ADD COLUMN IF NOT EXISTS fielder_9             BIGINT,
    ADD COLUMN IF NOT EXISTS launch_speed_angle    INT,
    ADD COLUMN IF NOT EXISTS effective_speed       REAL,
    ADD COLUMN IF NOT EXISTS spin_axis             REAL;
