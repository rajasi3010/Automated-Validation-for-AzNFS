from __future__ import annotations

import aznfs_support as m


def test_publish_targets_mirror_packages_csv():
    # Column 1 of AZNFS-mount/packages.csv, minus the EOL CentOS entries.
    assert m.PUBLISH_TARGETS == {
        "Ubuntu": {"18.04", "20.04", "22.04", "24.04", "26.04"},
        "RHEL": {"7.0", "7.3", "8.0", "9.0", "10.0"},
        "Rocky": {"8.0", "9.0"},
        "SUSE": {"15", "16"},
        "Debian": {"13"},
    }


def test_scope_is_the_publish_targets_plus_their_bare_major():
    # "RHEL 8" and "RHEL 8.0" both label the 8.0 target; 8.1 is a separate
    # release AzNFS publishes nothing for.
    assert m.SUPPORTED_RHEL == {"7", "7.0", "7.3", "8", "8.0", "9", "9.0", "10", "10.0"}
    assert m.SUPPORTED_ROCKY == {"8", "8.0", "9", "9.0"}
    assert m.SUPPORTED_SLES == {"15", "16"}
    assert m.SUPPORTED_UBUNTU == {"18.04", "20.04", "22.04", "24.04", "26.04"}
    assert m.SUPPORTED_DEBIAN == {"13"}


def test_releases_inside_the_matrix():
    for label in ("Ubuntu 22.04", "Ubuntu 26.04", "RHEL 9", "RHEL 9.0",
                  "Rocky 8", "Rocky 9.0", "SLES 15", "SLES 16", "Debian 13"):
        assert m.is_supported_distro(label), label


def test_releases_outside_the_matrix():
    # Ubuntu interim + retired releases, and families AzNFS does not target.
    for label in ("Ubuntu 25.04", "Ubuntu 25.10", "Ubuntu 26.10", "Ubuntu 16.04",
                  "Ubuntu 14.04", "Debian 11", "Debian 12", "Debian 14",
                  "Azure Linux 3",
                  "CBL-Mariner 2", "openSUSE", "CentOS 7", "Ubuntu Core 24"):
        assert not m.is_supported_distro(label), label


def test_other_rhel_minors_are_out_of_scope():
    # AzNFS publishes to rhel/8.0; rhel/8.1 is its own pocket with no packages.
    for label in ("RHEL 8.1", "RHEL 8.6", "RHEL 9.6", "RHEL 10.2", "RHEL 6.5"):
        assert not m.is_supported_distro(label), label
    for label in ("RHEL 8", "RHEL 8.0", "RHEL 7.3", "RHEL 10.0"):
        assert m.is_supported_distro(label), label


def test_unparseable_labels_are_out_of_scope():
    for label in ("", "Debian", "SUSE Linux", "RHEL"):
        assert not m.is_supported_distro(label)
