from __future__ import annotations

from dataclasses import dataclass, field

from src.phase2.orchestrator import (
    KNOWN_SUPPORTED,
    KNOWN_UNSUPPORTED,
    _csv_covers,
    next_aznfs_version,
    preflight_checks,
    process_entry,
    run_phase2,
)
from src.phase2.repo_index import RepoIndex


def entry(**kw):
    base = {
        "publisher": "Canonical",
        "image": "ubuntu-24_04-lts",
        "sku": "server",
        "version": "24.04.202506",
        "region": "eastus",
        "architecture": "x86_64",
        "family": "apt",
        "distro_label": "Ubuntu 24.04",
        "validated": "unknown",
    }
    base.update(kw)
    return base


@dataclass
class FakeDb:
    updates: list[tuple] = field(default_factory=list)

    def set_validation_state(self, identity, validated, reason, date_added):
        self.updates.append((identity, validated, reason, date_added))


@dataclass
class FakeNotifier:
    actionable: list[tuple[str, str]] = field(default_factory=list)
    trusted: list[tuple[str, str]] = field(default_factory=list)
    summaries: list[tuple[int, list[str], list[str]]] = field(default_factory=list)

    def notify_actionable(self, distro_label: str, message: str) -> None:
        self.actionable.append((distro_label, message))

    def notify_trusted(self, distro_label: str, message: str) -> None:
        self.trusted.append((distro_label, message))

    def notify_summary(self, processed: int, unsupported: list[str], to_phase3: list[str]) -> None:
        self.summaries.append((processed, unsupported, to_phase3))


@dataclass
class FakeOnboarding:
    configs: dict[str, dict] = field(default_factory=dict)
    pingable: bool = True

    def get_repo_config(self, repo_name: str):
        return self.configs.get(repo_name)

    def ping(self) -> bool:
        return self.pingable


@dataclass
class FakePackageIndex:
    files: list[str] = field(default_factory=list)
    reveal_after: int = 0           # return [] for the first N calls, then files
    pingable: bool = True
    _calls: int = field(default=0, init=False)

    def list_packages(self, repo: str, family: str):
        self._calls += 1
        if self._calls <= self.reveal_after:
            return []
        ext = ".rpm" if family.lower() in {"yum", "rpm", "dnf"} else ".deb"
        return [n for n in self.files
                if n.lower().startswith("aznfs") and n.lower().endswith(ext)]

    def ping(self) -> bool:
        return self.pingable


@dataclass
class FakeAdoBuild:
    """Build client: yields (state, result) tuples in order; last one repeats."""
    states: list = field(default_factory=lambda: [("completed", "succeeded")])
    triggered: list = field(default_factory=list)
    _i: int = field(default=0, init=False)

    def ping(self, client_id=None):
        return True

    def trigger_run(self, params: dict) -> str:
        self.triggered.append(params)
        return "run-123"

    def get_run_status(self, run_id: str):
        state = self.states[min(self._i, len(self.states) - 1)]
        self._i += 1
        return state


class FakeClock:
    """Deterministic monotonic clock; ``sleep`` advances it (no real waiting)."""
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.t += secs


@dataclass
class FakeAdo:
    ok: bool = True

    def ping(self, client_id=None):
        return self.ok


def test_gate1_fail_notifies_and_marks_unsupported():
    idx = RepoIndex(apt=frozenset(), yum=frozenset())
    onboarding = FakeOnboarding()
    package_index = FakePackageIndex()
    db = FakeDb()
    notifier = FakeNotifier()

    r = process_entry(entry(), idx, onboarding, package_index, db, notifier, "Ubuntu-24.04,amd64,microsoft-ubuntu-noble", "2.0.10")
    assert r.outcome == "unsupported"
    assert notifier.actionable[0][1] == "tuxdev repo missing"
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


def test_gate2_fail_notifies_and_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    onboarding = FakeOnboarding(configs={"microsoft-ubuntu-noble": {"signing_service": "other", "groups": ["shared"]}})
    package_index = FakePackageIndex()
    db = FakeDb()
    notifier = FakeNotifier()

    r = process_entry(entry(), idx, onboarding, package_index, db, notifier, "Ubuntu-24.04,amd64,microsoft-ubuntu-noble", "2.0.10")
    assert r.outcome == "unsupported"
    assert notifier.actionable[0][1] == "repo config mismatch"
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


