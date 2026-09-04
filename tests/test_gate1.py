from __future__ import annotations

from src.phase2.orchestrator import gate1_repo_exists


class FakeProd:
    """Models PMC prod: which (distro, version) pockets exist."""

    def __init__(self, repos: dict[str, set[str]] | None = None) -> None:
        # distro -> set of version segments whose /prod/ pocket returns 200
        self.repos = repos or {}
        self.resolve_calls: list[tuple] = []

    def resolve_repo(self, distro: str, candidates: list[str], family: str = "") -> str | None:
        self.resolve_calls.append((distro, tuple(candidates), family))
        present = self.repos.get(distro, set())
        for v in candidates:
            if v in present:
                return v
        return None

    def list_packages(self, distro, version, family):  # unused by gate 1
        return []


def entry(**kw):
    base = {
        "publisher": "Canonical",
        "distro_label": "Ubuntu 22.04",
        "version": "22.04.202506",
        "family": "apt",
    }
    base.update(kw)
    return base


def test_pass_exact_version():
    prod = FakeProd({"ubuntu": {"22.04"}})
    r = gate1_repo_exists(entry(), prod)
    assert r.passed
    assert r.segment == "ubuntu"
    assert r.resolved_version == "22.04"


def test_pass_rhel_x0_release_probes_both_pockets():
    prod = FakeProd({"rhel": {"9"}})  # PMC serves the same pocket at 9 and 9.0
    r = gate1_repo_exists(entry(publisher="RedHat", distro_label="RHEL 9.0", family="yum"), prod)
    assert r.passed
    assert r.segment == "rhel"
    assert r.resolved_version == "9"
    assert prod.resolve_calls[-1] == ("rhel", ("9", "9.0"), "yum")


def test_rhel_other_minor_never_falls_back_to_the_major():
    # AzNFS publishes to rhel/9.0; rhel/9.8 is its own pocket with no packages,
    # so resolving it to /rhel/9/ would claim support the release does not have.
    prod = FakeProd({"rhel": {"9"}})
    r = gate1_repo_exists(entry(publisher="RedHat", distro_label="RHEL 9.8", family="yum"), prod)
    assert not r.passed
    assert prod.resolve_calls[-1] == ("rhel", ("9.8",), "yum")


def test_fail_unmapped_distro():
    prod = FakeProd({"ubuntu": {"22.04"}})
    r = gate1_repo_exists(entry(publisher="BellLabs", distro_label="Plan9 4"), prod)
    assert not r.passed
    assert r.reason == "unmapped distro"


def test_fail_unparseable_version():
    prod = FakeProd({"ubuntu": {"22.04"}})
    r = gate1_repo_exists(entry(distro_label="Ubuntu", version="no-numbers"), prod)
    assert not r.passed
    assert r.reason == "unparseable version"


def test_fail_prod_repo_missing():
    prod = FakeProd({})  # nothing on prod
    r = gate1_repo_exists(entry(), prod)
    assert not r.passed
    assert r.reason == "prod repo missing"
    assert "ubuntu" in r.details
