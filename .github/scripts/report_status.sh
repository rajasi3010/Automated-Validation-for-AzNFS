#!/usr/bin/env bash
# Render the validation status into the run's Actions summary, as Phase 3's
# result report. Nothing is committed or pushed: master is protected, so a push
# from CI is rejected outright, and the status-page branch it used to push to
# went stale whenever a run failed before reaching it. Never fails the run.
set -uo pipefail

DB="${DB_PATH:-marketplace.db}"
if [ ! -s "$DB" ]; then
  echo "No database at $DB; skipping the status report."
  exit 0
fi

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "::warning::No python interpreter found; skipping the status report"
  exit 0
fi
if ! "$PY" scripts/query_status.py --db "$DB" --format markdown --out STATUS.md; then
  echo "::warning::Could not generate the status report"
  exit 0
fi

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  # An earlier step may have left the summary without a trailing newline.
  printf '\n\n' >> "$GITHUB_STEP_SUMMARY"
  cat STATUS.md >> "$GITHUB_STEP_SUMMARY"
  echo "Status report written to the run summary."
else
  cat STATUS.md
fi
