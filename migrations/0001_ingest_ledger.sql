-- Idempotent-ingest ledger (the NBA importedgamesmemory pattern, generalized).
-- One row per fetchable object per source; ingestion consults it before any
-- network call and updates it after.
--
-- status values:
--   pending            not yet successfully imported
--   imported           parsed and loaded; raw JSON archived at s3_key
--   permanent_missing  the source will never have this (don't retry)
--   error              last attempt failed; retry while attempts < cap

CREATE TABLE IF NOT EXISTS ingest_ledger (
    source        TEXT        NOT NULL,  -- e.g. 'statsapi_game', 'statcast_day', 'odds_day'
    object_key    TEXT        NOT NULL,  -- game_pk, date, or other source-native id
    status        TEXT        NOT NULL DEFAULT 'pending',
    attempts      INTEGER     NOT NULL DEFAULT 0,
    s3_key        TEXT,                  -- raw archive location once imported
    detail        TEXT,                  -- last error message or note
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, object_key)
);

CREATE INDEX IF NOT EXISTS idx_ingest_ledger_status
    ON ingest_ledger (source, status);
