-- Serving rollups: pre-resolved grading for the public track record.
--
-- Why these exist. model_predictions holds ~81 rows per game (12 model
-- versions across ~690 data_through_dates) and batter_predictions ~5.5 per
-- batter-game, because both tables are append-only — which is correct for
-- auditing and point-in-time work. But every public endpoint was resolving
-- "which row is current" with a LATERAL ... ORDER BY created_at DESC LIMIT 1
-- *per row, per request*, over unbounded history. /api/public/summary pulled
-- 162k rows into pandas to return 257 bytes and took 30 seconds doing it.
--
-- These tables resolve that once, on write, in the pipeline that already runs
-- whenever the inputs change (orchestration/grades.py). The serving path then
-- becomes an indexed range scan over ~9k and ~700 rows.
--
-- These are DERIVED tables: safe to TRUNCATE and rebuild from the base tables
-- at any time (`python -m orchestration.grades --full`). Nothing here is a
-- source of truth, and nothing here is a model feature — this is postgame
-- grading for display, so the point-in-time rule does not apply. Keep it that
-- way: no feature builder may read these.

-- One row per graded game: the published prediction, the result, and the
-- market's pregame view, all pre-resolved.
CREATE TABLE IF NOT EXISTS pred_grades (
    game_pk       BIGINT PRIMARY KEY REFERENCES games (game_pk),
    game_date     DATE    NOT NULL,
    -- which model_predictions row won the resolution, kept for provenance so
    -- a surprising number can be traced back without re-deriving the order
    model_type    TEXT    NOT NULL,
    model_version TEXT    NOT NULL,
    p_home        REAL,
    pred_margin   REAL,
    pred_total    REAL,
    margin        INT,     -- actual: home_score - away_score
    total         INT,     -- actual: home_score + away_score
    home_won      BOOLEAN,
    -- graded on the PUBLISHED pick (p_home vs .5), not the margin sign: the
    -- two can disagree on pre-clip calibrated rows, and the pick is what the
    -- site showed
    correct       BOOLEAN,
    margin_err    REAL,
    total_err     REAL,
    -- no-vig closing win probability and closing total, with the same
    -- plausibility guard the API applied (implausible close falls back to
    -- open; neither plausible ships NULL). Benchmarks only — hard rule.
    market_p_home REAL,
    market_total  REAL,
    refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pred_grades_date ON pred_grades (game_date);

-- One row per day of hitter calls. The public endpoint only ever served this
-- shape; it was computing a DISTINCT ON over a 387k-row join plus a window
-- function on every request to produce ~700 rows.
CREATE TABLE IF NOT EXISTS batter_grades_daily (
    game_date          DATE PRIMARY KEY,
    n                  INT NOT NULL,  -- gradeable calls that day
    model_correct      INT NOT NULL,
    -- the honest benchmark: how the lazy always-say-yes rule did on the same
    -- batter-games. Most starters do get a hit, so coin-flip is the wrong
    -- opponent.
    always_yes_correct INT NOT NULL,
    -- homers by ALL graded starters that day — the base rate a top-5 ranking
    -- claim has to beat
    hr_base_hits       INT NOT NULL,
    hr_watch_n         INT NOT NULL,
    hr_watch_hits      INT NOT NULL,
    refreshed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
