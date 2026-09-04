"""Read-only client for the PUBLIC PMC prod content server.

Phase 2 runs against ``packages.microsoft.com`` only (no PMC API, no tux-dev,
no corp proxy). PMC prod is *version-indexed*::

    https://packages.microsoft.com/<distro>/<version>/prod/

so the image's ``distro_label`` ("Ubuntu 22.04", "RHEL 9.0") maps straight to a
URL with no codename (jammy/noble) lookup. An ``x`` / ``x.0`` release is served
at both ``<major>`` and ``<major>.0``; every other release resolves only to
itself, so rhel/8.1 never falls back to rhel/8.

aznfs package directory layout (anonymous HTTP, autoindex pages):
  apt: {base}/<distro>/<version>/prod/pool/main/a/aznfs/   -> aznfs_<ver>_<arch>.deb
  yum: {base}/<distro>/<version>/prod/Packages/a/          -> aznfs-<ver>-1.<arch>.rpm

Deliberately dumb: no gate logic lives here (tests inject a fake exposing the
same ``resolve_repo`` / ``list_packages`` surface).
"""
from __future__ import annotations

import functools
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

# ``or`` (not the get-default) so an env var that is SET BUT EMPTY -- which is
# how an unset GitHub Actions repo variable arrives, e.g. PROD_REPO_BASE: '' --
# falls back to the default instead of yielding an empty base URL.
PROD_BASE = (os.environ.get("PROD_REPO_BASE") or "https://packages.microsoft.com").rstrip("/")

_MAP_PATH = Path(__file__).with_name("distro_map.yaml")

# Hyperlinks in a directory autoindex page, e.g. href="aznfs_0.3.2_amd64.deb".
_HREF_RE = re.compile(r"""href=["']([^"'?]+)["']""", re.IGNORECASE)
# Same anchor plus the autoindex's date column: `</a>   03-Sep-2026 17:58  9.0 MB`.
_INDEX_ENTRY_RE = re.compile(
    r"""href=["']([^"'?]+)["'][^>]*>.*?</a>\s+"""
    r"(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2})",
    re.IGNORECASE,
)
_AZNFS_VERSION_RE = re.compile(r"aznfs[_-]v?([0-9]+(?:\.[0-9]+)*)")
_VER_RE = re.compile(r"(\d+)(?:\.(\d+))?")

_INDEX_TIME_RE = re.compile(r"(\d{2})-([A-Za-z]{3})-(\d{4})\s+(\d{2}):(\d{2})$")
_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _parse_index_time(stamp: str) -> datetime | None:
    """Parse an autoindex date like ``03-Sep-2026 17:58`` as UTC.

    Month names are matched against an explicit table rather than ``%b``, which
    is locale-dependent: under a non-English LC_TIME every PMC timestamp would
    silently fail to parse and ordering would quietly fall back to version order.
    """
    m = _INDEX_TIME_RE.match((stamp or "").strip())
    if not m:
        return None
    month = _MONTHS.get(m.group(2).lower())
    if month is None:
        return None
    try:
        return datetime(int(m.group(3)), month, int(m.group(1)),
                        int(m.group(4)), int(m.group(5)), tzinfo=timezone.utc)
    except ValueError:  # e.g. 31-Feb
        return None


def _is_yum(family: str) -> bool:
    return (family or "").strip().lower() in {"yum", "rpm", "dnf"}


# ---------------------------------------------------------------------------
# distro_label / publisher -> PMC <distro> path segment + index kind
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _load_map(path: str = str(_MAP_PATH)) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:  # pragma: no cover - config is shipped with the repo
        return {}


