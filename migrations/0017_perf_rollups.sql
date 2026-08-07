-- Serving rollups for /api/performance (the model-comparison page).
--
-- These are a DIFFERENT grain from pred_grades and cannot reuse it.
-- pred_grades resolves each game to the one published prediction, which is
-- exactly what the public track record wants and exactly what this page must
-- not do: /api/performance exists to compare model variants against each
-- other, so it groups by (model_type, model_version). Collapsing to the
-- published row would erase the comparison. Hence a per-variant, per-day
-- grain: 55k rows for the team side, 3.8k for the batter side.
--
-- Sums and counts, never averages. An average is not additive across days --
-- summing daily means would silently weight a 4-game Monday like a 15-game
-- Saturday -- so each metric stores its numerator and its own denominator,
-- and the endpoint divides at read time. The denominators are per-metric
-- because avg() in the original queries skips NULLs independently per column;
-- there are none today, but a future model version writing one would
-- otherwise make the reconstructed average quietly wrong rather than fail.
--
-- Derived and disposable: `python -m orchestration.grades --full` rebuilds
-- both from the base tables. No feature builder may read them.

CREATE TABLE IF NOT EXISTS model_perf_daily (
    game_date          DATE NOT NULL,
    model_type         TEXT NOT NULL,
    model_version      TEXT NOT NULL,
    -- count(*): every prediction row for that variant on that day
    n                  INT NOT NULL,
    win_correct        INT NOT NULL,
    win_n              INT NOT NULL,
    margin_err_sum     DOUBLE PRECISION NOT NULL,
    margin_n           INT NOT NULL,
    total_err_sum      DOUBLE PRECISION NOT NULL,
    total_n            INT NOT NULL,
    -- Market comparison, over the subset with a plausible closing line
    -- (no-vig home probability inside [0.20, 0.85]). A capture outside that
    -- band is in-game contamination, not a pregame benchmark.
    mkt_n              INT NOT NULL,
    mkt_model_correct  INT NOT NULL,
    mkt_market_correct INT NOT NULL,
    mkt_pick_agree     INT NOT NULL,
    refreshed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- game_date leads so a trailing-window scan uses this index directly
    PRIMARY KEY (game_date, model_type, model_version)
);

CREATE TABLE IF NOT EXISTS batter_perf_daily (
    game_date     DATE NOT NULL,
    model_version TEXT NOT NULL,
    n             INT NOT NULL,
    brier_hit_sum DOUBLE PRECISION NOT NULL,
    brier_hit_n   INT NOT NULL,
    brier_hr_sum  DOUBLE PRECISION NOT NULL,
    brier_hr_n    INT NOT NULL,
    mae_h_sum     DOUBLE PRECISION NOT NULL,
    mae_h_n       INT NOT NULL,
    refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_date, model_version)
);
