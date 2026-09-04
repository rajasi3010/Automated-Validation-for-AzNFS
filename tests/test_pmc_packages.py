from __future__ import annotations

from datetime import timezone

import pytest
import requests

from src.phase2.pmc_packages import (
    _parse_index_time,
    AZNFS_SERIES,
    ProbeError,
    ProdPackageIndex,
    aznfs_dir_url,
    distro_segment,
    file_arch,
    in_series,
    index_kind,
    normalize_arch,
    repo_base_url,
    version_candidates,
    version_from_filename,
    version_tuple,
)

BASE = "https://packages.microsoft.com"


# ---------------------------------------------------------------------------
# Fake HTTP session
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession:
    """Returns a canned page per URL; 404 for anything unmapped."""

    def __init__(self, pages: dict[str, _Resp]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, timeout: int | None = None) -> _Resp:
        self.requested.append(url)
        return self.pages.get(url, _Resp(status_code=404))


# Real-shaped yum autoindex page (rhel/9 Packages/a/) with aznfs builds.
YUM_HTML_WITH_AZNFS = """
<a href="../">../</a>
<a href="acl-debuginfo-2.2.53-5.el9.x86_64.rpm">acl-debuginfo-...</a>
<a href="aznfs-0.3.2-1.x86_64.rpm">aznfs-0.3.2-1.x86_64.rpm</a>
<a href="aznfs-0.3.2-1.aarch64.rpm">aznfs-0.3.2-1.aarch64.rpm</a>
"""

# The real autoindex carries a date column, which is the only publication
# time PMC exposes. Note 0.3.49 was published AFTER 0.3.459.
YUM_HTML_DATED = """
<a href="../">../</a>
<a href="./aznfs-0.3.459-1.x86_64.rpm">aznfs-0.3.459-1.x86_64.rpm</a>   02-Sep-2026 07:06  9.0 MB
<a href="./aznfs-0.3.49-1.x86_64.rpm">aznfs-0.3.49-1.x86_64.rpm</a>     02-Sep-2026 14:09  9.0 MB
<a href="./aznfs-0.0.676-1.x86_64.rpm">aznfs-0.0.676-1.x86_64.rpm</a>   06-Feb-2026 11:10  9.0 MB
"""

YUM_HTML_NO_AZNFS = """
<a href="../">../</a>
<a href="acl-debuginfo-2.2.53-5.el9.x86_64.rpm">acl-debuginfo-...</a>
<a href="alsa-lib-1.2.2-2.el9.x86_64.rpm">alsa-lib-...</a>
"""

APT_HTML_WITH_AZNFS = """
<a href="../">../</a>
<a href="aznfs_0.3.2_amd64.deb">aznfs_0.3.2_amd64.deb</a>
<a href="aznfs_0.3.2_arm64.deb">aznfs_0.3.2_arm64.deb</a>
"""


# ---------------------------------------------------------------------------
# distro_label / publisher -> PMC segment + index kind
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("label,publisher,expected", [
    ("Ubuntu 22.04", "Canonical", "ubuntu"),
    ("RHEL 9.8", "RedHat", "rhel"),
    ("openSUSE 15.5", "SUSE", "opensuse"),   # keyword beats the SUSE->sles publisher map
    ("SLES 15", "SUSE", "sles"),
    ("Debian 11", "Debian", "debian"),
    ("", "Canonical", "ubuntu"),             # publisher fallback when label has no keyword
])
def test_distro_segment(label, publisher, expected):
    assert distro_segment(label, publisher) == expected


def test_distro_segment_unmapped_returns_none():
    assert distro_segment("Plan9 4", "BellLabs") is None


@pytest.mark.parametrize("label,publisher,family,expected", [
    ("Ubuntu 22.04", "Canonical", "apt", "apt"),   # family wins
    ("RHEL 9", "RedHat", "", "yum"),               # label keyword
    ("Ubuntu 22.04", "", "", "apt"),
    ("RHEL 9", "RedHat", "apt", "apt"),            # explicit family overrides label
])
def test_index_kind(label, publisher, family, expected):
    assert index_kind(label, publisher, family) == expected


