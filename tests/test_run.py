from __future__ import annotations

import json

import pytest

from src.phase2 import run


# ---------------------------------------------------------------------------
# Phase 1 module fakes (stand in for scripts/notifier.py + scripts/db_manager.py)
# ---------------------------------------------------------------------------
class FakeNotifierMod:
    def __init__(self):
        self.failures = []
        self.pending = []
        self.trusted = []
        self.summaries = []

    def send_phase2_failure(self, distro_label, detail, recipients=None):
        self.failures.append((distro_label, detail))

    def send_phase2_pending_publish(self, distro_label, detail, recipients=None):
        self.pending.append((distro_label, detail))

    def send_phase2_trusted(self, distro_label, download_url=None, version=None, recipients=None):
        self.trusted.append((distro_label, download_url, version))

    def send_phase2_summary(self, processed, unsupported=None, pending_publish=None,
                            to_phase3=None, trusted=None, skipped=0, errors=None, recipients=None):
        self.summaries.append({
            "processed": processed,
            "unsupported": unsupported or [],
            "pending_publish": pending_publish or [],
            "to_phase3": to_phase3 or [],
            "trusted": trusted or [],
        })


class FakeDbMod:
    def __init__(self, matched=True, records=None, pending=None):
        self.calls = []
        self.matched = matched
        self.records = records or {}     # identity tuple -> row dict
        self.pending = pending or []     # rows currently pending_publish

    def set_validation_state(self, db_path, identity, state, last_validated_version=None):
        self.calls.append((db_path, identity, state, last_validated_version))
        return self.matched

    def get_image_record(self, db_path, publisher, image, sku, region, architecture):
        return self.records.get((publisher, image, sku, region, architecture), {})

    def get_rows_by_state(self, db_path, state):
        return list(self.pending) if state == "pending_publish" else []


class FakeProd:
    def __init__(self, repos=None, packages=None):
        self.repos = repos or {}
        self.packages = packages or {}

    def resolve_repo(self, distro, candidates, family=""):
        present = self.repos.get(distro, set())
        for v in candidates:
            if v in present:
                return v
        return None

    def list_packages(self, distro, version, family):
        return list(self.packages.get((distro, version), []))