def distro_segment(distro_label: str, publisher: str = "") -> str | None:
    """PMC ``<distro>`` path segment for an image (e.g. "Ubuntu 22.04" -> "ubuntu").

    A ``distro_label`` keyword match wins first (so openSUSE/Alma/Rocky resolve
    regardless of the marketplace publisher); otherwise fall back to the
    publisher map. Returns ``None`` when nothing matches (unmapped distro).
    """
    cfg = _load_map()
    s = (distro_label or "").strip().lower()
    for entry in cfg.get("labels", []):
        if len(entry) >= 2 and entry[0] and str(entry[0]).lower() in s:
            return str(entry[1])
    pub = (publisher or "").strip().lower()
    rule = cfg.get("publishers", {}).get(pub)
    if rule:
        return rule.get("distro")
    return None


def index_kind(distro_label: str, publisher: str = "", family: str = "") -> str:
    """Package index kind ('apt'|'yum'). The image's ``family`` wins when set."""
    if family:
        return "yum" if _is_yum(family) else "apt"
    cfg = _load_map()
    s = (distro_label or "").strip().lower()
    for entry in cfg.get("labels", []):
        if len(entry) >= 3 and entry[0] and str(entry[0]).lower() in s:
            return str(entry[2])
    rule = cfg.get("publishers", {}).get((publisher or "").strip().lower())
    return (rule or {}).get("index", "apt")


def version_candidates(distro_label: str, fallback_version: str = "") -> list[str]:
    """Ordered PMC version segments to try for a distro_label.

    An ``x`` / ``x.0`` release is served at both paths -- rhel/8 and rhel/8.0 are
    the same pocket -- so both are tried. Every other release is tried only as
    itself: rhel/8.1 must never resolve to rhel/8, and ubuntu/22.04 must never
    resolve to ubuntu/22, because those are different releases.

    Falls back to the marketplace ``version`` when the label has no number.
    """
    m = _VER_RE.search(distro_label or "") or _VER_RE.search(fallback_version or "")
    if not m:
        return []
    major, minor = m.group(1), m.group(2)
    if minor is None or minor == "0":
        return [major, f"{major}.0"]
    return [f"{major}.{minor}"]


# ---------------------------------------------------------------------------
# PMC prod URL builders
# ---------------------------------------------------------------------------
def repo_base_url(distro: str, version: str, base: str = PROD_BASE) -> str:
    """The prod pocket root, e.g. .../ubuntu/22.04/prod/ . A 200 here == repo exists."""
    return f"{base.rstrip('/')}/{distro}/{version}/prod/"


def aznfs_dir_url(distro: str, version: str, family: str, base: str = PROD_BASE) -> str:
    """The directory whose autoindex lists the published aznfs packages."""
    root = repo_base_url(distro, version, base)
    if _is_yum(family):
        return root + "Packages/a/"
    return root + "pool/main/a/aznfs/"


# ---------------------------------------------------------------------------
# aznfs filename parsing (unchanged: identical filename formats on prod)
# ---------------------------------------------------------------------------
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
    """Parse a dotted version into ints for NUMERIC comparison ('0.3.10'->(0,3,10)).

    Prod lists e.g. aznfs-0.3.9 and aznfs-3.0.18 side by side, where a string
    compare would wrongly rank 0.3.9 above 0.3.18 -- always compare with this.
    """
    parts: list[int] = []
    for token in str(version or "").split("."):
        m = re.match(r"\d+", token.strip())
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


# AzNFS line under test. PMC prod also carries unrelated 0.0.x/0.1.x/0.2.x/1.x/
# 2.x/3.x aznfs lineages; Phase 2 only ever tracks the 0.3.x series, so every
# published version is filtered through ``in_series`` before the numeric-max
# patch is taken (otherwise the latest would jump to e.g. 3.0.18).
AZNFS_SERIES = "0.3"


def in_series(version: str, series: str = AZNFS_SERIES) -> bool:
    """True when ``version`` is in the tracked AzNFS series (matches major.minor).

    '0.3.458' and '0.3.9' are in series '0.3'; '3.0.18', '0.2.3' and '1.0.0'
    are not. Comparison is numeric so '0.30.x' never masquerades as '0.3'.
    """
    want = version_tuple(series)
    got = version_tuple(version)
    return len(got) >= len(want) and got[: len(want)] == want