def test_gate3_hit_marks_supported_emits_lisa_job_and_skips_phase3():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    onboarding = FakeOnboarding(
        configs={"microsoft-ubuntu-noble": {"signing_service": "esrp", "repo_groups": ["shared"]}}
    )
    package_index = FakePackageIndex(files=["aznfs_0.3.2_amd64.deb"])  # < TRUST_BELOW_VERSION
    db = FakeDb()
    notifier = FakeNotifier()

    r = process_entry(entry(), idx, onboarding, package_index, db, notifier, CSV_COVERS_NOBLE, "0.3.0")
    assert r.outcome == "trusted"
    assert r.lisa_job is not None
    assert r.lisa_job["download_url"].startswith("https://")
    assert "distro_info" in r.lisa_job
    assert r.lisa_job["variant_name"] == "0.3.2"
    assert r.lisa_job["newly_published"] is False
    assert notifier.trusted[0][1] == "already published,trusted."
    assert db.updates[-1][1] == KNOWN_SUPPORTED


def test_gate4_miss_notifies_and_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    onboarding = FakeOnboarding(
        configs={"microsoft-ubuntu-noble": {"signing_service": "esrp", "repo_groups": ["shared"]}}
    )
    package_index = FakePackageIndex()
    db = FakeDb()
    notifier = FakeNotifier()

    r = process_entry(entry(), idx, onboarding, package_index, db, notifier, "Debian-12,amd64,microsoft-debian-bookworm", "2.0.10")
    assert r.outcome == "unsupported"
    assert "packages.tux.csv" in notifier.actionable[0][1]
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


def test_gate4_token_arch_mismatch_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    onboarding = FakeOnboarding(
        configs={"microsoft-ubuntu-noble": {"signing_service": "esrp", "repo_groups": ["shared"]}}
    )
    package_index = FakePackageIndex()
    db = FakeDb()
    notifier = FakeNotifier()

    # distro row exists but only the arm64 build recipe; entry is x86_64 -> not covered
    csv_text = "Ubuntu-24.04,aznfsArm,microsoft-ubuntu-noble,noble\n"
    r = process_entry(entry(), idx, onboarding, package_index, db, notifier, csv_text, "2.0.10")
    assert r.outcome == "unsupported"


def test_csv_covers_decodes_recipe_tokens():
    csv = (
        "# packages.tux.csv comment header\n"
        "Ubuntu-24.04,aznfsDeb,microsoft-ubuntu-noble,noble\n"
        "Ubuntu-24.04,aznfsArm,microsoft-ubuntu-noble,noble\n"
        "RHEL-9.0,aznfsRpm,microsoft-rhel9\n"
        "RHEL-9.0,aznfsArcRpm,microsoft-rhel9\n"
    )
    # apt: x86_64 (aznfsDeb) and arm64 (aznfsArm)
    assert _csv_covers(csv, "Ubuntu 24.04", "x86_64", "apt") is True
    assert _csv_covers(csv, "Ubuntu 24.04", "arm64", "apt") is True
    # yum: x86_64 (aznfsRpm) and arm64 (aznfsArcRpm); 'RHEL 9' normalises to rhel-9
    assert _csv_covers(csv, "RHEL 9", "x86_64", "yum") is True
    assert _csv_covers(csv, "RHEL 9", "aarch64", "yum") is True
    # wrong package manager / unknown distro / empty csv -> not covered
    assert _csv_covers(csv, "Ubuntu 24.04", "x86_64", "yum") is False
    assert _csv_covers(csv, "Debian 12", "x86_64", "apt") is False
    assert _csv_covers("", "Ubuntu 24.04", "x86_64", "apt") is False


def test_preflight_ado_connectivity_fail():
    ok, why = preflight_checks([entry()], ado=FakeAdo(ok=False), ado_client_id="cid")
    assert not ok
    assert "ADO connectivity" in why


def test_preflight_publisher_label_mismatch_fail():
    bad = entry(publisher="Canonical", distro_label="RHEL 9")
    ok, why = preflight_checks([bad])
    assert not ok
    assert "publisher/distro_label mismatch" in why


def test_preflight_tux_unreachable_fail():
    pi = FakePackageIndex(pingable=False)
    ok, why = preflight_checks([entry()], package_index=pi)
    assert not ok
    assert "tux-dev package index connectivity" in why


def test_preflight_onboarding_unreachable_fail():
    ob = FakeOnboarding(pingable=False)
    ok, why = preflight_checks([entry()], onboarding=ob)
    assert not ok
    assert "onboarding connectivity" in why


