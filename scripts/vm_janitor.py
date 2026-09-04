#!/usr/bin/env python3
"""Delete the VMs Phase 3 leaves behind in the pinned resource group.

LISA's only cleanup is deleting the whole resource group it created. When
``resource_group_name`` is pinned in the runbook it deliberately skips that
(``platform_.py``: "skipped to delete resource group ... as it's specified in
runbook") and has no per-resource fallback, so every VM it provisions survives
the run. Pinning the RG to avoid subscription-scope Contributor therefore
disabled cleanup entirely, and the group accumulated 103 running VMs in a week.

This deletes them instead: the VMs, then the NICs / public IPs / disks they
leave orphaned, then LISA's transient storage accounts. The shared VNet and NSG
are kept -- they cost nothing and LISA reuses them.

Run with ``--alert`` to e-mail when anything survives the sweep, so a future
cleanup regression is noticed instead of quietly costing money.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# LISA names its transient NFS storage accounts lisasc<random>; anything else in
# the group was put there deliberately and is left alone.
STORAGE_PREFIX = "lisa"


def _az(*args: str) -> object:
    """Run an `az` command and return its parsed JSON output."""
    proc = subprocess.run(
        ["az", *args, "--output", "json"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"az {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def _parse_created(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def stale_vms(resource_group: str, older_than_hours: float) -> list[dict]:
    """VMs eligible for deletion, oldest first.

    ``older_than_hours`` guards a concurrently running environment: 0 sweeps
    everything (safe straight after a run, which holds the only Phase 3 slot),
    a few hours suits a scheduled sweep.
    """
    vms = _az("vm", "list", "-g", resource_group,
              "--query", "[].{name:name, id:id, created:timeCreated}") or []
    if older_than_hours <= 0:
        return sorted(vms, key=lambda v: v.get("created") or "")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    keep: list[dict] = []
    for vm in vms:
        created = _parse_created(vm.get("created", ""))
        if created is None or created < cutoff:
            keep.append(vm)
        else:
            logger.info("Keeping %s: created %s, newer than the cutoff",
                        vm.get("name"), vm.get("created"))
    return sorted(keep, key=lambda v: v.get("created") or "")


def _delete_orphans(resource_group: str) -> dict[str, int]:
    """Remove the NICs, public IPs, disks and storage accounts left behind.

    Only ever touches resources that are already detached, so it cannot take
    anything out from under a running VM.
    """
    removed = {"nics": 0, "public_ips": 0, "disks": 0, "storage": 0}

    nics = _az("network", "nic", "list", "-g", resource_group,
               "--query", "[?virtualMachine==null].id") or []
    for nic_id in nics:
        _az("network", "nic", "delete", "--ids", nic_id)
        removed["nics"] += 1

    ips = _az("network", "public-ip", "list", "-g", resource_group,
              "--query", "[?ipConfiguration==null].id") or []
    for ip_id in ips:
        _az("network", "public-ip", "delete", "--ids", ip_id)
        removed["public_ips"] += 1

    disks = _az("disk", "list", "-g", resource_group,
                "--query", "[?diskState=='Unattached'].id") or []
    for disk_id in disks:
        _az("disk", "delete", "--ids", disk_id, "--yes")
        removed["disks"] += 1

    accounts = _az("storage", "account", "list", "-g", resource_group,
                   "--query", f"[?starts_with(name, '{STORAGE_PREFIX}')].id") or []
    for account_id in accounts:
        _az("storage", "account", "delete", "--ids", account_id, "--yes")
        removed["storage"] += 1

    return removed


def sweep(resource_group: str, older_than_hours: float,
          dry_run: bool = False) -> dict:
    """Delete stale VMs and their orphans. Returns what was removed and left."""
    victims = stale_vms(resource_group, older_than_hours)
    logger.info("%d VM(s) eligible for deletion in %s", len(victims), resource_group)

    if dry_run:
        for vm in victims:
            logger.info("  would delete %s (created %s)", vm["name"], vm.get("created"))
        return {"deleted_vms": 0, "eligible": len(victims), "orphans": {}, "remaining": len(victims)}

    if victims:
        # One call so the deletions run in parallel and we wait for all of them;
        # the disks and NICs cannot be removed until their VM is gone.
        _az("vm", "delete", "--yes", "--ids", *[vm["id"] for vm in victims])

    orphans = _delete_orphans(resource_group)
    remaining = len(_az("vm", "list", "-g", resource_group, "--query", "[].name") or [])
    return {"deleted_vms": len(victims), "eligible": len(victims),
            "orphans": orphans, "remaining": remaining}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--older-than-hours", type=float, default=0.0,
                        help="0 (default) sweeps every VM; use a few hours for a "
                             "scheduled sweep that must not touch a live run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--alert", action="store_true",
                        help="e-mail if anything survives the sweep")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        result = sweep(args.resource_group, args.older_than_hours, args.dry_run)
    except Exception as exc:  # noqa: BLE001 - cleanup must report, never abort the run
        logger.exception("VM sweep failed")
        if args.alert:
            _alert(args.resource_group, f"the sweep itself failed: {exc}")
        return 1

    logger.info("Deleted %d VM(s); orphans removed: %s; %d VM(s) remain",
                result["deleted_vms"], result["orphans"], result["remaining"])
    if args.alert and result["remaining"]:
        _alert(args.resource_group,
               f"{result['remaining']} VM(s) still present after the sweep")
    return 0


def _alert(resource_group: str, detail: str) -> None:
    """Mail the team; a silent cleanup failure is what let 103 VMs accumulate."""
    try:
        import notifier
        notifier.notify(
            subject=f"[AzNFS pipeline] Phase 3 VM cleanup needs attention ({resource_group})",
            plain=(f"Phase 3 leaves VMs behind unless they are swept explicitly, and "
                   f"{detail}.\n\nCheck the resource group {resource_group}: every VM "
                   f"left running is billed until it is removed."),
        )
    except Exception:  # noqa: BLE001 - never let the alert break the run
        logger.exception("Could not send the cleanup alert")


if __name__ == "__main__":
    raise SystemExit(main())
