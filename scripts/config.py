"""
Central configuration for the marketplace scanner.
All tuneable values live here; secrets come from environment variables.
"""

import os

# ---------------------------------------------------------------------------
# Azure regions to scan
# ---------------------------------------------------------------------------
# AzNFS is currently validated only in eastus; expand this list if the
# project starts publishing per-region builds.
REGIONS = [
    "eastus",
]

# ---------------------------------------------------------------------------
# Publishers to scan
# ---------------------------------------------------------------------------
PUBLISHERS = [
    "Canonical",
    "RedHat",
    "SUSE",
    "Debian",
    # Rocky Linux images (publisher commonly resf in Marketplace).
    "resf",
    # Microsoft's own distro: Azure Linux 3.x and CBL-Mariner 1.x/2.x.
    "MicrosoftCBLMariner",
]
# NOTE: "OpenLogic" (the CentOS publisher) is intentionally NOT scanned. CentOS
# 7/8 are EOL: the yum mirrors baked into those marketplace images
# (mirrorlist.centos.org, olcentgbl.trafficmanager.net) are decommissioned, so
# AzNFS dependencies cannot be installed. CentOS is removed from the pipeline
# (see EXCLUDED_DISTRO_PREFIXES below, which also drops any CentOS rows still in
# the cached DB).


# Offers to skip during the scan. Some Canonical Ubuntu offers are PRIVATE /
# restricted-audience plans (e.g. the "Pro - Advanced SLA" offers
# 0001-com-ubuntu-pro-advanced-sla-airdig / -ca / -sk). They appear in the
# marketplace listing but the subscription is not entitled to deploy them, so
# Phase 3 fails at provisioning with "Offer ... not found / restricted
# audience". The same Ubuntu releases are available from PUBLIC offers
# (0001-com-ubuntu-server-*, ubuntu-24_04-lts, ubuntu-26_04-lts, ...), so
# dropping the restricted ones keeps full version coverage with deployable
# images. Matched case-insensitively as substrings of the offer name. Override
# with EXCLUDED_OFFER_SUBSTRINGS (comma-separated) if needed.
EXCLUDED_OFFER_SUBSTRINGS: list[str] = [
    s.strip().lower()
    for s in os.environ.get("EXCLUDED_OFFER_SUBSTRINGS", "advanced-sla").split(",")
    if s.strip()
]

# Distro families to drop from the pipeline entirely, matched case-insensitively
# as a prefix of the derived ``distro_label`` (e.g. "centos" drops "CentOS 7" and
# "CentOS 8"). Applied to BOTH the new/updated delta hand-off and the
# EMIT_BACKLOG feed, so excluded distros never reach Phase 2/3 even if rows for
# them already exist in the cached DB (or get reset to 'unknown'). CentOS is
# excluded because it is EOL (its in-image yum mirrors are gone). Override with
# EXCLUDED_DISTRO_PREFIXES (comma-separated) if needed.
EXCLUDED_DISTRO_PREFIXES: list[str] = [
    s.strip().lower()
    for s in os.environ.get("EXCLUDED_DISTRO_PREFIXES", "centos").split(",")
    if s.strip()
]



# ---------------------------------------------------------------------------
# Azure credentials  (set via environment; never hardcode)
# For local dev:   run `az login` and DefaultAzureCredential picks it up.
# For the Azure VM runner: prefer Managed Identity.
#   - System-assigned MI: only AZURE_SUBSCRIPTION_ID is required.
#   - User-assigned MI: set AZURE_MANAGED_IDENTITY_CLIENT_ID as well.
# ---------------------------------------------------------------------------
AZURE_SUBSCRIPTION_ID: str = os.environ["AZURE_SUBSCRIPTION_ID"]
AZURE_MANAGED_IDENTITY_CLIENT_ID: str | None = os.environ.get(
    "AZURE_MANAGED_IDENTITY_CLIENT_ID"
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)

DB_PATH: str = os.environ.get(
    "DB_PATH", os.path.join(_PROJECT_ROOT, "marketplace.db")
)

SCHEMA_PATH: str = os.path.join(_PROJECT_ROOT, "db", "schema.sql")

OUTPUT_DIR: str = os.environ.get(
    "OUTPUT_DIR", os.path.join(_PROJECT_ROOT, "output")
)

OUTPUT_JSON: str = os.path.join(OUTPUT_DIR, "needs_validation.json")
# needs_validation.json is the ONLY artifact Phase 1 writes. The distro-level
# rollup (the de-duplicated OS-release view) is computed in memory for the
# new-release diff and the monthly digest; it is not persisted to a file.

# ---------------------------------------------------------------------------
# Notifications  (Azure Communication Services Email)
# ---------------------------------------------------------------------------
# ACS_ENDPOINT example: https://<resource-name>.communication.azure.com
# ACS_SENDER  example: DoNotReply@<verified-domain>.azurecomm.net
ACS_ENDPOINT: str = os.environ.get("ACS_ENDPOINT", "")
ACS_SENDER: str = os.environ.get("ACS_SENDER", "")

# Comma-separated recipient list (env override supported).
_DEFAULT_RECIPIENTS = (
    "psachdeva@microsoft.com,"
    "rajasimandal@microsoft.com,"
    "Shyam.Prasad@microsoft.com,"
    "vaibsharma@microsoft.com,"
    "t-arohi@microsoft.com"
)
NOTIFY_RECIPIENTS: list[str] = [
    addr.strip()
    for addr in os.environ.get("NOTIFY_RECIPIENTS", _DEFAULT_RECIPIENTS).split(",")
    if addr.strip()
]
