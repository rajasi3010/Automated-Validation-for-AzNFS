"""The distro releases AzNFS targets - the single source of truth for scope.

Mirrors the publish targets in AZNFS-mount/packages.csv, minus the EOL CentOS
entries (CentOS-7.0 / CentOS-8.0), which Phase 1 drops upstream anyway.

Phase 1 applies this to its Phase 2 hand-off, so anything outside the matrix is
still discovered, stored and reported -- just never validated, because a missing
AzNFS package there is expected rather than a finding. Phase 2 then validates
whatever it is handed and does not re-judge scope.
"""

import re

# packages.csv column 1, verbatim, so this can be diffed against the source.
PUBLISH_TARGETS = {
    "Ubuntu": {"18.04", "20.04", "22.04", "24.04", "26.04"},
    "RHEL": {"7.0", "7.3", "8.0", "9.0", "10.0"},
    "Rocky": {"8.0", "9.0"},
    "SUSE": {"15", "16"},
}


def _accepted_versions(family: str) -> set[str]:
    """Publish targets plus their bare-major spelling.

    The marketplace labels the same release either way ("RHEL 8" and "RHEL 8.0"
    are both the 8.0 target), so both forms are accepted. A different minor is
    NOT: 8.1 is its own release and AzNFS publishes nothing for it.
    """
    accepted = set()
    for target in PUBLISH_TARGETS[family]:
        accepted.add(target)
        major, _, minor = target.partition(".")
        if minor == "0":
            accepted.add(major)
    return accepted


SUPPORTED_UBUNTU = _accepted_versions("Ubuntu")   # {"18.04", ... } exact releases
SUPPORTED_RHEL = _accepted_versions("RHEL")       # {"7", "7.0", "7.3", "8", "8.0", ...}
SUPPORTED_ROCKY = _accepted_versions("Rocky")     # {"8", "8.0", "9", "9.0"}
SUPPORTED_SLES = _accepted_versions("SUSE")       # {"15", "16"}

OUT_OF_MATRIX_REASON = "outside the AzNFS support matrix"


def _label_version(label: str) -> str:
    major, minor = major_minor(label)
    if not major:
        return ""
    return f"{major}.{minor}" if minor else major


def major_minor(label: str) -> tuple[str, str]:
    m = re.search(r"(10|\d+)(?:\.(\d+))?", label or "")
    if not m:
        return "", ""
    return m.group(1), m.group(2) or ""


def is_supported_distro(label: str) -> bool:
    """True when AzNFS publishes for exactly this distro release.

    A different minor of a supported major is NOT in scope: AzNFS publishes to
    rhel/8.0, and rhel/8.1 is a separate pocket carrying no AzNFS. Phase 2 skips
    those; a manual run can still force one.
    """
    s = (label or "").strip().lower()
    ver = _label_version(s)
    if not ver:
        return False

    if "ubuntu" in s:
        return ver in SUPPORTED_UBUNTU
    if "rhel" in s or "redhat" in s or "red hat" in s:
        return ver in SUPPORTED_RHEL
    if "rocky" in s:
        return ver in SUPPORTED_ROCKY
    if "sles" in s or "suse" in s:
        return ver in SUPPORTED_SLES
    return False