def test_run_phase2_stops_on_preflight_fail():
    idx = RepoIndex(apt=frozenset(), yum=frozenset())
    onboarding = FakeOnboarding()
    package_index = FakePackageIndex()
    db = FakeDb()
    notifier = FakeNotifier()

    jobs = run_phase2(
        entries=[entry()],
        repo_index=idx,
        onboarding=onboarding,
        package_index=package_index,
        db=db,
        notifier=notifier,
        packages_tux_csv_text="",
        aznfs_version="2.0.10",
        ado=FakeAdo(ok=False),
        ado_client_id="cid",
    )
    assert jobs == []
    assert notifier.actionable
    assert notifier.actionable[0][0] == "PRE-FLIGHT"


# ---------------------------------------------------------------------------
# Gate 4 pass -> build -> poll -> verify
# ---------------------------------------------------------------------------
def _esrp_onboarding():
    return FakeOnboarding(
        configs={"microsoft-ubuntu-noble": {"signing_service": "esrp", "repo_groups": ["shared"]}}
    )


# Real packages.tux.csv shape: <Distro Name>,<recipe token>,<Repo Name>,<Release>.
CSV_COVERS_NOBLE = "Ubuntu-24.04,aznfsDeb,microsoft-ubuntu-noble,noble\n"


def test_gate4_pass_without_ado_returns_to_phase3():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=[])  # nothing published yet
    db = FakeDb()
    notifier = FakeNotifier()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "0.3.10")
    assert r.outcome == "to_phase3"
    assert r.lisa_job is None


def test_gate4_pass_build_succeeds_and_visible_emits_published_job():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    # empty at Gate 3, then visible on the post-build visibility check
    package_index = FakePackageIndex(files=["aznfs_0.3.10_amd64.deb"], reveal_after=1)
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "0.3.10", ado=ado, sleep=fc.sleep, clock=fc)
    assert r.outcome == "published"
    assert r.lisa_job["newly_published"] is True
    assert r.lisa_job["package_filename"] == "aznfs_0.3.10_amd64.deb"
    assert r.lisa_job["variant_name"] == "0.3.10"
    assert r.lisa_job["download_url"].startswith("https://")
    assert ado.triggered and ado.triggered[0]["targetEnv"] == "tuxdev"
    assert ado.triggered[0]["versionName"] == "0.3.10"
    assert notifier.trusted[-1][1] == "published, handing to Phase 3"
    assert db.updates[-1][1] == KNOWN_SUPPORTED


def test_gate4_pass_build_failed_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=[])
    ado = FakeAdoBuild(states=[("completed", "failed")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "0.3.10", ado=ado, sleep=fc.sleep, clock=fc)
    assert r.outcome == "unsupported"
    assert "tux-dev pipeline failed" in notifier.actionable[-1][1]
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


def test_gate4_pass_build_timeout_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=[])
    ado = FakeAdoBuild(states=[("inProgress", None)])  # never completes
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "0.3.10", ado=ado, sleep=fc.sleep, clock=fc)
    assert r.outcome == "unsupported"
    assert "did not finish within" in notifier.actionable[-1][1]
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


def test_gate4_pass_build_succeeded_but_not_visible_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=[])  # never becomes visible
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "0.3.10", ado=ado, sleep=fc.sleep, clock=fc)
    assert r.outcome == "unsupported"
    assert "not visible" in notifier.actionable[-1][1]
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


def test_gate3_below_threshold_trusts_and_skips_build():
    # Published version strictly below TRUST_BELOW_VERSION (0.3.10) is trusted
    # as-is: no build is triggered.
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=["aznfs_0.3.2_amd64.deb"])
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "0.3.0", ado=ado, sleep=fc.sleep, clock=fc)
    assert r.outcome == "trusted"
    assert r.lisa_job["newly_published"] is False
    assert r.lisa_job["variant_name"] == "0.3.2"
    assert not ado.triggered                      # build NOT triggered
    assert db.updates[-1][1] == KNOWN_SUPPORTED


def test_gate3_at_or_above_threshold_rebuilds_via_gate4():
    # Published version >= TRUST_BELOW_VERSION must NOT be trusted: it falls
    # through to Gate 4 and triggers a fresh build.
    class _StagedIndex:
        def __init__(self):
            self._calls = 0

        def list_packages(self, repo, family):
            self._calls += 1
            if self._calls == 1:
                return ["aznfs_0.3.10_amd64.deb"]                             # at threshold at Gate 3
            return ["aznfs_0.3.10_amd64.deb", "aznfs_0.3.11_amd64.deb"]       # after build

        def ping(self):
            return True

    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), _StagedIndex(), db, notifier,
                      CSV_COVERS_NOBLE, "0.3.11", ado=ado,
                      version_provider=lambda: "0.3.11", sleep=fc.sleep, clock=fc)
    assert r.outcome == "published"          # rebuilt, not trusted
    assert ado.triggered                      # build WAS triggered
    assert ado.triggered[0]["versionName"] == "0.3.11"
    assert r.lisa_job["variant_name"] == "0.3.11"
    assert r.lisa_job["newly_published"] is True


