from __future__ import annotations

import scan_marketplace


def _row(image, sku, version, label="Ubuntu 22.04", arch="arm64", validated="unknown"):
    return {
        "publisher": "Canonical", "image": image, "sku": sku, "version": version,
        "region": "centralindia", "architecture": arch, "family": "debian",
        "distro_label": label, "validated": validated,
    }


# The real Ubuntu 22.04 arm64 candidates on 2026-09-07. Canonical rebuilt the
# pro+FIPS SKU that morning, so it was the only one in the delta.
_PRO_FIPS = _row("0001-com-ubuntu-pro-jammy-fips", "pro-fips-22_04-arm64",
                 "22.04.202608210")
_PLAIN = _row("ubuntu-22_04-lts", "server-arm64", "22.04.202609040")
_DAILY = _row("ubuntu-22_04-lts-daily", "server-arm64", "22.04.202608280")


def test_a_refreshed_plan_gated_sku_validates_the_plain_image_instead():
    # The pro+FIPS image carries a purchase plan this subscription cannot
    # accept, so validating it yields a deployment failure, not a verdict.
    picked = scan_marketplace.best_images_for_changed(
        [_PRO_FIPS], [_PRO_FIPS, _PLAIN, _DAILY]
    )

    assert [(p["image"], p["sku"]) for p in picked] == [
        ("ubuntu-22_04-lts", "server-arm64")
    ]


def test_a_changed_release_is_still_handed_over():
    # Re-picking must not drop the release: something changed, so it is checked.
    picked = scan_marketplace.best_images_for_changed([_PRO_FIPS], [_PRO_FIPS, _PLAIN])

    assert len(picked) == 1
    assert picked[0]["distro_label"] == "Ubuntu 22.04"


def test_untouched_releases_are_not_dragged_in():
    other = _row("ubuntu-24_04-lts", "server-arm64", "24.04.1", label="Ubuntu 24.04")

    picked = scan_marketplace.best_images_for_changed([_PRO_FIPS], [_PRO_FIPS, _PLAIN, other])

    assert {p["distro_label"] for p in picked} == {"Ubuntu 22.04"}


def test_architectures_stay_separate():
    x86 = _row("ubuntu-22_04-lts", "server", "22.04.202609040", arch="x86_64")

    picked = scan_marketplace.best_images_for_changed(
        [_PRO_FIPS, x86], [_PRO_FIPS, _PLAIN, x86]
    )

    assert sorted(p["architecture"] for p in picked) == ["arm64", "x86_64"]


def test_nothing_changed_hands_over_nothing():
    assert scan_marketplace.best_images_for_changed([], [_PLAIN]) == []