@pytest.mark.parametrize("label,fallback,expected", [
    # Only an x / x.0 release is served at two paths, so only it probes both.
    ("RHEL 10", "", ["10", "10.0"]),
    ("RHEL 9.0", "", ["9", "9.0"]),
    ("Debian 11", "", ["11", "11.0"]),
    # Everything else is its own release and probes itself alone.
    ("Ubuntu 22.04", "", ["22.04"]),
    ("RHEL 9.8", "", ["9.8"]),
    ("RHEL 8.1", "", ["8.1"]),
    ("", "24.04.202506", ["24.04"]),   # fall back to the marketplace version
    ("no-numbers", "also-none", []),
])
def test_version_candidates(label, fallback, expected):
    assert version_candidates(label, fallback) == expected


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------
def test_repo_base_url():
    assert repo_base_url("ubuntu", "22.04", BASE) == f"{BASE}/ubuntu/22.04/prod/"


def test_apt_aznfs_dir_url_uses_pool_main_a_aznfs():
    assert aznfs_dir_url("ubuntu", "22.04", "apt", BASE) == \
        f"{BASE}/ubuntu/22.04/prod/pool/main/a/aznfs/"


def test_yum_aznfs_dir_url_uses_packages_a():
    assert aznfs_dir_url("rhel", "9", "yum", BASE) == \
        f"{BASE}/rhel/9/prod/Packages/a/"


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("aznfs_0.3.2_amd64.deb", "0.3.2"),
    ("aznfs-0.3.2-1.x86_64.rpm", "0.3.2"),
    ("aznfs-3.0.18-1.aarch64.rpm", "3.0.18"),
])
def test_version_from_filename(name, expected):
    assert version_from_filename(name) == expected


@pytest.mark.parametrize("name,family,expected", [
    ("aznfs_0.3.2_amd64.deb", "apt", "amd64"),
    ("aznfs_0.3.2_arm64.deb", "apt", "arm64"),
    ("aznfs-0.3.2-1.x86_64.rpm", "yum", "x86_64"),
    ("aznfs-0.3.2-1.aarch64.rpm", "yum", "aarch64"),
    ("aznfs-0.3.2-1.cm2.x86_64.rpm", "yum", "x86_64"),   # mariner-style extra token
])
def test_file_arch(name, family, expected):
    assert file_arch(name, family) == expected


@pytest.mark.parametrize("arch,family,expected", [
    ("x86_64", "apt", "amd64"),
    ("arm64", "apt", "arm64"),
    ("x86_64", "yum", "x86_64"),
    ("arm64", "yum", "aarch64"),
    ("aarch64", "yum", "aarch64"),
])
def test_normalize_arch(arch, family, expected):
    assert normalize_arch(arch, family) == expected


def test_version_tuple_is_numeric_not_lexical():
    # The whole reason version_tuple exists: 0.3.18 > 0.3.9 numerically, but
    # string compare would rank "0.3.9" higher.
    assert version_tuple("0.3.18") > version_tuple("0.3.9")
    assert version_tuple("3.0.18") > version_tuple("0.3.9")
    assert max(["aznfs_0.3.9_amd64.deb", "aznfs_0.3.18_amd64.deb"],
               key=lambda f: version_tuple(version_from_filename(f))) == "aznfs_0.3.18_amd64.deb"


@pytest.mark.parametrize("version,expected", [
    ("0.3.0", True),
    ("0.3.9", True),
    ("0.3.46", True),
    ("0.3.458", True),     # high patch numbers stay in series
    ("0.2.3", False),
    ("0.0.676", False),
    ("1.0.4", False),
    ("2.1.3", False),
    ("3.0.18", False),     # the lineage that must never be picked
    ("0.30.1", False),     # numeric guard: 0.30 != 0.3
])
def test_in_series_matches_only_0_3_x(version, expected):
    assert in_series(version) is expected
    assert AZNFS_SERIES == "0.3"


