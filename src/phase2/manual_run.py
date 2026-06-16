#!/usr/bin/env python3
"""
Manual, side-effect-free gate runner for Phase 2 (src/phase2 codebase).

Drives Gate 1 -> Gate 2 -> Gate 3 -> Gate 4 for one or more Phase 1 entries and
prints each gate's decision, reusing the orchestrator's *real* functions so the
manual trace matches what run_phase2() would do. It NEVER writes the database
and NEVER sends notifications (it injects print-only fakes), and it stops before
any build/publish.

It runs with PARTIAL or NO live access:

  Gate 1  needs the tux-dev repo *listing* (RepoIndex). Offline: pass
          --apt-repos / --yum-repos, or --use-fixture-index. Live: --live-index
          (corp network).
  Gate 2  reads repo config (signing_service/groups) from onboarding YAMLs.
          Offline: --local-yaml DIR. Live: --live-onboarding (ADO access).
  Gate 3  reads the tux-dev *package* directory. Offline: --published "a,b" or
          --published-empty. Live: --live-index (corp network).
  Gate 4  reads packages.tux.csv text. Pass --csv-file PATH (or it is skipped).

Examples:
  # Fully offline trace of one Ubuntu entry:
  python -m src.phase2.manual_run --label "Ubuntu 24.04" \
      --use-fixture-index --local-yaml ./sample_yaml --published-empty \
      --csv-file ./packages.tux.csv --aznfs-version 0.3.10

  # Live (corp network + ADO) trace of the first entry:
  python -m src.phase2.manual_run --index 0 --live-index --live-onboarding \
      --csv-file ./packages.tux.csv --aznfs-version 0.3.10
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

# Make `src.phase2` importable whether run as a module or as a script.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.phase2 import orchestrator, tux_packages  # noqa: E402
from src.phase2.repo_index import RepoIndex  # noqa: E402
from src.phase2.onboarding_client import _norm, _short_name  # noqa: E402


# ---------------------------------------------------------------------------
# Offline fakes (mirror the injected-dependency surface; print, never mutate).
# ---------------------------------------------------------------------------
class PrintDb:
    def set_validation_state(self, identity, validated, reason, date_added):
        print(f"    [db] would set {identity} -> {validated} (reason={reason!r})")


class PrintNotifier:
    def notify_actionable(self, distro_label: str, message: str) -> None:
        print(f"    [notify:actionable] {distro_label}: {message}")

    def notify_trusted(self, distro_label: str, message: str) -> None:
        print(f"    [notify:trusted] {distro_label}: {message}")

    def notify_summary(self, processed: int, unsupported, to_phase3) -> None:
        print(f"    [notify:summary] processed={processed} "
              f"unsupported={unsupported} to_phase3={to_phase3}")


class LocalOnboarding:
    """get_repo_config() backed by a local directory of onboarding YAMLs."""

    def __init__(self, directory: str) -> None:
        self._index: dict[str, dict] = {}
        for root, _dirs, files in os.walk(directory):
            for name in files:
                if not name.lower().endswith((".yaml", ".yml")):
                    continue
                try:
                    with open(os.path.join(root, name), encoding="utf-8") as fh:
                        doc = yaml.safe_load(fh)
                except (OSError, yaml.YAMLError) as exc:
                    print(f"    ! could not parse {name}: {exc}")
                    continue
                if not isinstance(doc, dict):
                    continue
                keys = set()
                if doc.get("name"):
                    keys.add(_norm(str(doc["name"])))
                for p in doc.get("paths") or []:
                    keys.add(_norm(_short_name(str(p))))
                for key in keys:
                    if key:
                        self._index.setdefault(key, doc)

    def get_repo_config(self, repo_name: str) -> dict | None:
        return self._index.get(_norm(repo_name))


class ListPackageIndex:
    """list_packages() backed by a fixed filename list (offline Gate 3)."""

    def __init__(self, files: list[str]) -> None:
        self.files = list(files)

    def list_packages(self, repo: str, family: str) -> list[str]:
        ext = ".rpm" if family.lower() in {"yum", "rpm", "dnf"} else ".deb"
        return [n for n in self.files
                if n.lower().startswith("aznfs") and n.lower().endswith(ext)]


# ---------------------------------------------------------------------------
# Per-gate trace (mirrors orchestrator.process_entry, with prints)
# ---------------------------------------------------------------------------
def trace_entry(entry, repo_index, onboarding, package_index, csv_text, aznfs_version):
    label = entry.get("distro_label", "?")
    fam = entry.get("family", "")
    arch = (entry.get("architecture") or entry.get("arch") or "").lower()
    print("=" * 78)
    print(f"ENTRY: {label} [{fam}/{arch}] "
          f"{entry.get('publisher')}:{entry.get('image') or entry.get('offer')}")
    print("=" * 78)

    # Gate 1
    print("\n[GATE 1] tux-dev repo exists for this release?")
    g1 = orchestrator.gate1_evaluate(entry, repo_index)
    if not g1.passed:
        print(f"  STOP - unsupported: {g1.reason} ({g1.details})")
        return
    matched = g1.matched_repos or ([g1.resolved_repo] if g1.resolved_repo else [])
    print(f"  PASS - matched repos: {matched}")

    # Gate 2
    print("\n[GATE 2] repo configured right? (signing_service=esrp AND groups include shared)")
    repo_objects = {}
    for name in matched:
        cfg = onboarding.get_repo_config(name)
        print(f"    onboarding config for {name}: {cfg}")
        if cfg:
            repo_objects[name] = cfg
    g2 = orchestrator.gate2_evaluate(matched, repo_objects)
    if not g2.passed:
        print(f"  STOP - unsupported: {g2.reason} ({g2.details})")
        return
    repo_name = g2.resolved_repo or g1.resolved_repo or ""
    print(f"  PASS - using repo '{repo_name}'")

    # Gate 3
    print("\n[GATE 3] already published on tux-dev?")
    published = package_index.list_packages(repo_name, fam)
    want_arch = tux_packages.normalize_arch(arch, fam)
    print(f"  listed at {tux_packages.aznfs_dir_url(repo_name, fam)}")
    print(f"    files={published or '<none>'}  (want arch={want_arch})")
    matched_files = [f for f in published if tux_packages.file_arch(f, fam) == want_arch]
    if matched_files:
        best = max(matched_files,
                   key=lambda f: tux_packages.version_tuple(tux_packages.version_from_filename(f)))
        ver = tux_packages.version_from_filename(best)
        url = tux_packages.aznfs_dir_url(repo_name, fam) + best
        print(f"  TRUSTED - {best} (v{ver}); emit LISA job, skip build")
        print(f"    download_url={url}")
        return
    print("  CONTINUE - not yet published")

    # Gate 4
    print("\n[GATE 4] build matrix covers this distro/arch? (packages.tux.csv)")
    if not csv_text:
        print("  (no CSV provided; orchestrator would mark unsupported)")
        return
    if orchestrator._csv_covers(csv_text, label, arch, repo_name):
        print("  PASS - row exists; orchestrator returns 'to_phase3' (build happens elsewhere)")
    else:
        print("  STOP - unsupported: no packages.tux.csv row for this distro/arch/repo")


def build_repo_index(args) -> RepoIndex:
    if args.live_index:
        from src.phase2 import repo_index as ri
        print("Gate 1 source: LIVE tux-dev listing (corp network)")
        return ri.fetch()
    if args.use_fixture_index:
        from tests.fixtures.repo_index import INDEX
        print("Gate 1 source: test fixture INDEX")
        return INDEX
    apt = frozenset(s.strip() for s in (args.apt_repos or "").split(",") if s.strip())
    yum = frozenset(s.strip() for s in (args.yum_repos or "").split(",") if s.strip())
    print(f"Gate 1 source: explicit repos (apt={sorted(apt)}, yum={sorted(yum)})")
    return RepoIndex(apt=apt, yum=yum)


def build_onboarding(args):
    if args.live_onboarding:
        from src.phase2.onboarding_client import from_env
        print("Gate 2 source: LIVE onboarding YAMLs via ADO (needs ADO access)")
        return from_env()
    if args.local_yaml:
        print(f"Gate 2 source: LOCAL YAML dir '{args.local_yaml}'")
        return LocalOnboarding(args.local_yaml)
    print("Gate 2 source: NONE (no --local-yaml/--live-onboarding; Gate 2 will fail)")
    return LocalOnboarding(os.devnull if os.path.isdir(os.devnull) else ".__none__")


def build_package_index(args):
    if args.published_empty:
        print("Gate 3 source: forced EMPTY")
        return ListPackageIndex([])
    if args.published:
        files = [s.strip() for s in args.published.split(",") if s.strip()]
        print(f"Gate 3 source: LOCAL list {files}")
        return ListPackageIndex(files)
    if args.live_index:
        from src.phase2.tux_packages import from_env
        print("Gate 3 source: LIVE tux-dev package dir (corp network)")
        return from_env()
    print("Gate 3 source: forced EMPTY (default)")
    return ListPackageIndex([])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Manual Phase 2 gate runner (no side effects).")
    p.add_argument("--input", default="output/needs_validation.json",
                   help="Phase 1 needs_validation.json (default: output/needs_validation.json)")
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--index", type=int, default=0, help="entry index (default 0)")
    sel.add_argument("--label", help="run all entries with this exact distro_label")
    sel.add_argument("--all", action="store_true", help="run every entry")
    p.add_argument("--limit", type=int, default=1, help="max entries (default 1; 0 = no cap)")
    p.add_argument("--aznfs-version", default="0.3.10", help="AzNFS package version (default 0.3.10)")
    # Gate 1 (repo listing)
    p.add_argument("--apt-repos", help="comma list of apt repo names (offline Gate 1)")
    p.add_argument("--yum-repos", help="comma list of yum repo names (offline Gate 1)")
    p.add_argument("--use-fixture-index", action="store_true", help="use tests fixture RepoIndex")
    p.add_argument("--live-index", action="store_true", help="fetch live tux-dev listings (corp net)")
    # Gate 2 (onboarding)
    p.add_argument("--local-yaml", help="dir of onboarding YAMLs (offline Gate 2)")
    p.add_argument("--live-onboarding", action="store_true", help="read onboarding via ADO (needs access)")
    # Gate 3 (package dir)
    g3 = p.add_mutually_exclusive_group()
    g3.add_argument("--published", help="comma list of published filenames (offline Gate 3)")
    g3.add_argument("--published-empty", action="store_true", help="force Gate 3 to see no files")
    # Gate 4
    p.add_argument("--csv-file", help="local packages.tux.csv")
    args = p.parse_args(argv)

    repo_index = build_repo_index(args)
    onboarding = build_onboarding(args)
    package_index = build_package_index(args)
    csv_text = ""
    if args.csv_file:
        with open(args.csv_file, encoding="utf-8") as fh:
            csv_text = fh.read()
        print(f"Gate 4 source: '{args.csv_file}'")

    with open(args.input, encoding="utf-8") as fh:
        data = json.load(fh)
    if args.label:
        chosen = [e for e in data if e.get("distro_label") == args.label]
    elif args.all:
        chosen = list(data)
    else:
        chosen = [data[args.index]]
    if args.limit:
        chosen = chosen[: args.limit]
    print(f"Running {len(chosen)} entr{'y' if len(chosen) == 1 else 'ies'} from {args.input}\n")

    for entry in chosen:
        trace_entry(entry, repo_index, onboarding, package_index, csv_text, args.aznfs_version)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
