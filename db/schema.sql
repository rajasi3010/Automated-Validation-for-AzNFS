-- Schema for marketplace image tracking database.
-- This file is the source of truth; the Python script creates the DB from this on first run.

CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    publisher     TEXT    NOT NULL,
    image         TEXT    NOT NULL,   -- Azure SDK "offer" field (e.g. 0001-com-ubuntu-server-focal)
    sku           TEXT    NOT NULL,   -- Azure SDK "sku"   field (e.g. 20_04-lts-gen2)
    version       TEXT    NOT NULL,   -- Version string    (e.g. 20.04.202405010)
    region        TEXT    NOT NULL,   -- Azure region      (e.g. eastus)
    date_added    TEXT    NOT NULL,   -- ISO8601 UTC, set once on first insert
    last_modified TEXT    NOT NULL,   -- ISO8601 UTC, updated when the row itself changes
    last_checked  TEXT    NOT NULL,   -- ISO8601 UTC, updated on every scan run
    validated     TEXT    NOT NULL DEFAULT 'unknown',
                                      -- unknown           : LISA testing not yet done
                                      -- known_supported   : passed all LISA test cases
                                      -- known_unsupported : failed one or more LISA test cases
    UNIQUE(publisher, image, sku, version, region)
);

CREATE INDEX IF NOT EXISTS idx_validated  ON images(validated);
CREATE INDEX IF NOT EXISTS idx_region     ON images(region);
CREATE INDEX IF NOT EXISTS idx_publisher  ON images(publisher);
