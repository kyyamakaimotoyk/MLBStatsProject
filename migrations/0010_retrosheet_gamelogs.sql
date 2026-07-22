-- W0.3 (2026-07 cycle): Retrosheet game logs — the historical backbone for
-- the umpire serve path (Wave 4): full four-umpire crews per game back
-- decades for learning the crew-rotation direction and measuring
-- rotation-prediction error, plus per-game team K/BB totals so per-HP-umpire
-- factors and their era stability can be computed without any other source.
-- Standalone table (no game_pk): Retrosheet has no MLB gamePk; the 2019+
-- overlap joins to games/game_officials via (date, teams, game_number).
--
-- The information used here was obtained free of charge from and is
-- copyrighted by Retrosheet. Interested parties may contact Retrosheet at
-- "www.retrosheet.org". (Required attribution — must appear prominently if
-- this data ever surfaces on the public site.)
CREATE TABLE IF NOT EXISTS retrosheet_gamelogs (
    game_date   DATE NOT NULL,
    game_number INT  NOT NULL,          -- 0 single game, 1/2 doubleheader
    away_team   TEXT NOT NULL,          -- Retrosheet team codes
    home_team   TEXT NOT NULL,
    away_score  INT,
    home_score  INT,
    day_night   TEXT,
    park_id     TEXT,
    away_ab INT, away_h INT, away_bb INT, away_k INT,
    home_ab INT, home_h INT, home_bb INT, home_k INT,
    ump_hp_rid TEXT, ump_hp_name TEXT,
    ump_1b_rid TEXT, ump_1b_name TEXT,
    ump_2b_rid TEXT, ump_2b_name TEXT,
    ump_3b_rid TEXT, ump_3b_name TEXT,
    ump_lf_rid TEXT, ump_lf_name TEXT,
    ump_rf_rid TEXT, ump_rf_name TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_date, home_team, game_number)
);
CREATE INDEX IF NOT EXISTS idx_retrosheet_hp_ump
    ON retrosheet_gamelogs (ump_hp_rid, game_date);
