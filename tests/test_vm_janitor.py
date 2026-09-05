from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-000000000000")

import pytest

import vm_janitor


def _vm(name, created):
    return {"name": name, "id": f"/subscriptions/s/rg/r/{name}", "created": created}


def test_zero_hours_sweeps_everything(monkeypatch):
    # Straight after a run Phase 3 holds the only slot, so nothing is in use.
    vms = [_vm("old", "2026-08-26T11:35:24+00:00"), _vm("new", "2026-09-04T21:00:00+00:00")]
    monkeypatch.setattr(vm_janitor, "_az", lambda *a: vms)

    assert [v["name"] for v in vm_janitor.stale_vms("rg", 0)] == ["old", "new"]


def test_an_age_cutoff_protects_a_running_environment(monkeypatch):
    # A scheduled sweep must not delete a VM a live run is still using.
    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    vms = [_vm("old", "2026-08-26T11:35:24+00:00"), _vm("live", recent)]
    monkeypatch.setattr(vm_janitor, "_az", lambda *a: vms)

    assert [v["name"] for v in vm_janitor.stale_vms("rg", 3)] == ["old"]


def test_an_unparseable_creation_time_is_swept(monkeypatch):
    # Better to remove a VM of unknown age than to leak it for ever.
    monkeypatch.setattr(vm_janitor, "_az", lambda *a: [_vm("odd", "not-a-date")])

    assert [v["name"] for v in vm_janitor.stale_vms("rg", 3)] == ["odd"]


def test_dry_run_deletes_nothing(monkeypatch):
    calls = []

    def fake_az(*args):
        calls.append(args)
        return [_vm("old", "2026-08-26T11:35:24+00:00")]

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    result = vm_janitor.sweep("rg", 0, dry_run=True)

    assert result["deleted_vms"] == 0
    assert not any("delete" in a for call in calls for a in call)


def test_sweep_deletes_vms_then_their_orphans(monkeypatch):
    # Order matters twice over: a disk or NIC cannot be removed while its VM
    # holds it, and a private endpoint's NIC cannot be removed at all until the
    # endpoint is gone (Azure rejects it with NicInUseWithPrivateEndpoint).
    seen = []

    def fake_az(*args):
        seen.append(args[:3])
        if args[:2] == ("vm", "list"):
            return [_vm("old", "2026-08-26T11:35:24+00:00")] if len(seen) == 1 else []
        if args[:3] == ("storage", "account", "list"):
            return [{"name": "lisascaqty6dog2w", "id": "/id/acct"}]
        if "list" in args[:3]:
            return ["/id/one"]
        return None

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    result = vm_janitor.sweep("rg", 0)

    assert result["deleted_vms"] == 1
    assert result["remaining"] == 0
    assert result["failures"] == 0
    assert seen.index(("vm", "delete", "--yes")) < seen.index(("network", "private-endpoint", "list"))
    assert (seen.index(("network", "private-endpoint", "delete"))
            < seen.index(("network", "nic", "list")))


def test_one_stubborn_resource_does_not_abandon_the_sweep(monkeypatch):
    # A single failure used to abort everything, leaving 106 disks and IPs.
    def fake_az(*args):
        if args[:2] == ("vm", "list"):
            return []
        if args[:3] == ("storage", "account", "list"):
            return [{"name": "lisascaqty6dog2w", "id": "/id/acct"}]
        if "list" in args[:3]:
            return ["/id/one"]
        if args[:3] == ("network", "nic", "delete"):
            raise RuntimeError("NicInUseWithPrivateEndpoint")
        return None

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    result = vm_janitor.sweep("rg", 0)

    assert result["failures"] == 1
    assert result["orphans"]["disks"] == 1        # reached despite the NIC failure
    assert result["orphans"]["storage"] == 1


