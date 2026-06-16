"""Phase 2 orchestration helpers for Gate 1..4 decisions.

This module keeps external effects injectable (DB, notifier, onboarding,
package index, ADO build client) so it is easy to test and wire into
CLI/workflow code later. Gates 1-4 plus the build->poll->verify publish step
all live here: the Gate 1/2 evaluators below, Gate 3/4 and the build inside
``process_entry``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from . import tux_packages
from .repo_index import RepoIndex

logger = logging.getLogger(__name__)


KNOWN_SUPPORTED = "known_supported"
KNOWN_UNSUPPORTED = "known_unsupported"

# Build / publish-visibility policy (env-overridable; defaults per the spec).
TARGET_ENV = os.environ.get("TARGET_ENV", "tuxdev")
BUILD_POLL_INTERVAL = int(os.environ.get("BUILD_POLL_INTERVAL", str(10 * 60)))   # 600s
BUILD_TIMEOUT = int(os.environ.get("BUILD_TIMEOUT", str(2 * 60 * 60)))           # 2h
VISIBILITY_RETRIES = int(os.environ.get("VISIBILITY_RETRIES", "5"))
VISIBILITY_BACKOFF = int(os.environ.get("VISIBILITY_BACKOFF", "30"))
RESULT_SUCCEEDED = "succeeded"

# AzNFS build version: starts at AZNFS_START_VERSION and auto-increments by one
# patch level on every pipeline trigger (0.3.0 -> 0.3.1 -> 0.3.2 -> ...). The
# counter is persisted in AZNFS_VERSION_STATE, which holds the NEXT version to
# hand out.
AZNFS_START_VERSION = os.environ.get("AZNFS_START_VERSION", "0.3.0")
AZNFS_VERSION_STATE = os.environ.get("AZNFS_VERSION_STATE", "output/aznfs_version.txt")

# Gate 3 trust checkpoint: a published aznfs version strictly BELOW this is
# accepted as-is (trusted -> skip the build); a version at/above it is rebuilt
# through Gate 4 so the newer package goes through the full validation pipeline.
TRUST_BELOW_VERSION = os.environ.get("TRUST_BELOW_VERSION", "0.3.10")


class OnboardingLike(Protocol):
    """Source of a tux-dev repo's onboarding config (signing_service/groups)."""
    def get_repo_config(self, repo_name: str) -> dict | None: ...


class PackageIndexLike(Protocol):
    """Lists aznfs package filenames published in a tux-dev repo directory."""
    def list_packages(self, repo: str, family: str) -> list[str]: ...


class AdoLike(Protocol):
    def ping(self, client_id: str | None = None) -> bool: ...
    def trigger_run(self, params: dict) -> str: ...
    def get_run_status(self, run_id: str) -> tuple[str, str | None]: ...


class DbLike(Protocol):
    def set_validation_state(
        self,
        identity: tuple[str, str, str, str, str],
        validated: str,
        reason: str | None,
        date_added: str,
    ) -> None: ...


class NotifierLike(Protocol):
    def notify_actionable(self, distro_label: str, message: str) -> None: ...
    def notify_trusted(self, distro_label: str, message: str) -> None: ...
    def notify_summary(self, processed: int, unsupported: list[str], to_phase3: list[str]) -> None: ...


@dataclass
class Phase2Result:
    outcome: str  # unsupported | trusted | published | to_phase3
    reason: str = ""
    lisa_job: dict | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _identity(entry: dict) -> tuple[str, str, str, str, str]:
    return (
        entry.get("publisher", ""),
        entry.get("image") or entry.get("offer") or "",
        entry.get("sku", ""),
        entry.get("region", ""),
        entry.get("architecture") or entry.get("arch") or "",
    )


def _version_below_threshold(version: str, threshold: str | None = None) -> bool:
    """True when ``version`` is strictly below ``threshold`` (numeric compare).

    ``threshold`` defaults to the module-level ``TRUST_BELOW_VERSION`` (read at
    call time). An empty version compares as below any real threshold, so callers
    that care about the empty case guard it explicitly.
    """
    if not version:
        return True
    threshold = threshold or TRUST_BELOW_VERSION
    return tux_packages.version_tuple(version) < tux_packages.version_tuple(threshold)