def test_gate4_pass_empty_version_marks_unsupported():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=[])
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "", ado=ado, sleep=fc.sleep, clock=fc)
    assert r.outcome == "unsupported"
    assert "build version not provided" in notifier.actionable[-1][1]
    assert not ado.triggered                 # build never triggered
    assert db.updates[-1][1] == KNOWN_UNSUPPORTED


# ---------------------------------------------------------------------------
# Bug 5: auto-incrementing build version (0.3.0, 0.3.1, ...)
# ---------------------------------------------------------------------------
def test_next_aznfs_version_increments_and_persists(tmp_path):
    state = tmp_path / "aznfs_version.txt"
    # First three triggers hand out the start version then successive patches.
    assert next_aznfs_version(str(state), start="0.3.0") == "0.3.0"
    assert next_aznfs_version(str(state), start="0.3.0") == "0.3.1"
    assert next_aznfs_version(str(state), start="0.3.0") == "0.3.2"
    # The file holds the NEXT version to hand out.
    assert state.read_text().strip() == "0.3.3"
    # 0.3.9 -> 0.3.10 (numeric patch bump, not lexical).
    state.write_text("0.3.9\n")
    assert next_aznfs_version(str(state)) == "0.3.9"
    assert state.read_text().strip() == "0.3.10"


def test_build_consumes_injected_version_provider():
    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    # Gate 3 empty, then the freshly built 0.3.7 package becomes visible.
    package_index = FakePackageIndex(files=["aznfs_0.3.7_amd64.deb"], reveal_after=1)
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()

    calls = []

    def provider():
        calls.append(1)
        return "0.3.7"

    r = process_entry(entry(), idx, _esrp_onboarding(), package_index, db, notifier,
                      CSV_COVERS_NOBLE, "ignored", ado=ado,
                      version_provider=provider, sleep=fc.sleep, clock=fc)
    assert r.outcome == "published"
    assert len(calls) == 1                       # version consumed exactly once per build
    assert ado.triggered[0]["versionName"] == "0.3.7"   # provider value, not 'ignored'
    assert r.lisa_job["variant_name"] == "0.3.7"


def test_run_phase2_uses_injected_version_provider(tmp_path):
    import json

    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=["aznfs_0.3.0_amd64.deb"], reveal_after=1)
    ado = FakeAdoBuild(states=[("completed", "succeeded")])
    db = FakeDb()
    notifier = FakeNotifier()
    fc = FakeClock()
    out = tmp_path / "lisa_jobs.json"

    jobs = run_phase2(
        entries=[entry()],
        repo_index=idx,
        onboarding=_esrp_onboarding(),
        package_index=package_index,
        db=db,
        notifier=notifier,
        packages_tux_csv_text=CSV_COVERS_NOBLE,
        aznfs_version="ignored",
        ado=ado,
        lisa_jobs_path=str(out),
        version_provider=lambda: "0.3.0",
        sleep=fc.sleep,
        clock=fc,
    )
    assert len(jobs) == 1
    assert ado.triggered[0]["versionName"] == "0.3.0"
    written = json.loads(out.read_text())
    assert written[0]["newly_published"] is True


def test_run_phase2_writes_lisa_jobs_and_dispatches(tmp_path):
    import json

    idx = RepoIndex(apt=frozenset({"microsoft-ubuntu-noble"}), yum=frozenset())
    package_index = FakePackageIndex(files=["aznfs_0.3.2_amd64.deb"])  # < TRUST_BELOW_VERSION -> trusted
    db = FakeDb()
    notifier = FakeNotifier()
    out = tmp_path / "lisa_jobs.json"

    jobs = run_phase2(
        entries=[entry()],
        repo_index=idx,
        onboarding=_esrp_onboarding(),
        package_index=package_index,
        db=db,
        notifier=notifier,
        packages_tux_csv_text="",
        aznfs_version="0.3.10",
        lisa_jobs_path=str(out),
    )
    assert len(jobs) == 1
    written = json.loads(out.read_text())
    assert written[0]["distro_label"] == "Ubuntu 24.04"
    assert notifier.summaries[-1][0] == 1                 # processed
    assert "Ubuntu 24.04" in notifier.summaries[-1][2]    # to_phase3 list
