"""Fetches and caches the tuxdev directory listings."""
from __future__ import annotations
import re
from dataclasses import dataclass

import requests

APT_URL = "https://tux-devrepo.corp.microsoft.com/repos/"
YUM_URL = "https://tux-devrepo.corp.microsoft.com/yumrepos/"

_LINK_RE = re.compile(r'href="([^"/?]+)/"')


def parse_listing(html: str) -> set[str]:
    return {m.group(1) for m in _LINK_RE.finditer(html) if not m.group(1).startswith(".")}


@dataclass(frozen=True)
class RepoIndex:
    apt: frozenset[str]
    yum: frozenset[str]

    def __getitem__(self, key: str) -> frozenset[str]:
        return self.apt if key == "apt" else self.yum


def fetch(apt_url: str = APT_URL, yum_url: str = YUM_URL, timeout: int = 30) -> RepoIndex:
    apt = parse_listing(requests.get(apt_url, timeout=timeout).text)
    yum = parse_listing(requests.get(yum_url, timeout=timeout).text)
    return RepoIndex(apt=frozenset(apt), yum=frozenset(yum))