def _bump_patch(version: str) -> str:
    """Increment the last numeric component of a dotted version ('0.3.0'->'0.3.1')."""
    parts = (version or "").strip().split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        return version
    return ".".join(parts)


def next_aznfs_version(path: str | None = None, start: str | None = None) -> str:
    """Return the version to use for this build and persist the next one.

    The counter file at ``path`` stores the NEXT version to hand out (initialised
    to ``start``). Each call returns the stored version and writes back its
    patch-incremented successor, so successive pipeline triggers get
    0.3.0, 0.3.1, 0.3.2, ...
    """
    path = path or AZNFS_VERSION_STATE
    start = start or AZNFS_START_VERSION
    current = start
    try:
        with open(path, encoding="utf-8") as fh:
            stored = fh.read().strip()
        if stored:
            current = stored
    except FileNotFoundError:
        current = start
    nxt = _bump_patch(current)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(nxt + "\n")
    logger.info("AzNFS build version %s (next -> %s) [%s]", current, nxt, path)
    return current


def _csv_token_family(token: str) -> str:
    """Package manager implied by a packages.tux.csv column-2 token (apt|yum)."""
    return "yum" if "rpm" in token.lower() else "apt"


def _csv_token_arch(token: str) -> str:
    """Architecture implied by a packages.tux.csv column-2 token (x86_64|arm64)."""
    t = token.lower()
    return "arm64" if ("arm" in t or "arc" in t) else "x86_64"


def _csv_norm_distro(name: str) -> str:
    """Normalise a distro name for comparison: lower, hyphenated, no trailing .0."""
    s = (name or "").strip().lower().replace(" ", "-").replace("_", "-")
    return re.sub(r"\.0$", "", s)


def _csv_covers(csv_text: str, distro_label: str, arch: str, family: str) -> bool:
    """True when packages.tux.csv has a build-matrix row for this distro + arch.

    The real packages.tux.csv columns are
    ``<Distro Name>,<build-recipe token>,<Repo Name>,<Release Name>`` where
    column 2 is a recipe token (aznfsDeb / aznfsArm / aznfsRpm / aznfsArcRpm /
    ...), NOT a literal arch string. Match column 1 on the distro name and decode
    column 2 to BOTH the package manager (apt/yum) and the architecture
    (x86_64/arm64): "Arm"/"Arc" => arm64, "Rpm" => yum.
    """
    if not csv_text:
        return False
    key = _csv_norm_distro(distro_label)
    if not key:
        return False
    want_pm = "yum" if (family or "").strip().lower() in {"yum", "rpm", "dnf"} else "apt"
    want_arch = "arm64" if (arch or "").strip().lower() in {"arm64", "aarch64"} else "x86_64"
    for raw in csv_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 2 or not cells[1]:
            continue
        if _csv_norm_distro(cells[0]) != key:
            continue
        token = cells[1]
        if _csv_token_family(token) == want_pm and _csv_token_arch(token) == want_arch:
            return True
    return False


def _publisher_label_consistent(entry: dict) -> bool:
    pub = (entry.get("publisher") or "").strip().lower()
    lbl = (entry.get("distro_label") or "").strip().lower()
    if not pub or not lbl:
        return False
    if pub == "canonical":
        return lbl.startswith("ubuntu")
    if pub == "debian":
        return lbl.startswith("debian")
    if pub == "redhat":
        return lbl.startswith("rhel") or lbl.startswith("red hat") or lbl.startswith("redhat")
    if pub == "suse":
        return lbl.startswith("sles") or lbl.startswith("suse")
    return True


def preflight_checks(
    entries: list[dict],
    ado: AdoLike | None = None,
    ado_client_id: str | None = None,
    onboarding: OnboardingLike | None = None,
    package_index: PackageIndexLike | None = None,
) -> tuple[bool, str]:
    # 1) ADO connectivity check (when client is provided).
    if ado is not None:
        try:
            if not ado.ping(ado_client_id):
                return False, "preflight failed: ADO connectivity check failed"
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"preflight failed: ADO connectivity check error: {exc}"

    # 1b) Onboarding + tux-dev reachability (when clients expose ping()).
    for label, client in (("onboarding", onboarding), ("tux-dev package index", package_index)):
        if client is not None and hasattr(client, "ping"):
            try:
                if not client.ping():
                    return False, f"preflight failed: {label} connectivity check failed"
            except Exception as exc:  # pragma: no cover - defensive
                return False, f"preflight failed: {label} connectivity check error: {exc}"

    # 2) Distro/Publisher validation checks.
    required = {"publisher", "distro_label", "family", "sku", "version", "region"}
    for i, e in enumerate(entries):
        missing = [k for k in required if not e.get(k)]
        if missing:
            return False, f"preflight failed: entry[{i}] missing required fields: {missing}"
        if not (e.get("image") or e.get("offer")):
            return False, f"preflight failed: entry[{i}] requires image or offer"
        if not _publisher_label_consistent(e):
            return False, (
                f"preflight failed: entry[{i}] publisher/distro_label mismatch "
                f"({e.get('publisher')} vs {e.get('distro_label')})"
            )

    return True, ""


