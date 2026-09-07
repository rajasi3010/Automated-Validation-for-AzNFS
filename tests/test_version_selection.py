from __future__ import annotations

import db_manager


# RedHat/RHEL/8-LVM really does carry 8.0 through 8.10, so the newest is the one
# a string comparison ranks lowest of the recent ones.
_REAL_8_LVM_TAIL = [
    "8.7.2023022813",
    "8.8.2023081717",
    "8.9.2024022012",
    "8.10.2026061712",
]


def test_the_newest_version_of_an_aggregate_sku_is_picked():
    assert max(_REAL_8_LVM_TAIL, key=db_manager.version_tuple) == "8.10.2026061712"


def test_a_string_max_would_have_picked_the_stale_one():
    # Guards the reason for the key= argument: without it the scan recorded a
    # 2024 image as current and never saw the 2026 one.
    assert max(_REAL_8_LVM_TAIL) == "8.9.2024022012"


def test_date_style_versions_are_unaffected():
    ubuntu = ["22.04.202608210", "22.04.202609040"]

    assert max(ubuntu, key=db_manager.version_tuple) == max(ubuntu)