# ---------------------------------------------------------------------------
# ProdPackageIndex.resolve_repo  (repo-exists probe with minor->major fallback)
# ---------------------------------------------------------------------------
def test_resolve_repo_returns_first_existing_candidate():
    # rhel/9.8 is 404, rhel/9 is 200 -> resolves to "9" (the real PMC fallback).
    url9 = repo_base_url("rhel", "9", BASE)
    sess = _FakeSession({url9: _Resp("ok")})
    idx = ProdPackageIndex(base_url=BASE, session=sess)

    assert idx.resolve_repo("rhel", ["9.8", "9"], "yum") == "9"
    assert sess.requested == [repo_base_url("rhel", "9.8", BASE), url9]  # tried minor first


def test_resolve_repo_none_when_no_candidate_exists():
    sess = _FakeSession({})  # everything 404s
    idx = ProdPackageIndex(base_url=BASE, session=sess)
    assert idx.resolve_repo("ubuntu", ["27.04", "27"], "apt") is None


# ---------------------------------------------------------------------------
# ProdPackageIndex.list_packages  (package-exists listing)
# ---------------------------------------------------------------------------
def test_list_packages_yum_returns_aznfs_only():
    url = aznfs_dir_url("rhel", "9", "yum", BASE)
    sess = _FakeSession({url: _Resp(YUM_HTML_WITH_AZNFS)})
    idx = ProdPackageIndex(base_url=BASE, session=sess)
    assert idx.list_packages("rhel", "9", "yum") == [
        "aznfs-0.3.2-1.x86_64.rpm",
        "aznfs-0.3.2-1.aarch64.rpm",
    ]


def test_list_packages_yum_without_aznfs_returns_empty():
    url = aznfs_dir_url("rhel", "9", "yum", BASE)
    sess = _FakeSession({url: _Resp(YUM_HTML_NO_AZNFS)})
    idx = ProdPackageIndex(base_url=BASE, session=sess)
    assert idx.list_packages("rhel", "9", "yum") == []


def test_list_packages_apt_returns_debs():
    url = aznfs_dir_url("ubuntu", "22.04", "apt", BASE)
    sess = _FakeSession({url: _Resp(APT_HTML_WITH_AZNFS)})
    idx = ProdPackageIndex(base_url=BASE, session=sess)
    assert idx.list_packages("ubuntu", "22.04", "apt") == [
        "aznfs_0.3.2_amd64.deb",
        "aznfs_0.3.2_arm64.deb",
    ]


def test_list_packages_404_returns_empty():
    # Debian real case: repo exists but pool/main/a/aznfs/ is absent (404).
    sess = _FakeSession({})
    idx = ProdPackageIndex(base_url=BASE, session=sess)
    assert idx.list_packages("debian", "11", "apt") == []


def test_list_packages_records_publication_times():
    url = aznfs_dir_url("rhel", "9", "yum", BASE)
    idx = ProdPackageIndex(base_url=BASE, session=_FakeSession({url: _Resp(YUM_HTML_DATED)}))
    idx.list_packages("rhel", "9", "yum")

    assert idx.published_at("rhel", "9", "yum", "aznfs-0.3.49-1.x86_64.rpm") > \
           idx.published_at("rhel", "9", "yum", "aznfs-0.3.459-1.x86_64.rpm")


def test_published_at_is_none_when_the_index_has_no_dates():
    url = aznfs_dir_url("rhel", "9", "yum", BASE)
    idx = ProdPackageIndex(base_url=BASE, session=_FakeSession({url: _Resp(YUM_HTML_WITH_AZNFS)}))
    idx.list_packages("rhel", "9", "yum")

    assert idx.published_at("rhel", "9", "yum", "aznfs-0.3.2-1.x86_64.rpm") is None


