# Phase 3 — Automatic run (end-to-end)

How Phase 3 runs **with no human in the loop**, from a new distro image to a
recorded support decision and a team notification.

This complements [`../docs/PHASE3.md`](../docs/PHASE3.md) (the test plan and the
manual/local commands). Here we describe the **automated** scenario: what
triggers it, what runs, and what comes out.

---

## 1. Where Phase 3 sits in the pipeline

```mermaid
flowchart LR
    P1["Phase 1<br/>scan marketplace<br/>→ needs_validation.json"]
    P2["Phase 2<br/>publish AzNFS to PMC tux-dev<br/>→ jobs.json (image + URL + version + repo)"]
    P3["Phase 3<br/>validate + decide<br/>→ DB update + notify"]
    P1 --> P2 --> P3
```

Phase 3's **input** is Phase 2's `jobs.json`; its **output** is an updated
`images` table (`known_supported` / `known_unsupported`, `last_validated`,
`pmc_prod_state`) plus notifications. Publishing to PMC **prod stays manual** —
Phase 3 only validates and reports the gap.

---

## 2. The automatic Phase 3 flow

```mermaid
flowchart TD
    A["jobs.json<br/>(Phase 2 output)"] --> B{"run_phase3.py<br/>driver"}
    B -->|per distro| C["lisa run<br/>aznfs_validation.yml<br/>concurrency:3, per-env RG"]
    C --> D["lisa.junit.xml<br/>(machine-readable results)"]
    D --> E{"all cases<br/>passed?"}
    E -->|yes| F["job.lisa_passed = true"]
    E -->|no| G["job.lisa_passed = false"]
    F --> H["orchestrator.run()"]
    G --> H
    H --> I["Gate 1: prod repo defined?"]
    I --> J["Gate 2: repo config OK?<br/>(repo_groups, esrp, signing)"]
    J --> K["Gate 3: package on prod?"]
    K --> L["update images table<br/>+ notify team"]
```

Three moving parts, all already in this folder:

| Part | File | Role |
|------|------|------|
| **Driver** | [`run_phase3.py`](run_phase3.py) | Sequences the whole flow |
| **LISA suite + runbook** | [`testsuites/`](testsuites), [`runbooks/aznfs_validation.yml`](runbooks/aznfs_validation.yml) | Provision VM, install, validate (5 tiers) |
| **Orchestrator** | [`orchestrator/pmc_prod_check.py`](orchestrator/pmc_prod_check.py) | PMC prod gates, DB update, notifications |

### Step by step

1. **Read** Phase 2's `jobs.json` (one entry per distro: image URN, published
   package URL + version, PMC repo, arch).
2. **Validate** each distro: the driver runs `lisa run` on the base runbook with
   `-v` overrides. All 3 cases run **in parallel** (`concurrency:3`), each in its
   **own auto-deleted resource group** (empty `resource_group_name`). The
   `junit` notifier writes `lisa.junit.xml`.
3. **Score**: the driver parses that XML — a distro **passes** when it has at
   least one executed case and **zero** failures.
4. **Decide + report**: results go to `orchestrator.run()`, which for each passed
   distro applies the three PMC-prod gates, writes the outcome to the DB, and
   notifies the team. A failed distro is marked `known_unsupported`.
5. **Exit code**: `0` only if every distro passed validation — so CI can gate on
   it.

---

## 3. Running it

```bash
# from the repo root, with the LISA venv active and `az login` done
python -m phase3.run_phase3 path/to/jobs.json \
  --subscription-id 8ffe006d-4aa2-4eb6-bc3c-f33092ef804a \
  --concurrency 3 \
  --max-parallel-distros 4
```

- `--concurrency 3` — the 3 cases of **one** distro run at once (~17 min wall
  clock instead of ~50).
- `--max-parallel-distros 4` — up to 4 **distros** validate simultaneously. VMs
  in flight ≈ `max_parallel_distros × concurrency × 1`; each is 2 vCPUs, so bound
  this by your regional vCPU quota (e.g. 4 × 3 = 12 VMs = 24 vCPUs).

An example input is in [`examples/jobs.example.json`](examples/jobs.example.json).

> The driver runs each distro as its own `lisa run` for **simple, reliable
> result attribution** (one junit file per distro). The
> [`runbooks/aznfs_multidistro.yml`](runbooks/aznfs_multidistro.yml) `batch`
> combinator is the alternative single-run form (all distros in one LISA
> process) used for manual multi-distro runs.

---

## 4. What triggers it (scheduling)

Phase 3 is a batch job, triggered however Phases 1–2 are. Typical options:

- **Scheduled CI** (Azure DevOps pipeline / GitHub Actions cron): nightly or on
  a Phase 2 completion event, run the three phases in sequence; Phase 3's last
  step is `python -m phase3.run_phase3 jobs.json --subscription-id ...`.
- **Event/artifact chained**: Phase 2 publishes `jobs.json` as a pipeline
  artifact; a Phase 3 stage consumes it.

Minimal CI stage (illustrative):

```yaml
- stage: phase3_validate
  jobs:
    - job: validate
      steps:
        - script: |
            python -m pip install -e '.[azure]'   # LISA engine
            az login --identity                    # pipeline managed identity
            python -m phase3.run_phase3 "$(Pipeline.Workspace)/jobs.json" \
              --subscription-id "$(SUBSCRIPTION_ID)" \
              --concurrency 3 --max-parallel-distros 6
```

### Auth in automation

- **Azure** (deploy test VMs): the runner's **managed identity** — the runbook
  already uses `credential.type: default`, which picks up the pipeline identity;
  no keys in the runbook.
- **ADO read** (Gate 1, reading the prod repo definition from
  Compute-PMC.Onboarding): also the managed identity (see
  `orchestrator/config.py` `ADO_*`).

---

## 5. What you get out

- **DB**: each distro's `images` row updated — `known_supported` /
  `known_unsupported`, `last_validated`, and `pmc_prod_state` (one of
  `repo_missing` / `config_failed` / `package_missing` / `package_found`). See
  [`orchestrator/schema_phase3.sql`](orchestrator/schema_phase3.sql).
- **Notifications**: one message per distro outcome, plus a run summary.
- **Artifacts**: each distro's LISA run dir (console log, HTML report,
  `lisa.junit.xml`) under `runtime/log/...`.
- **Exit code**: non-zero if any distro failed validation (for CI gating).

---

## 6. Scaling notes (from real runs)

- Most of a run is idle VM **boot** time, so distro-level and case-level
  parallelism is what cuts wall-clock — not faster code. A 6-environment run
  completed in ~18 min versus ~100 min serial.
- The real ceiling is the subscription's **regional vCPU quota** (and, for the
  share-mounting tiers, storage-account limits), not time.
- Slow first boots in some regions are the main flake source; the engine SSH
  timeouts were raised to tolerate them. A pre-baked image (Shared Image
  Gallery) or a faster region removes most of that wait.
