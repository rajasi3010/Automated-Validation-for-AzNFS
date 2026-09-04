from __future__ import annotations

import os

os.environ.setdefault("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

import notifier
import query_status
import status_rollup
from status_rollup import buckets_by_state


def _img(label, state, image, sku, arch="x86_64", reason="", version="24.04.1"):
    return {"distro_label": label, "validated": state, "image": image, "sku": sku,
            "architecture": arch, "reason": reason, "version": version,
            "publisher": "Canonical"}


def test_rollup_carries_the_individual_skus():
    # "Ubuntu 24.04 is unsupported" is not actionable; the failing image is.
    records = [
        _img("Ubuntu 24.04", "known_supported", "ubuntu-24_04-lts", "server"),
        _img("Ubuntu 24.04", "known_unsupported", "ubuntu-24_04-lts", "minimal-arm64",
             arch="arm64", reason="prod repo is missing"),
    ]

    buckets = buckets_by_state(records)

    unsupported = buckets["known_unsupported"][0]
    assert unsupported["sku_count"] == 1
    assert unsupported["skus"] == [{
        "image": "ubuntu-24_04-lts", "sku": "minimal-arm64", "architecture": "arm64",
        "version": "24.04.1", "reason": "prod repo is missing",
    }]
    # The passing SKU stays visible under its own state.
    assert buckets["known_supported"][0]["skus"][0]["sku"] == "server"


def test_sku_reasons_are_redacted_like_the_distro_reason():
    records = [_img("Rocky 8", "known_unsupported", "rockylinux", "8-base",
                    reason="denied for client 'ea2ea2c0-c588-498a-984e-a12e390743b5'")]

    sku = buckets_by_state(records)["known_unsupported"][0]["skus"][0]

    assert "ea2ea2c0" not in sku["reason"]
    assert "denied for client" in sku["reason"]


def test_digest_email_names_the_failing_skus():
    buckets = {"known_unsupported": [{
        "distro_label": "Ubuntu 24.04", "version": "24.04.1", "publishers": ["Canonical"],
        "sku_count": 1, "reason": "prod repo is missing",
        "skus": [{"image": "ubuntu-24_04-lts", "sku": "minimal-arm64",
                  "architecture": "arm64", "reason": "prod repo is missing"}],
    }]}
    sent = {}

    notifier._send = lambda subject, plain, html_body, recipients: sent.update(
        {"plain": plain, "html": html_body}
    )
    notifier.send_monthly_reminder(buckets, recipients=["someone@example.com"])

    assert "ubuntu-24_04-lts/minimal-arm64" in sent["plain"]
    assert "ubuntu-24_04-lts/minimal-arm64" in sent["html"]


def test_supported_bucket_is_not_padded_with_sku_lists():
    # Only failures need the breakdown; 27 healthy SKUs would drown the mail.
    buckets = {"known_supported": [{
        "distro_label": "Ubuntu 22.04", "version": "22.04.1", "publishers": ["Canonical"],
        "sku_count": 2, "reason": "",
        "skus": [{"image": "ubuntu-22_04-lts", "sku": "server",
                  "architecture": "x86_64", "reason": ""}],
    }]}
    sent = {}

    notifier._send = lambda subject, plain, html_body, recipients: sent.update(
        {"plain": plain, "html": html_body}
    )
    notifier.send_monthly_reminder(buckets, recipients=["someone@example.com"])

    assert "ubuntu-22_04-lts/server" not in sent["plain"]


def test_skus_sharing_a_reason_are_listed_once_with_it():
    # Whole releases usually fail identically; repeating a 70-char reason per
    # SKU buries the one thing that matters -- which images are affected.
    skus = [
        {"image": "debian-11-daily", "sku": "11", "architecture": "x86_64", "reason": "no packages"},
        {"image": "debian-11-daily", "sku": "11-gen2", "architecture": "x86_64", "reason": "no packages"},
        {"image": "debian-11-daily", "sku": "11-arm", "architecture": "arm64", "reason": "repo missing"},
    ]

    grouped = status_rollup.group_skus_by_reason(skus)

    assert [r for r, _ in grouped] == ["no packages", "repo missing"]
    assert [len(g) for _, g in grouped] == [2, 1]


def test_markdown_cell_states_a_shared_reason_once():
    row = {"skus": [
        {"image": "debian-11-daily", "sku": "11", "architecture": "x86_64", "reason": "no packages"},
        {"image": "debian-11-daily", "sku": "11-gen2", "architecture": "x86_64", "reason": "no packages"},
    ]}

    cell = query_status._sku_cell(row)

    assert cell.count("no packages") == 1
    assert "`debian-11-daily/11 (x86_64)`" in cell
    assert "`debian-11-daily/11-gen2 (x86_64)`" in cell


def test_skus_with_no_reason_are_listed_without_a_dash():
    row = {"skus": [{"image": "img", "sku": "s", "architecture": "x86_64", "reason": ""}]}

    assert query_status._sku_cell(row) == "`img/s (x86_64)`"
