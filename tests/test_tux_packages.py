from __future__ import annotations

import requests

from src.phase2.tux_packages import TuxPackageIndex, aznfs_dir_url

BASE = "https://tux-devrepo.corp.microsoft.com"


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


# A real yum autoindex page (cbl-mariner Packages/a/) with NO aznfs package.
YUM_HTML_NO_AZNFS = """
<a href="../">../</a>
<a href="acl-debuginfo-2.2.53-5.cm2.x86_64.rpm">acl-debuginfo-2.2.53-5.cm2.x86_64.rpm</a>
<a href="alsa-lib-debuginfo-1.2.2-2.cm2.x86_64.rpm">alsa-lib-debuginfo-1.2.2-2.cm2.x86_64.rpm</a>
<a href="apparmor-debuginfo-2.13-15.cm2.x86_64.rpm">apparmor-debuginfo-2.13-15.cm2.x86_64.rpm</a>
<a href="azure-storage-cpp-debuginfo-7.3.0-2.cm2.x86_64.rpm">azure-storage-cpp-debuginfo-7.3.0-2.cm2.x86_64.rpm</a>
"""

YUM_HTML_WITH_AZNFS = """
<a href="../">../</a>
<a href="acl-debuginfo-2.2.53-5.cm2.x86_64.rpm">acl-debuginfo-2.2.53-5.cm2.x86_64.rpm</a>
<a href="aznfs-0.3.2-1.cm2.x86_64.rpm">aznfs-0.3.2-1.cm2.x86_64.rpm</a>
"""

APT_HTML_WITH_AZNFS = """
<a href="../">../</a>
<a href="aznfs_0.3.2_amd64.deb">aznfs_0.3.2_amd64.deb</a>
<a href="aznfs_0.3.2_arm64.deb">aznfs_0.3.2_arm64.deb</a>
"""


def test_yum_url_uses_packages_a_directory():
    repo = "cbl-mariner-2.0-preview-base-debuginfo-x86_64"
    assert aznfs_dir_url(repo, "yum", BASE) == f"{BASE}/yumrepos/{repo}/Packages/a/"


def test_apt_url_uses_pool_main_a_aznfs_directory():
    repo = "microsoft-ubuntu-noble"
    assert aznfs_dir_url(repo, "apt", BASE) == f"{BASE}/repos/{repo}/pool/main/a/aznfs/"


def test_yum_listing_without_aznfs_returns_empty():
    # The screenshot page: many *-debuginfo rpms, none starting with 'aznfs'.
    repo = "cbl-mariner-2.0-preview-base-debuginfo-x86_64"
    url = aznfs_dir_url(repo, "yum", BASE)
    sess = _FakeSession({url: _Resp(YUM_HTML_NO_AZNFS)})
    index = TuxPackageIndex(base_url=BASE, session=sess)

    assert index.list_packages(repo, "yum") == []          # Gate 3 -> "no"
    assert sess.requested == [url]


def test_yum_listing_with_aznfs_returns_package():
    repo = "microsoft-rhel9"
    url = aznfs_dir_url(repo, "yum", BASE)
    sess = _FakeSession({url: _Resp(YUM_HTML_WITH_AZNFS)})
    index = TuxPackageIndex(base_url=BASE, session=sess)

    assert index.list_packages(repo, "yum") == ["aznfs-0.3.2-1.cm2.x86_64.rpm"]


def test_apt_listing_with_aznfs_returns_packages():
    repo = "microsoft-ubuntu-noble"
    url = aznfs_dir_url(repo, "apt", BASE)
    sess = _FakeSession({url: _Resp(APT_HTML_WITH_AZNFS)})
    index = TuxPackageIndex(base_url=BASE, session=sess)

    assert index.list_packages(repo, "apt") == [
        "aznfs_0.3.2_amd64.deb",
        "aznfs_0.3.2_arm64.deb",
    ]


def test_missing_directory_404_returns_empty():
    repo = "microsoft-ubuntu-noble"
    sess = _FakeSession({})  # everything 404s
    index = TuxPackageIndex(base_url=BASE, session=sess)

    assert index.list_packages(repo, "apt") == []
