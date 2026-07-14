-- Phase 2: derived tables and the versioned feature store.
-- See docs/PROJECT_PLAN.md §5-6.

-- Pregame team strength (Elo-style). Values for game G depend only on games
-- strictly before G, so the table is point-in-time by construction.
CREATE TABLE IF NOT EXISTS team_strength_pregame (
    game_pk     BIGINT PRIMARY KEY,
    home_rating REAL,
    away_rating REAL,
    p_home      REAL
);

-- Park factors for season S are computed from seasons strictly before S
-- (up to 3), shrunk toward 1.0. Earliest ingested season gets 1.0.
CREATE TABLE IF NOT EXISTS park_factors (
    season   INT NOT NULL,
    venue_id INT NOT NULL,
    pf_runs  REAL NOT NULL,
    n_games  INT  NOT NULL,
    PRIMARY KEY (season, venue_id)
);

-- Versioned feature store (the NBA features/feature_set_* design).
-- One row per game per snapshot version; features live in a JSONB payload so
-- feature-set evolution never needs ALTER TABLE. Meta columns are fixed.
CREATE TABLE IF NOT EXISTS feature_snapshots (
    kind              TEXT   NOT NULL,   -- 'team' | 'batter'
    version           TEXT   NOT NULL,
    game_pk           BIGINT NOT NULL,
    game_date         DATE   NOT NULL,
    season            INT    NOT NULL,
    data_through_date DATE   NOT NULL,   -- features use nothing after this date
    payload           JSONB  NOT NULL,
    PRIMARY KEY (kind, version, game_pk)
);

CREATE TABLE IF NOT EXISTS feature_set_versions (
    kind        TEXT NOT NULL,
    version     TEXT NOT NULL,
    description TEXT,
    n_rows      INT,
    n_features  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, version)
);

-- Atomic pointer to the live snapshot per kind.
CREATE TABLE IF NOT EXISTS feature_set_current (
    kind       TEXT PRIMARY KEY,
    version    TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