# ---------------------------------------------------------------------------
# Gate 1: does a tuxdev repo exist for this distro release?
# ---------------------------------------------------------------------------
_MAP_PATH = Path(__file__).with_name("distro_map.yaml")
_VER_RE = re.compile(r"(\d+)(?:\.(\d+))?")


@dataclass
class GateResult:
    passed: bool
    reason: str = ""
    details: str = ""
    resolved_repo: str | None = None
    matched_repos: list[str] | None = None


def load_map(path: Path = _MAP_PATH) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f)


def _parse_version(raw: str) -> dict[str, str]:
    m = _VER_RE.match(raw or "")
    if not m:
        return {}
    major, minor = m.group(1), (m.group(2) or "0")
    return {
        "major": major,
        "minor": minor,
        "mm":    f"{major}.{minor}",
        "ver4":  major.zfill(2) + minor.zfill(2),
    }


def _regex_from_candidate(name: str) -> re.Pattern:
    # Be separator-tolerant (dash/underscore/dot) across onboarding styles.
    tokenized = re.sub(r"[^a-z0-9]+", r"[-_.]*", (name or "").lower())
    return re.compile(rf"^{tokenized}$")


def gate1_evaluate(distro: dict, repo_index: RepoIndex, distro_map: dict | None = None) -> GateResult:
    """Gate 1: a tuxdev repo exists for this distro release."""
    distro_map = distro_map or load_map()
    publisher = (distro.get("publisher") or "").strip().lower()
    rule = distro_map.get(publisher)
    if not rule:
        return GateResult(False, "unmapped publisher", details=publisher)

    v = _parse_version(distro.get("version", ""))
    if not v:
        return GateResult(False, "unparseable version", details=str(distro.get("version")))

    if rule["version_style"] == "codename":
        cn = rule["codenames"].get(v["mm"]) or rule["codenames"].get(v["major"])
        if not cn:
            return GateResult(False, "unmapped distro version",
                              details=f"{publisher} {v['mm']}")
        v["codename"] = cn

    candidates = [t.format(**v) for t in rule["name_templates"]]
    # Numeric aliases can be present without codename (e.g. ubuntu-2604).
    if publisher == "canonical":
        candidates.extend([
            f"microsoft-ubuntu-{v['ver4']}",
            f"microsoft-ubuntu-{v['mm']}",
        ])
    elif publisher == "debian":
        candidates.append(f"microsoft-debian-{v['major']}")

    # Stable de-dup preserving order.
    candidates = list(dict.fromkeys(candidates))

    existing = repo_index[rule["index"]]
    matches: list[str] = []
    for c in candidates:
        if c in existing:
            matches.append(c)
            continue
        pat = _regex_from_candidate(c)
        for repo in existing:
            if pat.match(repo.lower()):
                matches.append(repo)

    matches = list(dict.fromkeys(matches))
    if matches:
        return GateResult(True, resolved_repo=matches[0], matched_repos=matches)
    return GateResult(False, "tuxdev repo missing", details=",".join(candidates))


# ---------------------------------------------------------------------------
# Gate 2: among Gate-1 hits, pick a repo configured for publish
# (signing_service == esrp AND groups include "shared").
# ---------------------------------------------------------------------------
def _signing_service(repo: dict) -> str | None:
    return repo.get("signing_service") or repo.get("signingService")


def _repo_groups(repo: dict) -> set[str]:
    groups = repo.get("groups") or repo.get("repo_groups") or repo.get("repoGroups") or []
    return {str(g).strip().lower() for g in groups}


