import pytest

from src.phase2.orchestrator import gate1_evaluate as evaluate
from src.phase2.repo_index import RepoIndex
from tests.fixtures.repo_index import INDEX


def row(publisher: str, version: str, family: str = ""):
    return {"publisher": publisher, "version": version, "family": family}


@pytest.mark.parametrize("publisher,version,expected_repo", [
    ("Canonical", "24.04.202405xx", "microsoft-ubuntu-noble"),
    ("Canonical", "22.04.20240101", "microsoft-ubuntu-jammy"),
    ("Canonical", "20.04.20240101", "microsoft-ubuntu-2004-focal"),
    ("Canonical", "26.04.20260101", "microsoft-ubuntu-resolute"),
    ("Debian",    "12.20240101",    "microsoft-debian-bookworm"),
    ("Debian",    "13",             "microsoft-debian-trixie"),
    ("RedHat",    "9.3.2023121113", "microsoft-rhel9"),
    ("RedHat",    "9.0.2023121113", "microsoft-rhel9.0"),
    ("RedHat",    "8.6.2023121113", "microsoft-rhel8"),
    ("RedHat",    "10.0.2026",      "microsoft-rhel10"),
    ("SUSE",      "15.5.20250101",  "microsoft-sles15"),
    ("SUSE",      "12.5",           "microsoft-sles12"),
])
def test_pass(publisher, version, expected_repo):
    r = evaluate(row(publisher, version), INDEX)
    assert r.passed, r.reason
    assert r.resolved_repo == expected_repo
    assert r.matched_repos


def test_unmapped_publisher():
    r = evaluate(row("Fedora", "40"), INDEX)
    assert not r.passed
    assert r.reason == "unmapped publisher"


def test_unmapped_distro_version():
    r = evaluate(row("Canonical", "27.04"), INDEX)
    assert not r.passed
    assert r.reason == "unmapped distro version"


def test_missing_repo_for_known_codename():
    sparse = RepoIndex(apt=frozenset({"microsoft-ubuntu-jammy"}), yum=frozenset())
    r = evaluate(row("Canonical", "26.04"), sparse)
    assert not r.passed
    assert r.reason == "tuxdev repo missing"
    assert "microsoft-ubuntu-resolute" in r.details


def test_unparseable_version():
    r = evaluate(row("Canonical", "garbage"), INDEX)
    assert not r.passed
    assert r.reason == "unparseable version"


def test_both_numeric_and_codename_repo_present_gate1_passes():
    index = RepoIndex(
        apt=frozenset({"microsoft-ubuntu-jammy", "microsoft-ubuntu-2204"}),
        yum=frozenset(),
    )
    r = evaluate(row("Canonical", "22.04.20240101"), index)
    assert r.passed
    assert "microsoft-ubuntu-jammy" in (r.matched_repos or [])
    assert "microsoft-ubuntu-2204" in (r.matched_repos or [])
