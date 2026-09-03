from __future__ import annotations

import distro_lifecycle as dl


def test_ubuntu_lts_releases_are_validated():
    for label in ("Ubuntu 20.04", "Ubuntu 22.04", "Ubuntu 24.04", "Ubuntu 26.04"):
        assert dl.lifecycle(label) == dl.ACTIVE
        assert dl.is_validation_target(label)


def test_ubuntu_interim_releases_are_not_validated():
    # Non-LTS releases live ~9 months and AzNFS publishes for LTS only.
    for label in ("Ubuntu 25.04", "Ubuntu 25.10", "Ubuntu 26.10", "Ubuntu 23.10"):
        assert dl.lifecycle(label) == dl.INTERIM
        assert not dl.is_validation_target(label)
        assert "non-LTS" in dl.exclusion_reason(label)


def test_eol_releases_are_not_validated_and_say_why():
    assert dl.lifecycle("Ubuntu 16.04") == dl.EOL
    assert not dl.is_validation_target("Debian 10")
    assert "2024-10" in dl.exclusion_reason("SLES 12")


def test_non_ubuntu_releases_are_unaffected_by_the_lts_rule():
    for label in ("RHEL 9", "Rocky 9", "SLES 15", "Debian 13"):
        assert dl.is_validation_target(label)


def test_extra_eol_distros_can_retire_a_release_without_a_code_change(monkeypatch):
    monkeypatch.setenv("EXTRA_EOL_DISTROS", "RHEL 7, Ubuntu 18.04")

    assert not dl.is_validation_target("RHEL 7")
    assert dl.exclusion_reason("Ubuntu 18.04").startswith("declared EOL")
    assert dl.is_validation_target("RHEL 9")


def test_enforcement_can_be_switched_off_for_a_full_sweep(monkeypatch):
    monkeypatch.setenv("LIFECYCLE_ENFORCE", "0")

    assert dl.is_validation_target("Ubuntu 25.10")
    assert dl.is_validation_target("Debian 10")
    # The classification itself still reports the truth.
    assert dl.lifecycle("Debian 10") == dl.EOL
