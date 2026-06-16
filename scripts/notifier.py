"""Send notifications via Azure Communication Services Email using Managed Identity."""
from __future__ import annotations

import html
import logging
from typing import Iterable

from azure.communication.email import EmailClient
from azure.identity import DefaultAzureCredential

import config

logger = logging.getLogger(__name__)


def _client() -> EmailClient:
    credential = DefaultAzureCredential(
        managed_identity_client_id=config.AZURE_MANAGED_IDENTITY_CLIENT_ID
    )
    return EmailClient(config.ACS_ENDPOINT, credential)


# Columns shown in the distro-rollup table (the cut-down, per-OS-release view).
_DISTRO_COLUMNS = ["family", "distro_label", "publishers", "architectures", "sku_count"]
_DISTRO_LABELS = {"sku_count": "# SKUs", "architectures": "arch"}


def _fmt(value) -> str:
    return ", ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)


def _distro_rows_html(rollup: list[dict]) -> str:
    head = "".join(
        f"<th style='text-align:left;padding:4px 8px;background:#f3f3f3'>"
        f"{_DISTRO_LABELS.get(h, h)}</th>"
        for h in _DISTRO_COLUMNS
    )
    body = ""
    for row in rollup:
        cells = "".join(
            f"<td style='padding:4px 8px;border-top:1px solid #ddd'>"
            f"{html.escape(_fmt(row.get(h, '')))}</td>"
            for h in _DISTRO_COLUMNS
        )
        body += f"<tr>{cells}</tr>"
    return (
        "<table style='border-collapse:collapse;font-family:Segoe UI,sans-serif;"
        f"font-size:13px'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def _distro_plain(rollup: list[dict]) -> str:
    return "\n".join(
        f"- {r.get('family')} / {r.get('distro_label')} "
        f"[{_fmt(r.get('publishers', []))}; {_fmt(r.get('architectures', []))}] "
        f"({r.get('sku_count')} SKU(s))"
        for r in rollup
    )


def send_phase1_summary(
    new_distros: list[dict],
    recipients: Iterable[str] | None = None,
) -> None:
    """Phase 1 notification: NEW distro releases that need AzNFS validation.

    Reports at the distro-release granularity only — the cut-down list. The
    underlying SKU / version / region / architecture churn is deliberately not
    shown (it is tracked in the DB and the per-SKU artifact for auditing), so a
    fresh scan reports a handful of OS releases, not hundreds of SKUs.
    """
    if not new_distros:
        logger.info("No new distro releases — skipping notification.")
        return

    recipients = list(recipients or config.NOTIFY_RECIPIENTS)
    if not recipients:
        logger.warning("No recipients configured — skipping notification.")
        return

    n = len(new_distros)
    subject = f"[AzNFS Phase 1] {n} new distro release(s) need validation"

    plain = (
        f"{n} new distro release(s) need AzNFS validation "
        f"(collapsed from marketplace SKUs; sku/version/region/architecture are "
        f"not part of a distro's identity):\n\n"
        f"{_distro_plain(new_distros)}"
    )

    html_body = (
        f"<h3 style='font-family:Segoe UI,sans-serif'>Distro releases to validate "
        f"<span style='color:#888;font-weight:normal'>({n})</span></h3>"
        f"<p style='font-family:Segoe UI,sans-serif;color:#555'>"
        f"New OS releases discovered on the marketplace — the unit AzNFS validates. "
        f"SKU / version / region / architecture are collapsed (shown as counts).</p>"
        f"{_distro_rows_html(new_distros)}"
    )

    _send(subject, plain, html_body, recipients)


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


# ===========================================================================
# Phase 2 (PMC tux-dev publishing orchestrator) notifications
# ===========================================================================
# Reuses the ACS email path (`_send`) for the team and the run summary, and a
# webhook for pre-flight ping / ops paging. Per the orchestrator's design we
# send one message per *actionable failure* and exactly one run summary; the
# successfully-published / already-published images are reported only in the
# summary (no per-image chatter).

def notify(
    subject: str,
    plain: str,
    html_body: str | None = None,
    recipients: Iterable[str] | None = None,
) -> None:
    """Generic e-mail helper (used by the Phase 2 functions below)."""
    recipients = list(recipients or config.NOTIFY_RECIPIENTS)
    if not recipients:
        logger.warning("No recipients configured — skipping notification.")
        return
    body = html_body or f"<pre style='font-family:Consolas,monospace'>{html.escape(plain)}</pre>"
    _send(subject, plain, body, recipients)


def notifications_ready() -> tuple[bool, str]:
    """True when the ACS e-mail channel is fully configured.

    Pre-flight uses this instead of sending a probe e-mail: if endpoint, sender
    or recipients are missing, actionable failures could not be delivered, so
    the run aborts (and page_ops still best-effort e-mails the abort reason).
    """
    missing = []
    if not config.ACS_ENDPOINT:
        missing.append("ACS_ENDPOINT")
    if not config.ACS_SENDER:
        missing.append("ACS_SENDER")
    if not config.NOTIFY_RECIPIENTS:
        missing.append("NOTIFY_RECIPIENTS")
    if missing:
        return False, "missing " + ", ".join(missing)
    return True, ""


def send_phase2_failure(
    distro_label: str,
    detail: str,
    recipients: Iterable[str] | None = None,
) -> None:
    """One actionable-failure notice (a gate marked the release known_unsupported).

    ``detail`` is the gate's human-actionable message (what a human must do to
    unblock the release).
    """
    subject = f"[AzNFS Phase 2] action needed: {distro_label}"
    plain = f"{distro_label}: {detail}"
    notify(subject, plain, recipients=recipients)


def send_phase2_trusted(
    distro_label: str,
    download_url: str | None = None,
    version: str | None = None,
    recipients: Iterable[str] | None = None,
) -> None:
    """Gate 3 hit: the package is already on tux-dev -- trusted.

    Includes the distro, the already-published AzNFS version and the tux-dev
    download URL so a human can locate the package straight from the mail.
    """
    subject = f"[AzNFS Phase 2] already published (trusted): {distro_label}"
    lines = [f"{distro_label}: AzNFS is already published on PMC tux-dev -- trusted."]
    if version:
        lines.append(f"Version: {version}")
    if download_url:
        lines.append(f"Download (tux-dev): {download_url}")
    notify(subject, "\n".join(lines), recipients=recipients)


def send_phase2_summary(
    processed: int,
    unsupported: list[tuple[str, str]] | None = None,
    to_phase3: list[str] | None = None,
    trusted: list[str] | None = None,
    skipped: int = 0,
    errors: list[tuple[str, str]] | None = None,
    recipients: Iterable[str] | None = None,
) -> None:
    """The single end-of-run summary.

    ``unsupported`` / ``errors`` are lists of ``(distro_label, reason)``;
    ``to_phase3`` is the list of distro_labels freshly built + handed to Phase 3;
    ``trusted`` is the list already published (Phase 3 skipped).
    """
    unsupported = unsupported or []
    to_phase3 = to_phase3 or []
    trusted = trusted or []
    errors = errors or []

    subject = (
        f"[AzNFS Phase 2] run summary: {len(to_phase3)} to Phase 3, "
        f"{len(trusted)} trusted, {len(unsupported)} unsupported"
    )

    def _lines(items):
        return "\n".join(f"  - {lbl}: {reason}" for lbl, reason in items) or "  (none)"

    plain = (
        f"Phase 2 processed {processed} image(s).\n\n"
        f"Handed to Phase 3 ({len(to_phase3)}):\n"
        + ("\n".join(f"  - {lbl}" for lbl in to_phase3) or "  (none)")
        + f"\n\nAlready published, trusted (Phase 3 skipped) ({len(trusted)}):\n"
        + ("\n".join(f"  - {lbl}" for lbl in trusted) or "  (none)")
        + f"\n\nMarked unsupported ({len(unsupported)}):\n{_lines(unsupported)}"
        + (f"\n\nSkipped (family/label mismatch): {skipped}" if skipped else "")
        + (f"\n\nOrchestrator errors ({len(errors)}):\n{_lines(errors)}" if errors else "")
    )
    notify(subject, plain, recipients=recipients)


def post_webhook(url: str | None, text: str, timeout: int = 15) -> bool:
    """POST a simple ``{"text": ...}`` payload to a webhook. Returns success.

    Used for the pre-flight reachability ping. Never raises — a webhook problem
    is reported via the return value so the caller can decide.
    """
    if not url:
        logger.warning("No webhook URL configured — skipping webhook post.")
        return False
    try:
        import requests  # local import: keeps Phase 1's import surface unchanged
        resp = requests.post(url, json={"text": text}, timeout=timeout)
        if not resp.ok:
            logger.error("Webhook POST -> %s", resp.status_code)
            return False
        return True
    except Exception as exc:  # pragma: no cover - network/dep guard
        logger.error("Webhook POST failed: %s", exc)
        return False


def page_ops(reason: str, target: str | None = None, timeout: int = 15) -> bool:
    """Page ops on a pre-flight abort (whole-run failure).

    Posts to the ops ``target`` webhook and also e-mails the team as a durable
    record. Returns whether the webhook page was delivered.
    """
    text = f"[AzNFS Phase 2 PRE-FLIGHT ABORT] {reason}"
    posted = post_webhook(target, text, timeout=timeout) if target else False
    try:
        notify("[AzNFS Phase 2] PRE-FLIGHT ABORT", text)
    except Exception as exc:  # pragma: no cover - email is a best-effort record
        logger.error("page_ops e-mail failed: %s", exc)
    return posted