class _SwitchingSession:
    """Serves a different page for the same URL on each call."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return self.pages.pop(0) if self.pages else _Resp("", 404)


class _ExplodingSession:
    """Every request dies the way a timeout / DNS blip does."""

    def __init__(self):
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        raise requests.ConnectionError("read timed out")


def test_a_relisting_without_dates_clears_the_old_timestamps():
    # If the index stops publishing the date column, the previous run's
    # timestamps must not linger -- ordering has to fall back to version order.
    url = aznfs_dir_url("rhel", "9", "yum", BASE)
    sess = _SwitchingSession([_Resp(YUM_HTML_DATED), _Resp(YUM_HTML_WITH_AZNFS)])
    idx = ProdPackageIndex(base_url=BASE, session=sess)

    idx.list_packages("rhel", "9", "yum")
    assert idx.published_at("rhel", "9", "yum", "aznfs-0.3.49-1.x86_64.rpm") is not None

    idx.list_packages("rhel", "9", "yum")
    assert idx.published_at("rhel", "9", "yum", "aznfs-0.3.49-1.x86_64.rpm") is None


def test_a_vanished_directory_clears_its_timestamps():
    sess = _SwitchingSession([_Resp(YUM_HTML_DATED), _Resp("", 404)])
    idx = ProdPackageIndex(base_url=BASE, session=sess)

    idx.list_packages("rhel", "9", "yum")
    idx.list_packages("rhel", "9", "yum")

    assert idx.published_at("rhel", "9", "yum", "aznfs-0.3.49-1.x86_64.rpm") is None


@pytest.mark.parametrize("stamp,expected", [
    ("03-Sep-2026 17:58", (2026, 9, 3, 17, 58)),
    ("06-Feb-2026 11:10", (2026, 2, 6, 11, 10)),
    ("23-Mar-2025 19:05", (2025, 3, 23, 19, 5)),
    ("31-Dec-2026 00:00", (2026, 12, 31, 0, 0)),
])
def test_index_time_parses_every_month_name(stamp, expected):
    got = _parse_index_time(stamp)
    assert (got.year, got.month, got.day, got.hour, got.minute) == expected
    assert got.tzinfo is timezone.utc


@pytest.mark.parametrize("stamp", ["", "   ", "not-a-date", "3-Sep-2026 17:58",
                                   "31-Feb-2026 10:00", "03-Xxx-2026 17:58",
                                   "03-Sep-2026", "03-Sep-2026 17:58:22"])
def test_index_time_rejects_anything_else(stamp):
    assert _parse_index_time(stamp) is None


def test_all_twelve_month_abbreviations_are_recognised():
    # %b is locale-dependent; the explicit table must cover the whole year.
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for i, mon in enumerate(months, start=1):
        assert _parse_index_time(f"01-{mon}-2026 00:00").month == i
        assert _parse_index_time(f"01-{mon.upper()}-2026 00:00").month == i


def test_a_failed_listing_clears_the_old_timestamps():
    # raise_for_status() on a 5xx must not leave the previous run's times behind.
    sess = _SwitchingSession([_Resp(YUM_HTML_DATED), _Resp("", 500)])
    idx = ProdPackageIndex(base_url=BASE, session=sess)

    idx.list_packages("rhel", "9", "yum")
    with pytest.raises(requests.HTTPError):
        idx.list_packages("rhel", "9", "yum")

    assert idx.published_at("rhel", "9", "yum", "aznfs-0.3.49-1.x86_64.rpm") is None


def test_unreachable_pmc_raises_instead_of_reporting_a_missing_repo():
    # Returning "missing" here is what recorded permanent known_unsupported
    # verdicts for distros whose repo existed all along.
    prod = ProdPackageIndex(session=_ExplodingSession())

    with pytest.raises(ProbeError):
        prod.resolve_repo("ubuntu", ["24.04"], "apt")


def test_unreachable_pmc_raises_instead_of_reporting_no_packages():
    prod = ProdPackageIndex(session=_ExplodingSession())

    with pytest.raises(ProbeError):
        prod.list_packages("ubuntu", "24.04", "apt")


def test_http_404_still_means_genuinely_absent():
    prod = ProdPackageIndex(session=_FakeSession({}))

    assert prod.resolve_repo("ubuntu", ["24.04"], "apt") is None
    assert prod.list_packages("ubuntu", "24.04", "apt") == []


def test_default_session_retries_transient_failures():
    retry = ProdPackageIndex()._session.get_adapter("https://").max_retries

    assert retry.total == 3
    assert 503 in retry.status_forcelist