class ProdPackageIndex:
    """Lists aznfs package filenames published under a PMC prod version path."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = (base_url or PROD_BASE).rstrip("/")
        # ``or "30"`` guards against HTTP_TIMEOUT being set-but-empty in CI
        # (an unset repo variable arrives as ''), which int('') would reject.
        self.timeout = timeout if timeout is not None else int(os.environ.get("HTTP_TIMEOUT") or "30")
        self._session = session or requests.Session()
        # aznfs dir url -> {filename: autoindex timestamp}. Replaced wholesale on
        # every listing so a directory's cache never outlives what it now serves.
        self._published_at: dict[str, dict[str, datetime]] = {}

    def _ok(self, url: str) -> bool:
        try:
            resp = self._session.get(url, timeout=self.timeout)
            logger.debug("Gate 1 probe: GET %s -> HTTP %s", url, resp.status_code)
            return 200 <= resp.status_code < 300
        except requests.RequestException as exc:
            logger.warning("GET %s failed: %s", url, exc)
            return False

    def resolve_repo(self, distro: str, candidates: list[str], family: str = "") -> str | None:
        """Return the first ``candidates`` version whose prod pocket exists (200).

        This is the "does a prod repo exist for this distro release?" check;
        ``family`` is unused for the existence probe but accepted for symmetry.
        Returns the resolved version string, or ``None`` when none exist.
        """
        for version in candidates:
            if self._ok(repo_base_url(distro, version, self.base_url)):
                logger.debug("resolve_repo(%s): matched version %s of candidates %s",
                             distro, version, candidates)
                return version
        logger.debug("resolve_repo(%s): no prod pocket for any of %s", distro, candidates)
        return None

    def list_packages(self, distro: str, version: str, family: str) -> list[str]:
        """aznfs package filenames published under this prod path (may be empty)."""
        url = aznfs_dir_url(distro, version, family, self.base_url)
        # Drop the previous listing's timestamps up front so NO exit path -- 404,
        # network error, raise_for_status on a 5xx -- can leave stale ones behind.
        self._published_at.pop(url, None)
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("GET %s failed: %s", url, exc)
            return []
        if resp.status_code == 404:
            logger.debug("Gate 2 listing: GET %s -> HTTP 404 (no aznfs dir)", url)
            return []
        resp.raise_for_status()
        ext = ".rpm" if _is_yum(family) else ".deb"
        names: list[str] = []
        stamps: dict[str, datetime] = {}
        for href, stamp in _INDEX_ENTRY_RE.findall(resp.text):
            name = href.split("/")[-1].split("?")[0]
            published = _parse_index_time(stamp)
            if published is None:
                logger.debug("Unparseable PMC timestamp %r for %s", stamp, name)
            else:
                stamps[name] = published
        self._published_at[url] = stamps
        for href in _HREF_RE.findall(resp.text):
            name = href.split("/")[-1].split("?")[0]
            if name.lower().startswith("aznfs") and name.lower().endswith(ext):
                names.append(name)
        logger.debug("Gate 2 listing: GET %s -> HTTP %s, %d aznfs%s file(s)",
                     url, resp.status_code, len(names), ext)
        return names

    def published_at(self, distro: str, version: str, family: str,
                     filename: str) -> datetime | None:
        """When PMC published ``filename``, or None if the index gave no date.

        Only meaningful after ``list_packages`` has read that directory; the
        autoindex is the only place PMC exposes a publication time.
        """
        url = aznfs_dir_url(distro, version, family, self.base_url)
        return self._published_at.get(url, {}).get(filename)

    def ping(self) -> bool:
        """Lightweight reachability probe (used by pre-flight if wired)."""
        try:
            resp = self._session.get(f"{self.base_url}/", timeout=self.timeout)
            return resp.ok or resp.status_code in (401, 403)
        except requests.RequestException as exc:
            logger.error("PMC prod server unreachable: %s", exc)
            return False


def from_env() -> ProdPackageIndex:
    return ProdPackageIndex()
