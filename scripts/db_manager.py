"""
All SQLite operations for the marketplace scanner.

Responsibilities:
  - Initialize the database from schema.sql if it does not exist.
  - Insert a new image row (validated = 'unknown') when first seen.
  - Update last_checked on every scan for existing rows.
  - Return the full row dict for any image so it can be written to JSON.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO8601 string (e.g. 2026-05-26T00:00:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def initialize(db_path: str, schema_path: str) -> None:
    """Create the database file and tables from schema.sql if they do not exist.

    Safe to call on every run — all CREATE statements use IF NOT EXISTS.
    """
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with open(schema_path, "r") as fh:
        schema_sql = fh.read()

    conn = _connect(db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
        logger.info("Database ready at %s", db_path)
    finally:
        conn.close()


def check_and_upsert(
    db_path: str,
    publisher: str,
    image: str,
    sku: str,
    version: str,
    region: str,
) -> bool:
    """Check whether this exact image tuple exists in the database.

    - If it does NOT exist: insert a new row with validated='unknown' and
      return True  (signals that this image needs validation).
    - If it already exists: update only last_checked and return False.
    """
    now = _now_iso()
    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM images
            WHERE publisher = ?
              AND image     = ?
              AND sku       = ?
              AND version   = ?
              AND region    = ?
            """,
            (publisher, image, sku, version, region),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                """
                INSERT INTO images
                    (publisher, image, sku, version, region,
                     date_added, last_modified, last_checked, validated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unknown')
                """,
                (publisher, image, sku, version, region, now, now, now),
            )
            conn.commit()
            logger.info(
                "New image found: %s / %s / %s / %s [%s]",
                publisher, image, sku, version, region,
            )
            return True

        # Existing row — just refresh last_checked
        cursor.execute(
            "UPDATE images SET last_checked = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()
        return False

    finally:
        conn.close()


def get_image_record(
    db_path: str,
    publisher: str,
    image: str,
    sku: str,
    version: str,
    region: str,
) -> dict:
    """Return the full row for the given image as a plain Python dict."""
    conn = _connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM images
            WHERE publisher = ?
              AND image     = ?
              AND sku       = ?
              AND version   = ?
              AND region    = ?
            """,
            (publisher, image, sku, version, region),
        )
        row = cursor.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()
