#!/usr/bin/env python3
"""
scan_marketplace.py — Phase 1 entry point.

Workflow
--------
1. Ensure the local SQLite database exists (create from schema if not).
2. Authenticate to Azure and build a Compute client.
3. For every configured region × publisher, crawl offers → SKUs → versions.
4. For each version:
     - If the (publisher, offer, sku, version, region) tuple is NOT in the DB
       → insert it as validated='unknown' and flag it for the output JSON.
     - If it IS in the DB → update last_checked only; no output.
5. Write all flagged images to output/needs_validation.json.
6. Exit with code 0 when there are no new images, or 1 when new images were found
   so that the GitHub Actions step can branch on the result.

Running locally
---------------
  export AZURE_SUBSCRIPTION_ID=<your-sub-id>
  az login          # DefaultAzureCredential picks this up
  python scan_marketplace.py
"""

import json
import logging
import os
import sys

import config
import azure_client
import db_manager

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    # ------------------------------------------------------------------
    # Step 1 — Initialise database
    # ------------------------------------------------------------------
    logger.info("Initialising database at: %s", config.DB_PATH)
    db_manager.initialize(config.DB_PATH, config.SCHEMA_PATH)

    # ------------------------------------------------------------------
    # Step 2 — Azure client
    # ------------------------------------------------------------------
    logger.info("Building Azure Compute client …")
    client = azure_client.get_compute_client()

    # ------------------------------------------------------------------
    # Step 3+4 — Scan and compare
    # ------------------------------------------------------------------
    new_images: list[dict] = []

    for region in config.REGIONS:
        logger.info("=== Region: %s ===", region)

        for publisher in config.PUBLISHERS:
            logger.info("  Publisher: %s", publisher)
            offers = azure_client.list_offers(client, region, publisher)

            if not offers:
                logger.info("    No offers found — skipping.")
                continue

            for offer in offers:
                skus = azure_client.list_skus(client, region, publisher, offer)

                for sku in skus:
                    versions = azure_client.list_versions(
                        client, region, publisher, offer, sku
                    )

                    for version in versions:
                        is_new = db_manager.check_and_upsert(
                            config.DB_PATH,
                            publisher,
                            offer,
                            sku,
                            version,
                            region,
                        )
                        if is_new:
                            record = db_manager.get_image_record(
                                config.DB_PATH,
                                publisher,
                                offer,
                                sku,
                                version,
                                region,
                            )
                            new_images.append(record)

    # ------------------------------------------------------------------
    # Step 5 — Write JSON output
    # ------------------------------------------------------------------
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    with open(config.OUTPUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(new_images, fh, indent=2)

    # ------------------------------------------------------------------
    # Step 6 — Exit code
    # ------------------------------------------------------------------
    if new_images:
        logger.info(
            "Scan complete: %d new image(s) found. Output written to %s",
            len(new_images),
            config.OUTPUT_JSON,
        )
        return 1  # Signals GH Actions to send email notification

    logger.info("Scan complete: no new images found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
