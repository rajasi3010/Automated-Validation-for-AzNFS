"""
Thin wrappers around the Azure Compute SDK for marketplace image discovery.

Each function catches per-call exceptions and logs a warning so that a single
unavailable publisher/offer/sku does not abort the entire scan.
"""

import logging
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

import config

logger = logging.getLogger(__name__)


def get_compute_client() -> ComputeManagementClient:
    """Return an authenticated ComputeManagementClient using DefaultAzureCredential.

    Local dev  : run `az login` beforehand.
    GitHub Actions: set AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID secrets.
    """
    credential = DefaultAzureCredential()
    return ComputeManagementClient(credential, config.AZURE_SUBSCRIPTION_ID)


def list_offers(
    client: ComputeManagementClient, location: str, publisher: str
) -> list[str]:
    """Return all offer names for a publisher in a region."""
    try:
        return [
            o.name
            for o in client.virtual_machine_images.list_offers(location, publisher)
        ]
    except Exception as exc:
        logger.warning(
            "list_offers failed — location=%s publisher=%s: %s", location, publisher, exc
        )
        return []


def list_skus(
    client: ComputeManagementClient, location: str, publisher: str, offer: str
) -> list[str]:
    """Return all SKU names for a publisher/offer in a region."""
    try:
        return [
            s.name
            for s in client.virtual_machine_images.list_skus(location, publisher, offer)
        ]
    except Exception as exc:
        logger.warning(
            "list_skus failed — location=%s publisher=%s offer=%s: %s",
            location, publisher, offer, exc,
        )
        return []


def list_versions(
    client: ComputeManagementClient,
    location: str,
    publisher: str,
    offer: str,
    sku: str,
) -> list[str]:
    """Return all version strings for a publisher/offer/sku in a region."""
    try:
        return [
            v.name
            for v in client.virtual_machine_images.list(
                location, publisher, offer, sku
            )
        ]
    except Exception as exc:
        logger.warning(
            "list_versions failed — location=%s publisher=%s offer=%s sku=%s: %s",
            location, publisher, offer, sku, exc,
        )
        return []