def _entry(**kw):
    base = {
        "publisher": "Canonical",
        "image": "ubuntu-22_04-lts",
        "sku": "server",
        "version": "22.04.202506",
        "region": "eastus",
        "architecture": "x86_64",
        "family": "apt",
        "distro_label": "Ubuntu 22.04",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Notifier adapter
# ---------------------------------------------------------------------------
def test_notifier_adapter_routes_each_kind():
    mod = FakeNotifierMod()
    ad = run.Phase1NotifierAdapter(mod)

    ad.notify_actionable("Plan9 4", "no PMC prod repo")
    ad.notify_pending_publish("Debian 11", "publish aznfs")
    ad.notify_trusted("RHEL 9", "already validated v0.3.2")

    assert mod.failures == [("Plan9 4", "no PMC prod repo")]
    assert mod.pending == [("Debian 11", "publish aznfs")]
    assert mod.trusted == [("RHEL 9", None, None)]


def test_notifier_adapter_summary_pairs_reasons_into_buckets():
    mod = FakeNotifierMod()
    ad = run.Phase1NotifierAdapter(mod)

    ad.notify_actionable("Plan9 4", "no PMC prod repo")
    ad.notify_pending_publish("Debian 11", "publish aznfs")
    ad.notify_summary(
        processed=4,
        unsupported=["Plan9 4"],
        pending_publish=["Debian 11"],
        trusted=["RHEL 9"],
        to_phase3=["Ubuntu 22.04"],
    )

    s = mod.summaries[-1]
    assert s["processed"] == 4
    assert s["unsupported"] == [("Plan9 4", "no PMC prod repo")]
    assert s["pending_publish"] == [("Debian 11", "publish aznfs")]
    assert s["trusted"] == ["RHEL 9"]
    assert s["to_phase3"] == ["Ubuntu 22.04"]


# ---------------------------------------------------------------------------
# DB adapter
# ---------------------------------------------------------------------------
def test_db_adapter_forwards_path_identity_state():
    mod = FakeDbMod()
    ad = run.Phase1DbAdapter(mod, "/tmp/marketplace.db")
    ident = ("Canonical", "ubuntu-22_04-lts", "server", "eastus", "x86_64")

    ad.set_validation_state(ident, "known_supported")

    assert mod.calls == [("/tmp/marketplace.db", ident, "known_supported", None)]


def test_db_adapter_warns_when_no_row(caplog):
    mod = FakeDbMod(matched=False)
    ad = run.Phase1DbAdapter(mod, "db")
    with caplog.at_level("WARNING"):
        ad.set_validation_state(("p", "i", "s", "r", "a"), "known_unsupported")
    assert "No DB row matched" in caplog.text


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------
def test_load_entries_rejects_non_list(tmp_path):
    p = tmp_path / "needs.json"
    p.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(ValueError):
        run.load_entries(str(p))


def test_load_entries_reads_list(tmp_path):
    p = tmp_path / "needs.json"
    p.write_text(json.dumps([{"distro_label": "Ubuntu 22.04"}]))
    assert run.load_entries(str(p)) == [{"distro_label": "Ubuntu 22.04"}]


# ---------------------------------------------------------------------------
# enrich_and_merge: DB last_validated_version + pending_publish re-entry
# ---------------------------------------------------------------------------
def test_enrich_adds_last_validated_version_from_db():
    ident = ("Canonical", "ubuntu-22_04-lts", "server", "eastus", "x86_64")
    db = FakeDbMod(records={ident: {"last_validated_version": "0.3.2"}})

    out = run.enrich_and_merge([_entry()], db, "db")

    assert out[0]["last_validated_version"] == "0.3.2"


def test_enrich_merges_pending_publish_rows_and_dedupes():
    e = _entry()
    dup_row = {**e, "last_validated_version": ""}        # same identity -> not duplicated
    extra_row = {
        "publisher": "Debian", "image": "debian-11", "sku": "d",
        "region": "eastus", "architecture": "x86_64",
        "family": "apt", "distro_label": "Debian 11", "last_validated_version": "",
    }
    db = FakeDbMod(pending=[dup_row, extra_row])

    out = run.enrich_and_merge([e], db, "db")

    assert len(out) == 2
    assert {r["distro_label"] for r in out} == {"Ubuntu 22.04", "Debian 11"}


# ---------------------------------------------------------------------------
# End-to-end run() with injected fakes (no network, no Phase 1 modules)
# ---------------------------------------------------------------------------
def test_run_end_to_end_to_phase3_writes_lisa_jobs(tmp_path):
    notifier_mod = FakeNotifierMod()
    db_mod = FakeDbMod()
    out = tmp_path / "lisa_jobs.json"
    prod = FakeProd(
        repos={"ubuntu": {"22.04"}},
        packages={("ubuntu", "22.04"): ["aznfs_0.3.2_amd64.deb"]},
    )

    jobs = run.run(
        entries=[_entry()],
        prod=prod,
        notifier_obj=run.Phase1NotifierAdapter(notifier_mod),
        db=run.Phase1DbAdapter(db_mod, "marketplace.db"),
        lisa_jobs_path=str(out),
    )

    assert len(jobs) == 1
    written = json.loads(out.read_text())
    assert written[0]["package_filename"] == "aznfs_0.3.2_amd64.deb"
    assert db_mod.calls[-1][2] == "pending_validation"
    assert notifier_mod.summaries


def test_run_end_to_end_trusted(tmp_path):
    notifier_mod = FakeNotifierMod()
    db_mod = FakeDbMod()
    out = tmp_path / "lisa_jobs.json"
    prod = FakeProd(
        repos={"ubuntu": {"22.04"}},
        packages={("ubuntu", "22.04"): ["aznfs_0.3.2_amd64.deb"]},
    )

    jobs = run.run(
        entries=[_entry(last_validated_version="0.3.2")],
        prod=prod,
        notifier_obj=run.Phase1NotifierAdapter(notifier_mod),
        db=run.Phase1DbAdapter(db_mod, "marketplace.db"),
        lisa_jobs_path=str(out),
    )

    assert jobs == []
    assert db_mod.calls[-1][2] == "known_supported"
    assert notifier_mod.trusted and notifier_mod.summaries
