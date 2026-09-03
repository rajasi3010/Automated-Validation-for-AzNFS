"""Which distro releases are worth validating, and which are only worth tracking.

Two classes are excluded from validation but still discovered and reported, so
nobody has to wonder why they vanished:

* **eol**     - the vendor stopped standard support, so a missing AzNFS package
                is expected rather than a finding.
* **interim** - Ubuntu non-LTS releases. They live ~9 months and AzNFS publishes
                for LTS only, so validating them just manufactures noise.

Kept free of `config`/Azure imports so Phase 1, Phase 2 and the reporting tools
can all use it.
"""

import os
import re

ACTIVE = "active"
EOL = "eol"
INTERIM = "interim"

# Vendor end-of-standard-support. Extended/ESM programmes are deliberately NOT
# counted as supported: AzNFS does not publish for them either.
EOL_RELEASES = {
    "Ubuntu 14.04": "Ubuntu standard support ended 2019-04 (ESM only)",
    "Ubuntu 16.04": "Ubuntu standard support ended 2021-04 (ESM only)",
    "Debian 10": "Debian LTS ended 2024-06",
    "Debian 11": "Debian LTS ended 2026-08",
    "SLES 12": "SUSE general support ended 2024-10 (LTSS only)",
}

_UBUNTU_RELEASE_RE = re.compile(r"^Ubuntu (\d{2})\.(\d{2})$")


def _extra_eol() -> dict[str, str]:
    """Labels added through EXTRA_EOL_DISTROS, so a release can be retired
    without a code change."""
    raw = os.environ.get("EXTRA_EOL_DISTROS", "")
    return {label.strip(): "declared EOL via EXTRA_EOL_DISTROS"
            for label in raw.split(",") if label.strip()}


def is_interim_ubuntu(distro_label: str) -> bool:
    """True for Ubuntu non-LTS releases: LTS is an even year with an .04 month."""
    match = _UBUNTU_RELEASE_RE.match(distro_label.strip())
    if not match:
        return False
    year, month = int(match.group(1)), match.group(2)
    return not (month == "04" and year % 2 == 0)


def lifecycle(distro_label: str) -> str:
    """Return ``active`` / ``eol`` / ``interim`` for a distro release label."""
    label = (distro_label or "").strip()
    if label in EOL_RELEASES or label in _extra_eol():
        return EOL
    if is_interim_ubuntu(label):
        return INTERIM
    return ACTIVE


def exclusion_reason(distro_label: str) -> str:
    """Why this release is not validated, or '' when it is."""
    label = (distro_label or "").strip()
    state = lifecycle(label)
    if state == EOL:
        return EOL_RELEASES.get(label) or _extra_eol().get(label, "end of life")
    if state == INTERIM:
        return "Ubuntu interim (non-LTS) release; AzNFS publishes for LTS only"
    return ""


def enforced() -> bool:
    """Set LIFECYCLE_ENFORCE=0 to validate everything again (e.g. a one-off sweep)."""
    return os.environ.get("LIFECYCLE_ENFORCE", "1").strip() not in ("0", "false", "no")


def is_validation_target(distro_label: str) -> bool:
    """False for releases that should be tracked and reported but never validated."""
    if not enforced():
        return True
    return lifecycle(distro_label) == ACTIVE
