# Workflow: Phase 1 Marketplace Scan

## End-to-End Flow

1. **Start job**
   - Canonical daily trigger: the systemd timer on the runner VM
     (`deploy/aznfs-scan-trigger.timer`) dispatches the workflow at
     01:23 UTC sharp via `workflow_dispatch`.
   - Backup trigger: the GitHub `cron` (`23 1 * * *`). GitHub's hosted
     scheduler fires it hours late at unpredictable times, so a `precheck`
     job skips the cron run whenever a scan already ran that UTC day —
     it only proceeds if the VM timer failed to dispatch.
   - Manual trigger: `workflow_dispatch` from the Actions UI always runs.

2. **Restore DB state**
   - GitHub Actions restores `marketplace.db` cache if available.

3. **Run scan script**
   - Script ensures schema exists.
   - Script loops through region x publisher x offer x sku x version.

4. **Compare with local DB**
   - If tuple `(publisher, image, sku, version, region)` does not exist:
     - insert row
     - set `validated='unknown'`
     - append row to `needs_validation.json`
   - Else:
     - update `last_checked`

5. **Generate output JSON**
   - `output/needs_validation.json` contains only new rows.

6. **Notify by email (if new rows exist)**
   - Workflow composes a markdown table and emails recipients.

7. **Persist state for next run**
   - Updated `marketplace.db` is cached for future diffs.

## Why this works

- SQLite gives deterministic local state for change detection.
- Unique constraint prevents duplicates.
- JSON output provides clean handoff to downstream validation phase.
- Email alerts reduce latency for triage when new distro images appear.
