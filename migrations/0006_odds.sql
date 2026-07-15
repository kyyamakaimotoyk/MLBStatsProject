-- Betting lines: EVALUATION BENCHMARK ONLY, never model features (hard rule).
-- They live in their own table and are never joined by any feature builder;
-- core/features.py cannot see them because they never enter a snapshot.
--
-- Rows are timestamped captures: the daily pipeline stores a morning line for
-- today's slate (is_closing = FALSE) and, on the following run, the last
-- available line for yesterday's games (is_closing = TRUE — ESPN retains the
-- final pregame line). Historical archive imports load closing lines directly.

CREATE TABLE IF NOT EXISTS odds_lines (
    game_pk            BIGINT NOT NULL,
    book               TEXT   NOT NULL,
    captured_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_closing         BOOLEAN NOT NULL DEFAULT FALSE,
    ml_home            INT,     -- American moneylines
    ml_away            INT,
    runline_home       REAL,    -- home spread, e.g. -1.5
    runline_home_price INT,
    runline_away_price INT,
    total              REAL,
    over_price         INT,
    under_price        INT,
    source             TEXT NOT NULL,  -- 'espn_daily' | 'archive_...'
    PRIMARY KEY (game_pk, book, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_odds_closing ON odds_lines (game_pk, is_closing);
