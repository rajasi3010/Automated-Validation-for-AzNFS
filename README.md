# Marketplace Distro Scanner (Phase 1)

This repository contains the Phase 1 pipeline to discover Azure Marketplace VM images, track them in a local SQLite database, and emit a JSON list of newly discovered images that require validation.

## Goal

Build a one-stop Python script that:
1. Scans Azure Marketplace images for selected regions/publishers.
2. Compares scan results with a local SQLite database.
3. Adds new images with `validated=unknown`.
4. Exports only newly discovered images to `output/needs_validation.json`.
5. Sends email notifications when run in GitHub Actions and new images are found.

## Current Scope

- Regions:
  - `westus3`
  - `westus2`
  - `eastus2`
  - `eastus`
  - `southeastasia`
- Publishers (initial list):
  - `Canonical`
  - `RedHat`
  - `SUSE`
  - `Debian`

## Repository Structure

- `.github/workflows/scan-marketplace.yml` - scheduled/manual automation and email notification
- `db/schema.sql` - database schema source of truth
- `scripts/config.py` - region/publisher config and paths
- `scripts/azure_client.py` - Azure SDK wrappers
- `scripts/db_manager.py` - SQLite operations
- `scripts/scan_marketplace.py` - orchestration entrypoint
- `output/` - generated JSON output (not committed)

## Data Model

See `db/schema.sql`.

Highlights:
- `image` column maps to Azure SDK `offer`.
- `sku` is stored explicitly.
- `validated` lifecycle values:
  - `unknown`
  - `known_supported`
  - `known_unsupported`

## Setup (Local Linux/WSL)

1. Create/activate virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Authenticate:
   - `az login`
4. Set environment variable:
   - `AZURE_SUBSCRIPTION_ID=<subscription-guid>`
5. Run scan:
   - `cd scripts`
   - `python scan_marketplace.py`

## Output Contract

`output/needs_validation.json` contains only newly discovered images with fields including:
- `publisher`
- `image` (offer)
- `sku`
- `version`
- `region`
- `date_added` (date found)

## GitHub Actions + Email

Workflow: `.github/workflows/scan-marketplace.yml`

Required repository secrets:
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_CLIENT_ID`
- `AZURE_CLIENT_SECRET`
- `AZURE_TENANT_ID`
- `MAIL_SERVER`
- `MAIL_PORT`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_RECIPIENT`

Email contains a table with:
- Publisher
- Image (Offer)
- Version
- Region
- SKU
- Date Found

## Notes

- Database state is preserved between GitHub Actions runs using cache.
- First run initializes database and marks discovered images as `unknown`.
- Later runs only emit newly discovered entries.
