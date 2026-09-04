"""The distro releases AzNFS targets - the single source of truth for scope.

Mirrors the publish targets in AZNFS-mount/packages.csv, minus the EOL CentOS
entries (CentOS-7.0 / CentOS-8.0), which Phase 1 drops upstream anyway.

Anything outside this matrix is discovered and tracked, but never validated: a
missing AzNFS package there is expected, not a finding. Keeping it here (rather
than in ``src/phase2``) lets Phase 1's reporting and Phase 2's gates share one
definition instead of drifting apart.
"""

import re

# packages.csv column 1, verbatim, so this can be diffed against the source.
# RHEL and Rocky publish per minor (RHEL-8.0, Rocky-9.0) but the repo behind it
# serves the whole major, so those families are matched on the major below.
PUBLISH_TARGETS = {
    "Ubuntu": {"18.04", "20.04", "22.04", "24.04", "26.04"},
    "RHEL": {"7.0", "7.3", "8.0", "9.0", "10.0"},
    "Rocky": {"8.0", "9.0"},
    "SUSE": {"15", "16"},
}


def _majors(family: str) -> set[str]:
    return {target.split(".")[0] for target in PUBLISH_TARGETS[family]}


SUPPORTED_UBUNTU = set(PUBLISH_TARGETS["Ubuntu"])   # matched as major.minor
SUPPORTED_RHEL = _majors("RHEL")                    # {"7", "8", "9", "10"}
SUPPORTED_ROCKY = _majors("Rocky")                  # {"8", "9"}
SUPPORTED_SLES = _majors("SUSE")                    # {"15", "16"}

OUT_OF_MATRIX_REASON = "outside the AzNFS support matrix"


def major_minor(label: str) -> tuple[str, str]:
    m = re.search(r"(10|\d+)(?:\.(\d+))?", label or "")
    if not m:
        return "", ""
    return m.group(1), m.group(2) or ""


def is_supported_distro(label: str) -> bool:
    """True when AzNFS targets this distro release."""
    s = (label or "").strip().lower()
    major, minor = major_minor(s)

    if "ubuntu" in s:
        ver = f"{major}.{minor}" if major and minor else ""
        return ver in SUPPORTED_UBUNTU
    if "rhel" in s or "redhat" in s or "red hat" in s:
        return major in SUPPORTED_RHEL
    if "rocky" in s:
        return major in SUPPORTED_ROCKY
    if "sles" in s or "suse" in s:
        return major in SUPPORTED_SLES
    return False
