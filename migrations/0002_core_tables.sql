-- Core ingestion tables: reference data, per-game data from the MLB Stats API
-- live feed (GUMBO), and pitch-level Statcast data.
-- See docs/PROJECT_PLAN.md §5.

CREATE TABLE IF NOT EXISTS teams (
    team_id      INT PRIMARY KEY,     -- MLBAM team id
    name         TEXT NOT NULL,
    abbrev       TEXT,
    league       TEXT,
    division     TEXT,
    venue_id     INT,
    first_season INT,
    active       BOOLEAN,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS venues (
    venue_id  INT PRIMARY KEY,
    name      TEXT NOT NULL,
    city      TEXT,
    state     TEXT,
    elevation INT,                    -- feet; relevant for park factors (Coors)
    roof_type TEXT,                   -- open / dome / retractable
    capacity  INT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS players (
    player_id        INT PRIMARY KEY, -- MLBAM id
    full_name        TEXT NOT NULL,
    birth_date       DATE,
    bats             TEXT,            -- L / R / S
    throws           TEXT,            -- L / R
    primary_position TEXT,
    mlb_debut        DATE,
    height           TEXT,
    weight           INT,
    active           BOOLEAN,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Chadwick Bureau register: MLBAM <-> FanGraphs / BBRef / Retrosheet ids
CREATE TABLE IF NOT EXISTS players_xref (
    player_id        INT PRIMARY KEY, -- key_mlbam
    key_fangraphs    INT,
    key_bbref        TEXT,
    key_retro        TEXT,
    name_first       TEXT,
    name_last        TEXT,
    mlb_played_first INT,
    mlb_played_last  INT
);

CREATE TABLE IF NOT EXISTS games (
    game_pk           BIGINT PRIMARY KEY,
    season            INT NOT NULL,
    game_type         TEXT NOT NULL,  -- R, F (WC), D (DS), L (CS), W (WS)
    game_date         DATE NOT NULL,  -- officialDate
    first_pitch_utc   TIMESTAMPTZ,
    status            TEXT,
    home_team_id      INT REFERENCES teams (team_id),
    away_team_id      INT REFERENCES teams (team_id),
    venue_id          INT,            -- no FK: international venues drift
    day_night         TEXT,
    doubleheader      TEXT,           -- N / Y / S (split)
    game_number       INT,
    scheduled_innings INT,
    innings_played    INT,
    home_score        INT,
    away_score        INT,
    weather_condition TEXT,
    temp_f            INT,
    wind_speed_mph    INT,
    wind_dir          TEXT,
    attendance        INT,
    duration_minutes  INT,
    hp_umpire_id      INT,
    hp_umpire_name    TEXT,
    is_final          BOOLEAN NOT NULL DEFAULT FALSE,
    imported_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_games_date ON games (game_date);
CREATE INDEX IF NOT EXISTS idx_games_season_type ON games (season, game_type);

-- Point-in-time probable-pitcher snapshots. Backfill writes source='backfill'
-- (the final feed's announced probables); the Phase 5 daily pipeline writes
-- source='daily' rows as probables are announced/changed.
CREATE TABLE IF NOT EXISTS probable_pitchers (
    game_pk         BIGINT NOT NULL,
    source          TEXT   NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    home_pitcher_id INT,
    away_pitcher_id INT,
    PRIMARY KEY (game_pk, source, captured_at)
);

-- Starting lineups (batting-order slots 1-9 only; subs live in game lines)
CREATE TABLE IF NOT EXISTS lineups (
    game_pk        BIGINT NOT NULL,
    player_id      INT    NOT NULL,
    team_id        INT,
    batting_order  INT,             -- 1..9
    start_position TEXT,
    PRIMARY KEY (game_pk, player_id)
);
CREATE INDEX IF NOT EXISTS idx_lineups_player ON lineups (player_id);

CREATE TABLE IF NOT EXISTS batter_game_lines (
    game_pk            BIGINT NOT NULL,
    player_id          INT    NOT NULL,
    team_id            INT,
    is_home            BOOLEAN,
    is_starter         BOOLEAN,
    batting_order_slot INT,          -- 1..9, NULL for some subs
    pa                 INT,
    ab                 INT,
    r                  INT,
    h                  INT,
    doubles            INT,
    triples            INT,
    hr                 INT,
    tb                 INT,
    rbi                INT,
    bb                 INT,
    so                 INT,
    hbp                INT,
    sb                 INT,
    cs                 INT,
    sf                 INT,
    sac                INT,
    lob                INT,
    PRIMARY KEY (game_pk, player_id)
);
CREATE INDEX IF NOT EXISTS idx_batter_lines_player ON batter_game_lines (player_id);

CREATE TABLE IF NOT EXISTS pitcher_game_lines (
    game_pk       BIGINT NOT NULL,
    player_id     INT    NOT NULL,
    team_id       INT,
    is_home       BOOLEAN,
    is_starter    BOOLEAN,
    outs          INT,               -- innings pitched as outs (5.2 IP -> 17)
    batters_faced INT,
    h             INT,
    r             INT,
    er            INT,
    bb            INT,
    so            INT,
    hr            INT,
    hbp           INT,
    pitches       INT,
    strikes       INT,
    PRIMARY KEY (game_pk, player_id)
);
CREATE INDEX IF NOT EXISTS idx_pitcher_lines_player ON pitcher_game_lines (player_id);

-- Plate-appearance-level results from the live feed play-by-play.
-- Pitch-level detail lives in statcast_pitches.
CREATE TABLE IF NOT EXISTS plays (
    game_pk         BIGINT NOT NULL,
    at_bat_index    INT    NOT NULL,
    inning          INT,
    is_top          BOOLEAN,
    batter_id       INT,
    pitcher_id      INT,
    bat_side        TEXT,
    pitch_hand      TEXT,
    event           TEXT,
    event_type      TEXT,
    description     TEXT,
    rbi             INT,
    outs_post       INT,
    home_score_post INT,
    away_score_post INT,
    PRIMARY KEY (game_pk, at_bat_index)
);
CREATE INDEX IF NOT EXISTS idx_plays_batter ON plays (batter_id);
CREATE INDEX IF NOT EXISTS idx_plays_pitcher ON plays (pitcher_id);

-- Curated Statcast columns (full raw CSVs are archived in S3 under raw/statcast/,
-- so adding a column later is a reprocess, not a re-scrape).
CREATE TABLE IF NOT EXISTS statcast_pitches (
    game_pk                          BIGINT NOT NULL,
    game_date                        DATE   NOT NULL,
    at_bat_number                    INT    NOT NULL,
    pitch_number                     INT    NOT NULL,
    batter_id                        INT,
    pitcher_id                       INT,
    stand                            TEXT,
    p_throws                         TEXT,
    inning                           INT,
    inning_topbot                    TEXT,
    balls                            INT,
    strikes                          INT,
    outs_when_up                     INT,
    pitch_type                       TEXT,
    pitch_name                       TEXT,
    release_speed                    REAL,
    release_spin_rate                REAL,
    release_extension                REAL,
    pfx_x                            REAL,
    pfx_z                            REAL,
    plate_x                          REAL,
    plate_z                          REAL,
    zone                             REAL,
    type                             TEXT,   -- B / S / X
    description                      TEXT,
    events                           TEXT,
    bb_type                          TEXT,
    launch_speed                     REAL,
    launch_angle                     REAL,
    hit_distance_sc                  REAL,
    estimated_ba_using_speedangle    REAL,
    estimated_woba_using_speedangle  REAL,
    woba_value                       REAL,
    woba_denom                       REAL,
    babip_value                      REAL,
    iso_value                        REAL,
    delta_run_exp                    REAL,
    home_team                        TEXT,
    away_team                        TEXT,
    PRIMARY KEY (game_pk, at_bat_number, pitch_number)
);
CREATE INDEX IF NOT EXISTS idx_statcast_date ON statcast_pitches (game_date);
CREATE INDEX IF NOT EXISTS idx_statcast_batter ON statcast_pitches (batter_id, game_date);
CREATE INDEX IF NOT EXISTS idx_statcast_pitcher ON statcast_pitches (pitcher_id, game_date);
