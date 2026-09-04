"""The distro releases AzNFS targets - the single source of truth for scope.

Anything outside this matrix is discovered and tracked, but never validated: a
missing AzNFS package there is expected, not a finding. Keeping it here (rather
than in ``src/phase2``) lets Phase 1's reporting and Phase 2's gates share one
definition instead of drifting apart.

Mirrors the supported list in the AZNFS-mount README.
"""

import re

SUPPORTED_UBUNTU = {"18.04", "20.04", "22.04", "24.04", "26.04"}
SUPPORTED_RHEL = {"7", "8", "9", "10"}
SUPPORTED_ROCKY = {"8", "9"}
SUPPORTED_SLES = {"15", "16"}

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
