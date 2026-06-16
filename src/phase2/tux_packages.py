"""Read-only reader for the tux-dev package directory index.

Replaces the old PMC v4 ``get_package`` call: Gate 3 ("is AzNFS already
published?") now lists the autoindex of a repo's aznfs package directory on the
tux-dev browse server and returns the package filenames it finds. The browse
host is corp-network only.

Directory layout:
  apt: {base}/repos/<repo>/pool/main/a/aznfs/
  yum: {base}/yumrepos/<repo>/Packages/a/

Deliberately dumb: no gate logic (tests inject a fake with the same
``list_packages`` surface).
"""
from __future__ import annotations

import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

TUX_BASE = os.environ.get("TUX_DEV_REPO_BASE", "https://tux-devrepo.corp.microsoft.com").rstrip("/")

# Hyperlinks in a directory autoindex page, e.g. href="aznfs_0.3.2_amd64.deb".
_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
_AZNFS_VERSION_RE = re.compile(r"aznfs[_-]v?([0-9]+(?:\.[0-9]+)*)")


def _is_yum(family: str) -> bool:
    return (family or "").strip().lower() in {"yum", "rpm", "dnf"}


def aznfs_dir_url(repo: str, family: str, base: str = TUX_BASE) -> str:
    """URL of the directory whose autoindex lists the published aznfs packages."""
    repo = (repo or "").strip("/")
    if _is_yum(family):
        return f"{base}/yumrepos/{repo}/Packages/a/"
    return f"{base}/repos/{repo}/pool/main/a/aznfs/"


def version_from_filename(filename: str) -> str:
    """'aznfs_0.3.2_amd64.deb' / 'aznfs-0.3.2-1.x86_64.rpm' -> '0.3.2'."""
    m = _AZNFS_VERSION_RE.match(filename or "")
    return m.group(1) if m else ""


def file_arch(filename: str, family: str) -> str:
    """Architecture token embedded in a published aznfs filename.

    apt: 'aznfs_<ver>_<arch>.deb'        -> amd64|arm64
    yum: 'aznfs-<ver>-<rel>.<arch>.rpm'  -> x86_64|aarch64
    """
    name = filename or ""
    if _is_yum(family):
        m = re.match(r"aznfs-.+\.([a-z0-9_]+)\.rpm$", name)
    else:
        m = re.match(r"aznfs_[^_]+_([a-z0-9]+)\.deb$", name)
    return m.group(1) if m else ""


def normalize_arch(arch: str, family: str) -> str:
    """Map Phase 1's arch (x86_64|arm64) to the package-format naming."""
    a = (arch or "").strip().lower()
    if _is_yum(family):
        return {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(a, a)
    return {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(a, a)


def version_tuple(version: str) -> tuple[int, ...]:
    """Parse a dotted version into ints for numeric comparison ('0.3.10'->(0,3,10))."""
    parts: list[int] = []
    for token in str(version or "").split("."):
        m = re.match(r"\d+", token.strip())
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


class TuxPackageIndex:
    """Lists aznfs package filenames published in a tux-dev repo directory."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or TUX_BASE).rstrip("/")
        self.timeout = timeout if timeout is not None else int(os.environ.get("HTTP_TIMEOUT", "30"))
        self._session = session or requests.Session()

    def list_packages(self, repo: str, family: str) -> list[str]:
        """AzNFS package filenames published in this repo's directory (may be empty)."""
        url = aznfs_dir_url(repo, family, self.base_url)
        resp = self._session.get(url, timeout=self.timeout)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        ext = ".rpm" if _is_yum(family) else ".deb"
        names: list[str] = []
        for href in _HREF_RE.findall(resp.text):
            name = href.split("/")[-1].split("?")[0]
            if name.lower().startswith("aznfs") and name.lower().endswith(ext):
                names.append(name)
        return names

    def ping(self) -> bool:
        """Lightweight reachability probe (used by pre-flight if wired)."""
        try:
            resp = self._session.get(f"{self.base_url}/", timeout=self.timeout)
            return resp.ok or resp.status_code in (401, 403)
        except requests.RequestException as exc:
            logger.error("tux-dev browse server unreachable: %s", exc)
            return False


def from_env() -> TuxPackageIndex:
    return TuxPackageIndex()