def test_survivors_raise_an_alert(monkeypatch):
    # A silent cleanup failure is what let 103 VMs accumulate unnoticed.
    monkeypatch.setattr(vm_janitor, "sweep",
                        lambda *a, **k: {"deleted_vms": 0, "eligible": 0,
                                         "orphans": {}, "remaining": 7})
    alerts = []
    monkeypatch.setattr(vm_janitor, "_alert", lambda rg, detail: alerts.append(detail))

    assert vm_janitor.main(["--resource-group", "rg", "--alert"]) == 0
    assert "7 VM(s) still present" in alerts[0]


def test_a_failed_sweep_alerts_and_reports_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("az exploded")

    monkeypatch.setattr(vm_janitor, "sweep", boom)
    alerts = []
    monkeypatch.setattr(vm_janitor, "_alert", lambda rg, detail: alerts.append(detail))

    assert vm_janitor.main(["--resource-group", "rg", "--alert"]) == 1
    assert "az exploded" in alerts[0]


def test_a_clean_sweep_stays_quiet(monkeypatch):
    monkeypatch.setattr(vm_janitor, "sweep",
                        lambda *a, **k: {"deleted_vms": 3, "eligible": 3,
                                         "orphans": {}, "remaining": 0})
    alerts = []
    monkeypatch.setattr(vm_janitor, "_alert", lambda rg, detail: alerts.append(detail))

    assert vm_janitor.main(["--resource-group", "rg", "--alert"]) == 0
    assert alerts == []


def test_shared_storage_account_is_never_deleted(monkeypatch):
    # LISA's shared account is lisas<location><subscription-suffix>, which the
    # old "lisa" prefix matched. It is reused across runs and must survive.
    deleted = []

    def fake_az(*args):
        if args[:2] == ("vm", "list"):
            return []
        if args[:3] == ("storage", "account", "list"):
            return [{"name": "lisascentralindi92ef804a", "id": "/id/shared"},
                    {"name": "lisascaqty6dog2w", "id": "/id/transient"}]
        if "list" in args[:3]:
            return []
        if args[:3] == ("storage", "account", "delete"):
            deleted.append(args[-1])
        return None

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    result = vm_janitor.sweep("rg", 0)

    assert deleted == ["/id/transient"]
    assert result["orphans"]["storage"] == 1


def test_orphan_groups_are_swept_when_no_rg_is_pinned(monkeypatch):
    # Unpinned is the normal setup, and LISA deletes its own group -- so a
    # tagged group still standing means that cleanup did not happen.
    deleted = []

    def fake_az(*args):
        if args[:2] == ("group", "list"):
            return ["lisa-20260905-1-e0", "lisa-20260905-1-e1"]
        if args[:3] == ("group", "delete", "--name"):
            deleted.append(args[3])
        return None

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    result = vm_janitor.sweep_orphan_groups(0)

    assert deleted == ["lisa-20260905-1-e0", "lisa-20260905-1-e1"]
    assert result["deleted_groups"] == 2


def test_a_group_holding_a_fresh_vm_is_left_alone(monkeypatch):
    # Guards a concurrently running environment when a cutoff is given.
    fresh = datetime.now(timezone.utc).isoformat()

    def fake_az(*args):
        if args[:2] == ("group", "list"):
            return ["lisa-live-e0"]
        if args[:2] == ("vm", "list"):
            return [fresh]
        return None

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    assert vm_janitor.orphan_groups(24) == []


def test_an_orphan_group_alerts_even_when_deletion_succeeds(monkeypatch):
    # The group existing at all means LISA's cleanup did not run -- worth
    # knowing about even though the janitor tidied up after it.
    alerts = []

    def fake_az(*args):
        if args[:2] == ("group", "list"):
            return ["lisa-orphan-e0"]
        return None

    monkeypatch.setattr(vm_janitor, "_az", fake_az)
    monkeypatch.setattr(vm_janitor, "_alert", lambda scope, detail: alerts.append(detail))
    assert vm_janitor.main(["--older-than-hours", "0", "--alert"]) == 0
    assert len(alerts) == 1
    assert "outlived" in alerts[0]
