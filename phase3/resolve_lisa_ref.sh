#!/usr/bin/env bash
# Print the commit a LISA ref points at, so a run can name the exact engine it
# used rather than a moving branch.
#
# Accepts a branch, a tag or a commit SHA. Anything else is an error here --
# a typoed ref used to sail through and surface much later as a confusing pip
# clone failure.
#
#   resolve_lisa_ref.sh <repo-url> <ref>
set -euo pipefail

REPO="${1:?usage: resolve_lisa_ref.sh <repo-url> <ref>}"
REF="${2:?usage: resolve_lisa_ref.sh <repo-url> <ref>}"

# A ref that does not exist is not an error here -- ls-remote exits 0 with empty
# output -- so let a real failure (unreachable host, no access) surface as one
# instead of being reported below as a bad ref.
REFS=$(git ls-remote "$REPO" "refs/heads/$REF" "refs/tags/$REF" "refs/tags/$REF^{}")

# An annotated tag resolves to the tag object, not the commit; the ^{} entry is
# the commit it wraps, so prefer that when it exists. A miss is normal here, so
# grep's exit status must not trip pipefail.
SHA=$(printf '%s\n' "$REFS" | grep -F "refs/tags/$REF^{}" | cut -f1 | head -1 || true)
[ -n "$SHA" ] || SHA=$(printf '%s\n' "$REFS" | cut -f1 | head -1 || true)

if [ -z "$SHA" ]; then
  if printf '%s' "$REF" | grep -Eq '^[0-9a-fA-F]{7,40}$'; then
    SHA="$REF"
  else
    echo "ERROR: '$REF' is not a branch, tag or commit SHA in $REPO" >&2
    exit 1
  fi
fi

# Canonical lowercase, so the installed URL and the recorded SHA always match.
printf '%s\n' "$SHA" | tr '[:upper:]' '[:lower:]'
