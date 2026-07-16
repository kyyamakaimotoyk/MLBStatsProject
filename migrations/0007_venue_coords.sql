-- E6b: venue coordinates for the weather forecast feed.
ALTER TABLE venues ADD COLUMN IF NOT EXISTS latitude REAL;
ALTER TABLE venues ADD COLUMN IF NOT EXISTS longitude REAL;
