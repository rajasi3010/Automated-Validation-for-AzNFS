from __future__ import annotations

import aznfs_support as m


def test_matrix_matches_the_aznfs_supported_list():
    assert m.SUPPORTED_UBUNTU == {"18.04", "20.04", "22.04", "24.04", "26.04"}
    assert m.SUPPORTED_RHEL == {"7", "8", "9", "10"}
    assert m.SUPPORTED_ROCKY == {"8", "9"}
    assert m.SUPPORTED_SLES == {"15", "16"}


def test_releases_inside_the_matrix():
    for label in ("Ubuntu 22.04", "Ubuntu 26.04", "RHEL 9", "RHEL 10",
                  "Rocky 8", "SLES 15", "SLES 16"):
        assert m.is_supported_distro(label), label


def test_releases_outside_the_matrix():
    # Ubuntu interim + retired releases, and families AzNFS does not target.
    for label in ("Ubuntu 25.04", "Ubuntu 25.10", "Ubuntu 26.10", "Ubuntu 16.04",
                  "Ubuntu 14.04", "Debian 11", "Debian 12", "Azure Linux 3",
                  "CBL-Mariner 2", "openSUSE", "CentOS 7", "Ubuntu Core 24"):
        assert not m.is_supported_distro(label), label


def test_rhel_minor_releases_follow_their_major():
    # rhel/8.1 and rhel/9.6 are in scope because RHEL 8 and 9 are.
    assert m.is_supported_distro("RHEL 8.1")
    assert m.is_supported_distro("RHEL 9.6")
    assert not m.is_supported_distro("RHEL 6.5")


def test_unparseable_labels_are_out_of_scope():
    for label in ("", "Debian", "SUSE Linux", "RHEL"):
        assert not m.is_supported_distro(label)
