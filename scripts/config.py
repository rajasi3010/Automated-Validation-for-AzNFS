"""
Central configuration for the marketplace scanner.
All tuneable values live here; secrets come from environment variables.
"""

import os

# ---------------------------------------------------------------------------
# Azure regions to scan
# ---------------------------------------------------------------------------
REGIONS = [
    "westus3",
    "westus2",
    "eastus2",
    "eastus",
    "southeastasia",
]

# ---------------------------------------------------------------------------
# Publishers to scan
# ---------------------------------------------------------------------------
PUBLISHERS = [
    "Canonical",
    "RedHat",
    "SUSE",
    "Debian",
]

# ---------------------------------------------------------------------------
# Azure credentials  (set via environment; never hardcode)
# For local dev:   run  `az login`  — DefaultAzureCredential picks it up.
# For GH Actions:  inject AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / AZURE_TENANT_ID
#                  as repository secrets and DefaultAzureCredential uses them.
# ---------------------------------------------------------------------------
AZURE_SUBSCRIPTION_ID: str = os.environ["AZURE_SUBSCRIPTION_ID"]

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
