"""Send notifications via Azure Communication Services Email using Managed Identity."""
from __future__ import annotations

import html
import logging
from typing import Iterable

from azure.communication.email import EmailClient
from azure.identity import DefaultAzureCredential

import config

logger = logging.getLogger(__name__)

# Columns shown in the email table (order matters).
_EMAIL_COLUMNS = [
    "publisher",
    "family",
    "distro_label",
    "sku",
    "version",
    "region",
    "architecture",
    "validated",
    "date_added",
]


def _client() -> EmailClient:
    credential = DefaultAzureCredential(
        managed_identity_client_id=config.AZURE_MANAGED_IDENTITY_CLIENT_ID
    )
    return EmailClient(config.ACS_ENDPOINT, credential)


def _rows_html(images: list[dict]) -> str:
    head = "".join(
        f"<th style='text-align:left;padding:4px 8px;background:#f3f3f3'>{h}</th>"
        for h in _EMAIL_COLUMNS
    )
    body = ""
    for img in images:
        cells = "".join(
            f"<td style='padding:4px 8px;border-top:1px solid #ddd'>"
            f"{html.escape(str(img.get(h, '')))}</td>"
            for h in _EMAIL_COLUMNS
        )
        body += f"<tr>{cells}</tr>"
    return (
        "<table style='border-collapse:collapse;font-family:Segoe UI,sans-serif;"
        f"font-size:13px'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def _plain_rows(images: list[dict]) -> str:
    return "\n".join(
        f"- {i.get('publisher')} / {i.get('family')} / {i.get('distro_label')} / "
        f"{i.get('sku')} v{i.get('version')} [{i.get('region')}, {i.get('architecture')}] "
        f"validated={i.get('validated')} added={i.get('date_added')}"
        for i in images
    )


def send_phase1_summary(
    new_images: list[dict],
    updated_images: list[dict] | None = None,
    recipients: Iterable[str] | None = None,
) -> None:
    """Phase 1 notification: brand-new SKUs and/or version bumps on known SKUs."""
    updated_images = updated_images or []
    if not new_images and not updated_images:
        logger.info("Nothing to report — skipping notification.")
        return

    recipients = list(recipients or config.NOTIFY_RECIPIENTS)
    if not recipients:
        logger.warning("No recipients configured — skipping notification.")
        return

    n_new, n_upd = len(new_images), len(updated_images)
    bits = []
    if n_new:
        bits.append(f"{n_new} new")
    if n_upd:
        bits.append(f"{n_upd} version bump{'s' if n_upd != 1 else ''}")
    subject = f"[AzNFS Phase 1] {' + '.join(bits)} marketplace SKU(s)"

    # Plain text
    plain_parts = []
    if n_new:
        plain_parts.append(
            f"NEW SKUs (validated=unknown — will be sent to Phase 2):\n"
            f"{_plain_rows(new_images)}"
        )
    if n_upd:
        plain_parts.append(
            f"VERSION BUMPS on already-classified SKUs "
            f"(validation state preserved):\n{_plain_rows(updated_images)}"
        )
    plain = "\n\n".join(plain_parts)

    # HTML
    html_parts = []
    if n_new:
        html_parts.append(
            f"<h3 style='font-family:Segoe UI,sans-serif'>New SKUs "
            f"<span style='color:#888;font-weight:normal'>({n_new})</span></h3>"
            f"<p style='font-family:Segoe UI,sans-serif;color:#555'>"
            f"validated=<code>unknown</code> — will be handed to Phase 2.</p>"
            f"{_rows_html(new_images)}"
        )
    if n_upd:
        html_parts.append(
            f"<h3 style='font-family:Segoe UI,sans-serif;margin-top:24px'>"
            f"Version bumps <span style='color:#888;font-weight:normal'>({n_upd})</span></h3>"
            f"<p style='font-family:Segoe UI,sans-serif;color:#555'>"
            f"Existing SKUs whose newest version changed. Validation state preserved.</p>"
            f"{_rows_html(updated_images)}"
        )
    html_body = "".join(html_parts)

    _send(subject, plain, html_body, recipients)


# Backwards-compatible alias for the older single-list call site.
def send_phase1_new_distros(images: list[dict], recipients: Iterable[str] | None = None) -> None:
    send_phase1_summary(images, [], recipients)


def _send(subject: str, plain: str, html_body: str, recipients: list[str]) -> None:
    message = {
        "senderAddress": config.ACS_SENDER,
        "recipients": {"to": [{"address": addr.strip()} for addr in recipients if addr.strip()]},
        "content": {"subject": subject, "plainText": plain, "html": html_body},
    }
    try:
        poller = _client().begin_send(message)
        result = poller.result()
        logger.info("Email sent (id=%s) to %d recipient(s).",
                    getattr(result, "id", "?"), len(recipients))
    except Exception as exc:
        # Never let a notification failure crash the scan.
        logger.error("Failed to send notification: %s", exc)
