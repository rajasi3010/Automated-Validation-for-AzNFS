from __future__ import annotations

import os

os.environ.setdefault("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

from scan_marketplace import buckets_by_state


def _img(label, state, sku, reason="", version="24.04.1", publisher="Canonical"):
    return {"distro_label": label, "validated": state, "sku": sku, "reason": reason,
            "version": version, "publisher": publisher}


def test_distro_appears_in_exactly_one_bucket():
    # A niche SKU holding a stale verdict must not put the distro in two buckets
    # at once (Ubuntu 24.04 was listed as supported AND "prod repo is missing").
    records = [
        _img("Ubuntu 24.04", "known_supported", "server"),
        _img("Ubuntu 24.04", "known_unsupported", "minimal-arm64", reason="prod repo is missing"),
        _img("Ubuntu 24.04", "unknown", "cvm"),
    ]

    buckets = buckets_by_state(records)

    assert [d["distro_label"] for d in buckets["known_supported"]] == ["Ubuntu 24.04"]
    assert buckets.get("known_unsupported", []) == []
    assert buckets.get("unknown", []) == []
    assert buckets["known_supported"][0]["sku_count"] == 3


def test_unsupported_beats_unknown_but_loses_to_supported():
    records = [
        _img("Debian 11", "known_unsupported", "11", reason="not in the support set"),
        _img("Debian 11", "unknown", "11-gen2"),
    ]

    buckets = buckets_by_state(records)

    assert [d["distro_label"] for d in buckets["known_unsupported"]] == ["Debian 11"]
    assert buckets.get("unknown", []) == []
    assert buckets["known_unsupported"][0]["reason"] == "not in the support set"


def test_reason_is_dropped_once_a_distro_counts_as_supported():
    records = [
        _img("Rocky 9", "known_supported", "9-base"),
        _img("Rocky 9", "known_unsupported", "9-lvm", reason="no AzNFS packages found"),
    ]

    buckets = buckets_by_state(records)

    assert buckets["known_supported"][0]["reason"] == ""


def test_latest_version_and_publishers_are_still_collapsed():
    records = [
        _img("SLES 15", "unknown", "gen1", version="2026.01", publisher="SUSE"),
        _img("SLES 15", "unknown", "gen2", version="2026.08", publisher="SUSE"),
    ]

    rollup = buckets_by_state(records)["unknown"][0]

    assert rollup["version"] == "2026.08"
    assert rollup["publishers"] == ["SUSE"]
    assert rollup["sku_count"] == 2