def gate2_evaluate(
    matched_repos: list[str],
    repo_objects: dict[str, dict],
    allowed_signing_services: set[str] | None = None,
    required_repo_groups: set[str] | None = None,
) -> GateResult:
    """Gate 2: a matched repo has signing_service=esrp and includes 'shared'."""
    allowed_signing_services = {s.lower() for s in (allowed_signing_services or {"esrp"})}
    required_repo_groups = {g.lower() for g in (required_repo_groups or {"shared"})}

    failures: list[str] = []
    for repo_name in matched_repos:
        repo = repo_objects.get(repo_name) or {}
        signing = (_signing_service(repo) or "").strip().lower()
        groups = _repo_groups(repo)

        signing_ok = signing in allowed_signing_services
        groups_ok = bool(groups & required_repo_groups)
        if signing_ok and groups_ok:
            return GateResult(True, resolved_repo=repo_name)

        failures.append(f"{repo_name}: signing_service={signing!r}, repo_groups={sorted(groups)}")

    return GateResult(
        False,
        reason="repo config mismatch",
        details=(
            f"Need signing_service in {sorted(allowed_signing_services)} and repo_groups "
            f"including one of {sorted(required_repo_groups)}. Checked: {'; '.join(failures)}"
        ),
    )


# ---------------------------------------------------------------------------
# LISA job + build->poll->verify + Phase 3 hand-off
# ---------------------------------------------------------------------------
def _make_lisa_job(
    entry: dict,
    distro_label: str,
    repo_name: str,
    family: str,
    package_filename: str,
    resolved_version: str,
    newly_published: bool,
) -> dict:
    """Assemble the Phase 3 LISA job entry for a (to-be-)published package."""
    return {
        "distro_info": {
            "distro_label": distro_label,
            "publisher": entry.get("publisher"),
            "offer": entry.get("image") or entry.get("offer"),
            "sku": entry.get("sku"),
            "image_version": entry.get("version"),
            "region": entry.get("region"),
            "arch": entry.get("architecture") or entry.get("arch"),
        },
        "distro_label": distro_label,
        "publisher": entry.get("publisher"),
        "offer": entry.get("image") or entry.get("offer"),
        "sku": entry.get("sku"),
        "image_version": entry.get("version"),
        "region": entry.get("region"),
        "arch": entry.get("architecture") or entry.get("arch"),
        "repository": repo_name,
        "package_filename": package_filename,
        "aznfs_version": resolved_version,
        "variant_name": resolved_version,
        "download_url": tux_packages.aznfs_dir_url(repo_name, family) + package_filename,
        "newly_published": newly_published,
    }


