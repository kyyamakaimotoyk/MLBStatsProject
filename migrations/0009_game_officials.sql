-- W0.2 (2026-07 cycle): full umpire crew per game, the serve path the retired
-- E3/E8b umpire retest is gated on. One row per (game, position); handles
-- 6-official postseason/special-event crews. captured_at is preserved on
-- re-upsert while the official identity is unchanged, so probe rows written
-- pregame by orchestration.daily keep the earliest-seen timestamp — that
-- first-seen-vs-first-pitch distribution is the officials-post-time
-- measurement the capture design depends on. Sources: 'feed' (live import),
-- 'backfill_s3' (GUMBO archive re-parse), 'probe_<tick>' (pregame probes),
-- 'retrosheet' (historical crews via the Chadwick id bridge).
CREATE TABLE IF NOT EXISTS game_officials (
    game_pk       BIGINT      NOT NULL,
    official_type TEXT        NOT NULL,
    official_id   BIGINT,
    official_name TEXT,
    source        TEXT        NOT NULL,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_pk, official_type)
);
CREATE INDEX IF NOT EXISTS idx_game_officials_official
    ON game_officials (official_id);
