#!/usr/bin/env bash
# Render the validation status into the run's Actions summary, as Phase 3's
# result report. Nothing is committed or pushed: master is protected, so a push
# from CI is rejected outright, and the `permissions:` block a job needs to push
# elsewhere costs it the ability to save the marketplace.db cache -- which is
# what silently discarded every verdict Phase 3 produced. Never fails the run.
set -uo pipefail

DB="${DB_PATH:-marketplace.db}"
if [ ! -s "$DB" ]; then
  echo "No database at $DB; skipping the status report."
  exit 0
fi

PY="$(command -v python3 || command -v python)"
if ! "$PY" scripts/query_status.py --db "$DB" --format markdown --out STATUS.md; then
  echo "::warning::Could not generate the status report"
  exit 0
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  cat STATUS.md >> "$GITHUB_STEP_SUMMARY"
  echo "Status report written to the run summary."
else
  cat STATUS.md
fi
