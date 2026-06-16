"""Snapshot of the tuxdev listings used in tests."""
from src.phase2.repo_index import RepoIndex

APT = frozenset({
    "microsoft-debian-jessie", "microsoft-debian-stretch", "microsoft-debian-buster",
    "microsoft-debian-bullseye", "microsoft-debian-bookworm", "microsoft-debian-trixie",
    "microsoft-ubuntu-1604-xenial", "microsoft-ubuntu-1804-bionic",
    "microsoft-ubuntu-2004-focal", "microsoft-ubuntu-2010-groovy",
    "microsoft-ubuntu-2104-hirsute", "microsoft-ubuntu-2110-impish",
    "microsoft-ubuntu-2204-jammy", "microsoft-ubuntu-2210-kinetic",
    "microsoft-ubuntu-2304-lunar", "microsoft-ubuntu-2310-mantic",
    "microsoft-ubuntu-jammy", "microsoft-ubuntu-noble",
    "microsoft-ubuntu-questing", "microsoft-ubuntu-resolute",
    "tux-dev",
})

YUM = frozenset({
    "microsoft-rhel7", "microsoft-rhel7.0", "microsoft-rhel7.3",
    "microsoft-rhel8", "microsoft-rhel8.0",
    "microsoft-rhel9", "microsoft-rhel9.0", "microsoft-rhel10",
    "microsoft-sles12", "microsoft-sles15", "microsoft-sles16",
    "microsoft-el8", "microsoft-el9", "microsoft-opensuse15",
    "tuxdev-rhel7",
})

INDEX = RepoIndex(apt=APT, yum=YUM)
