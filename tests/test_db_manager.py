from __future__ import annotations

import sqlite3

import db_manager


def test_reset_clears_all_validation_markers(tmp_path):
    # RESET_VALIDATION must clear last_regressed_version + last_validated_image_version
    # too, otherwise a reset 'unknown' row keeps a stale regression marker and Gate 3
    # can trust it into known_supported without a LISA run.
    db = str(tmp_path / "m.db")
    db_manager.initialize(db, "db/schema.sql")
    ident = ("RedHat", "rhel", "9_0", "eastus", "x86_64")
    db_manager.check_and_upsert(db, *ident[:3], "9.0.1", ident[3], ident[4], "yum", "RHEL 9")
    db_manager.set_validation_state(db, ident, "known_supported", last_validated_version="0.3.458")
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE images SET last_regressed_version='0.3.500', last_validated_image_version='9.0.1'"
    )
    conn.commit()
    conn.close()

    db_manager.reset_validation_to_unknown(db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT validated, last_validated_version, last_regressed_version, "
        "last_validated_image_version FROM images"
    ).fetchone()
    conn.close()
    assert row == ("unknown", "", "", "")


def test_reset_respects_exclude_states_but_still_clears_markers(tmp_path):
    # A pending_validation row is left untouched; every other row is reset AND has
    # all its validation markers cleared.
    db = str(tmp_path / "m.db")
    db_manager.initialize(db, "db/schema.sql")
    keep = ("RedHat", "rhel", "9_1", "eastus", "x86_64")
    reset = ("Canonical", "ubuntu-22_04-lts", "server", "eastus", "x86_64")
    db_manager.check_and_upsert(db, *keep[:3], "9.1.0", keep[3], keep[4], "yum", "RHEL 9")
    db_manager.check_and_upsert(db, *reset[:3], "22.04.1", reset[3], reset[4], "apt", "Ubuntu 22.04")
    db_manager.set_validation_state(db, keep, "pending_validation")
    db_manager.set_validation_state(db, reset, "known_supported", last_validated_version="0.3.458")
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE images SET last_regressed_version='0.3.500', last_validated_image_version='22.04.1' "
        "WHERE sku='server'"
    )
    conn.commit()
    conn.close()

    db_manager.reset_validation_to_unknown(db, exclude_states=("pending_validation",))

    conn = sqlite3.connect(db)
    kept = conn.execute("SELECT validated FROM images WHERE sku='9_1'").fetchone()[0]
    was_reset = conn.execute(
        "SELECT validated, last_regressed_version, last_validated_image_version "
        "FROM images WHERE sku='server'"
    ).fetchone()
    conn.close()
    assert kept == "pending_validation"           # excluded row untouched
    assert was_reset == ("unknown", "", "")         # reset + markers cleared