def _build_and_verify(
    repo_name: str,
    family: str,
    want_arch: str,
    aznfs_version: str,
    ado: AdoLike,
    package_index: PackageIndexLike,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> tuple[str | None, str]:
    """Trigger the AzNFS pipeline, poll to completion, then verify visibility.

    Returns ``(best_filename, "")`` once the freshly-built package is visible on
    tux-dev, or ``(None, reason)`` on build failure / timeout / not-visible.
    """
    if not (aznfs_version or "").strip():
        return None, "build version not provided (AZNFS_PACKAGE_VERSION is empty)"
    params = {"versionName": aznfs_version, "targetEnv": TARGET_ENV}
    run_id = ado.trigger_run(params)

    # Poll every BUILD_POLL_INTERVAL until completed or BUILD_TIMEOUT.
    deadline = clock() + BUILD_TIMEOUT
    while True:
        state, result = ado.get_run_status(run_id)
        if state == "completed":
            break
        if clock() >= deadline:
            return None, f"tux-dev pipeline failed: run {run_id} did not finish within {BUILD_TIMEOUT}s"
        sleep(BUILD_POLL_INTERVAL)

    if result != RESULT_SUCCEEDED:
        return None, f"tux-dev pipeline failed: run {run_id} ended '{result or 'failed'}'"

    # Build succeeded -- confirm the package actually became visible in the
    # tux-dev repo directory (handles publish-propagation lag).
    for attempt in range(VISIBILITY_RETRIES):
        published = package_index.list_packages(repo_name, family)
        matched = [f for f in published if tux_packages.file_arch(f, family) == want_arch]
        if matched:
            best = max(
                matched,
                key=lambda f: tux_packages.version_tuple(tux_packages.version_from_filename(f)),
            )
            return best, ""
        if attempt < VISIBILITY_RETRIES - 1:
            sleep(VISIBILITY_BACKOFF)
    return None, (
        f"pipeline succeeded but package not visible: run {run_id}, no aznfs "
        f"{want_arch} package after {VISIBILITY_RETRIES} checks"
    )


def write_lisa_jobs(jobs: list[dict], path: str) -> None:
    """Persist the run's LISA jobs as the Phase 3 hand-off artifact."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(jobs, fh, indent=2)
    logger.info("Wrote %d LISA job(s) -> %s", len(jobs), path)


def dispatch_phase3(jobs: list[dict]) -> None:
    """Hand the collected LISA jobs to Phase 3.

    The written ``lisa_jobs.json`` is the hand-off artifact; wiring the actual
    Phase 3 trigger (LISA workflow dispatch) is left to the workflow layer.
    """
    logger.info("Phase 3 hand-off: %d LISA job(s) ready", len(jobs))


def process_entry(
    entry: dict,
    repo_index: RepoIndex,
    onboarding: OnboardingLike,
    package_index: PackageIndexLike,
    db: DbLike,
    notifier: NotifierLike,
    packages_tux_csv_text: str,
    aznfs_version: str,
    ado: AdoLike | None = None,
    version_provider: Callable[[], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Phase2Result:
    """Run gates 1..4 (plus the build) for one entry and apply side-effects.

    Gate 1 fail        -> notify + known_unsupported
    Gate 2 fail        -> notify + known_unsupported
    Gate 3 hit         -> notify trusted + known_supported + emit LISA job
    Gate 4 miss        -> notify + known_unsupported
    Gate 4 pass, no ADO-> 'to_phase3' (build is triggered elsewhere)
    build fail/timeout -> notify + known_unsupported
    built + visible    -> notify + known_supported + emit LISA job ('published')
    """
    ts = _now_iso()
    ident = _identity(entry)
    distro_label = entry.get("distro_label", "")

    g1: GateResult = gate1_evaluate(entry, repo_index)
    if not g1.passed:
        reason = "tuxdev repo missing"
        notifier.notify_actionable(distro_label, reason)
        db.set_validation_state(ident, KNOWN_UNSUPPORTED, None, ts)
        return Phase2Result("unsupported", reason=reason)

    matched = g1.matched_repos or ([g1.resolved_repo] if g1.resolved_repo else [])
    repo_objects: dict[str, dict] = {}
    for name in matched:
        repo_cfg = onboarding.get_repo_config(name)
        if repo_cfg:
            repo_objects[name] = repo_cfg

    g2 = gate2_evaluate(matched, repo_objects)
    if not g2.passed:
        reason = "repo config mismatch"
        notifier.notify_actionable(distro_label, reason)
        db.set_validation_state(ident, KNOWN_UNSUPPORTED, None, ts)
        return Phase2Result("unsupported", reason=reason)

    repo_name = g2.resolved_repo or g1.resolved_repo or ""
    family = entry.get("family") or ""
    arch = (entry.get("architecture") or entry.get("arch") or "").lower()

    # Gate 3: is an aznfs package for this arch already published on tux-dev?
    published = package_index.list_packages(repo_name, family)
    want_arch = tux_packages.normalize_arch(arch, family)
    matched_files = [f for f in published if tux_packages.file_arch(f, family) == want_arch]
    if matched_files:
        best = max(
            matched_files,
            key=lambda f: tux_packages.version_tuple(tux_packages.version_from_filename(f)),
        )
        resolved_version = tux_packages.version_from_filename(best) or aznfs_version
        # Checkpoint (after Gate 3 match): a published version strictly BELOW
        # TRUST_BELOW_VERSION is accepted as-is (trusted -> skip the build); a
        # version at/above it is (re)built via Gate 4 so the newer package goes
        # through the full validation pipeline.
        if resolved_version and _version_below_threshold(resolved_version, TRUST_BELOW_VERSION):
            reason = "already published,trusted."
            notifier.notify_trusted(distro_label, reason)
            db.set_validation_state(ident, KNOWN_SUPPORTED, None, ts)
            lisa_job = _make_lisa_job(
                entry, distro_label, repo_name, family, best, resolved_version,
                newly_published=False,
            )
            return Phase2Result("trusted", reason=reason, lisa_job=lisa_job)
        logger.info(
            "Published %s at/above %s -- rebuilding via Gate 4: %s",
            resolved_version or "?", TRUST_BELOW_VERSION, distro_label,
        )

    # Gate 4: packages.tux.csv coverage
    if not _csv_covers(packages_tux_csv_text, distro_label, arch, family):
        reason = (
            "team must update packages.tux.csv + push branch + re-invoke Phase 2 "
            "with the new branch ref"
        )
        notifier.notify_actionable(distro_label, reason)
        db.set_validation_state(ident, KNOWN_UNSUPPORTED, None, ts)
        return Phase2Result("unsupported", reason=reason)

    # Gate 4 passed. Without an ADO client the build is triggered elsewhere
    # (e.g. the manual/offline flow) -- hand off as 'to_phase3'.
    if ado is None:
        return Phase2Result("to_phase3")

    # Build -> poll -> verify visibility on tux-dev. Each build consumes the next
    # auto-incrementing version (0.3.0, 0.3.1, ...) when a provider is injected;
    # otherwise it falls back to the explicit ``aznfs_version``.
    build_version = version_provider() if version_provider is not None else aznfs_version
    best, why = _build_and_verify(
        repo_name, family, want_arch, build_version, ado, package_index, sleep, clock,
    )
    if best is None:
        notifier.notify_actionable(distro_label, why)
        db.set_validation_state(ident, KNOWN_UNSUPPORTED, None, ts)
        return Phase2Result("unsupported", reason=why)

    resolved_version = tux_packages.version_from_filename(best) or build_version
    reason = "published, handing to Phase 3"
    notifier.notify_trusted(distro_label, reason)
    db.set_validation_state(ident, KNOWN_SUPPORTED, None, ts)
    lisa_job = _make_lisa_job(
        entry, distro_label, repo_name, family, best, resolved_version,
        newly_published=True,
    )
    return Phase2Result("published", reason=reason, lisa_job=lisa_job)


def run_phase2(
    entries: list[dict],
    repo_index: RepoIndex,
    onboarding: OnboardingLike,
    package_index: PackageIndexLike,
    db: DbLike,
    notifier: NotifierLike,
    packages_tux_csv_text: str,
    aznfs_version: str,
    ado: AdoLike | None = None,
    ado_client_id: str | None = None,
    lisa_jobs_path: str | None = None,
    version_provider: Callable[[], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[dict]:
    # Each pipeline trigger consumes the next auto-incrementing build version;
    # default to the persistent file-backed counter when no provider is injected.
    if version_provider is None:
        version_provider = next_aznfs_version
    ok, why = preflight_checks(
        entries, ado=ado, ado_client_id=ado_client_id,
        onboarding=onboarding, package_index=package_index,
    )
    if not ok:
        notifier.notify_actionable("PRE-FLIGHT", why)
        notifier.notify_summary(processed=0, unsupported=[], to_phase3=[])
        return []

    lisa_jobs: list[dict] = []
    unsupported: list[str] = []
    to_phase3: list[str] = []

    for e in entries:
        label = e.get("distro_label", "?")
        try:
            result = process_entry(
                e,
                repo_index,
                onboarding,
                package_index,
                db,
                notifier,
                packages_tux_csv_text,
                aznfs_version,
                ado=ado,
                version_provider=version_provider,
                sleep=sleep,
                clock=clock,
            )
        except Exception as exc:  # one image's failure never aborts the run
            logger.exception("Unexpected error processing %s", label)
            notifier.notify_actionable(label, f"orchestrator error (will retry next run): {exc}")
            continue

        if result.outcome == "unsupported":
            unsupported.append(label)
        elif result.outcome in ("trusted", "published"):
            if result.lisa_job:
                lisa_jobs.append(result.lisa_job)
            to_phase3.append(label)
        else:  # to_phase3 (build triggered elsewhere)
            to_phase3.append(label)

    if lisa_jobs_path:
        write_lisa_jobs(lisa_jobs, lisa_jobs_path)
    dispatch_phase3(lisa_jobs)
    notifier.notify_summary(processed=len(entries), unsupported=unsupported, to_phase3=to_phase3)
    return lisa_jobs
