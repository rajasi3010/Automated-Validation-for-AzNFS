# Phase 3 — LISA artifacts

These are the **authored LISA artifacts** for Phase 3 AzNFS validation. LISA
loads them straight from this repo -- the runbook's `extension:` path points at
`testsuites/`, so nothing is copied anywhere and this is the only source of
truth. The engine itself ([Azure/azfiles-lisa](https://github.com/Azure/azfiles-lisa))
is installed as an ordinary pinned package by `setup_lisa.sh`; there is no
engine checkout.

See [`../docs/PHASE3.md`](../docs/PHASE3.md) for the full test plan.

## Contents

| File | What it is |
|------|------------|
| `testsuites/aznfs_validation.py` | The `AzNfsValidation` LISA test suite (3 cases, 5 tiers) |
| `testsuites/_lisa_fixes.py` | Fixes applied to the engine at import time (see below) |
| `testsuites/__init__.py` | Package marker |
| `runbooks/aznfs_validation.yml` | LISA runbook (platform + `aznfs_*` inputs) |
| `orchestrator/` | Records the verdict in the DB + sends one summary e-mail (not a LISA test) |
| `run_phase3.py` | **Automation driver**: lisa_jobs.json → LISA → record_result |
| `setup_lisa.sh` | Installs the engine + deps into the venv |
| `resolve_lisa_ref.sh` | Resolves a branch/tag/SHA to the commit to install |
| `AUTOMATION.md` | How Phase 3 runs end-to-end with no human in the loop |
| `examples/jobs.example.json` | Sample Phase 2 input for the driver |

See [`AUTOMATION.md`](AUTOMATION.md) for the automated end-to-end scenario.

## Fixes carried against the engine

`testsuites/_lisa_fixes.py` patches LISA at import time (LISA imports every
module under the extension path). Today it defaults storage accounts to
`allow_shared_key_access=True`, without which `Nfs.create_share` cannot list the
account keys and every NFS test fails before it mounts anything.

Keeping it here rather than editing an engine checkout means it is in version
control, survives every reinstall, and cannot be lost when the engine updates.

## Test cases

| Case | Tiers | Needs a share |
|------|-------|---------------|
| `verify_aznfs_install_lifecycle` | 1–3 (artifact, install, footprint) | No |
| `verify_aznfs_nfs_functional` | 4 (mount + simple I/O, EIT off/on) | Yes |
| `verify_aznfs_resilience` | 5 (watchdog restart) | Yes |

## Run (from a LISA checkout, on WSL/Linux)

```bash
lisa run -r runbooks/aznfs_validation.yml \
  -v subscription_id:<sub> \
  -v marketplace_image:"RedHat:RHEL:9_5:latest" \
  -v aznfs_package_url:"https://packages.microsoft.com/rhel/9.0/prod/Packages/a/aznfs-0.3.458-1.x86_64.rpm" \
  -v aznfs_expected_version:"0.3.458"
```

Run a single case with `-v case_name:verify_aznfs_install_lifecycle` (the
`name` criteria is a regex fullmatch; the lifecycle case needs no Azure share,
so it is the cheapest to start with). See [`../docs/PHASE3.md`](../docs/PHASE3.md)
for parallel and multi-distro runs, and [`AUTOMATION.md`](AUTOMATION.md) for the
fully automated driver.

## Notes

- AzNFS names/paths (`aznfs`, `aznfswatchdog`, `mount.aznfs`) and the exact
  mount/EIT options are **runbook variables**, not hardcoded — confirm with the
  team and override via `-v` without editing code.
- Install is **prod URL first**, **PMC repo fallback**. Tier 1 artifact
  checks only run when a package URL is provided (you can only inspect a file
  you downloaded).
- Non-RPM/DEB distros are **skipped**, not failed.
