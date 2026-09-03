from __future__ import annotations

import os

os.environ.setdefault("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

from status_rollup import buckets_by_state


def _img(label, state, sku, reason="", version="24.04.1", publisher="Canonical"):
    return {"distro_label": label, "validated": state, "sku": sku, "reason": reason,
            "version": version, "publisher": publisher, "image": "img",
            "architecture": "x86_64"}


def test_eol_and_interim_releases_get_their_own_bucket():
    # They used to inflate "unsupported" even though a missing package there is
    # expected, not a finding.
    records = [
        _img("Ubuntu 24.04", "known_supported", "server"),
        _img("Ubuntu 25.10", "known_unsupported", "server", reason="no packages"),
        _img("Debian 10", "known_unsupported", "10", reason="no packages"),
    ]

    buckets = buckets_by_state(records)

    assert [d["distro_label"] for d in buckets["out_of_scope"]] == ["Debian 10", "Ubuntu 25.10"]
    assert buckets.get("known_unsupported", []) == []
    reasons = {d["distro_label"]: d["reason"] for d in buckets["out_of_scope"]}
    assert "non-LTS" in reasons["Ubuntu 25.10"]
    assert "LTS ended" in reasons["Debian 10"]


def test_in_scope_releases_keep_their_per_sku_verdicts():
    # Excluding EOL releases must not collapse everything else: a distro whose
    # SKUs disagree still appears under each state, with the SKUs attached.
    records = [
        _img("Ubuntu 24.04", "known_supported", "server"),
        _img("Ubuntu 24.04", "known_unsupported", "minimal-arm64", reason="prod repo is missing"),
    ]

    buckets = buckets_by_state(records)

    assert [d["distro_label"] for d in buckets["known_supported"]] == ["Ubuntu 24.04"]
    assert buckets["known_unsupported"][0]["skus"][0]["sku"] == "minimal-arm64"


def test_latest_version_and_publishers_are_still_collapsed():
    records = [
        _img("SLES 15", "unknown", "gen1", version="2026.01", publisher="SUSE"),
        _img("SLES 15", "unknown", "gen2", version="2026.08", publisher="SUSE"),
    ]

    rollup = buckets_by_state(records)["unknown"][0]

    assert rollup["version"] == "2026.08"
    assert rollup["publishers"] == ["SUSE"]
    assert rollup["sku_count"] == 2
