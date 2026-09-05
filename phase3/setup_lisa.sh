#!/usr/bin/env bash
# Phase 3 - install / refresh the LISA engine on a runner (idempotent).
#
# Sets up everything the Phase 3 GitHub Actions workflow (phase3-validate.yml)
# needs on the self-hosted runner so `python -m phase3.run_phase3` can drive
# `lisa run`:
#
#   1. system build deps (apt)               -- needs sudo; skipped if missing
#   2. a Python venv at LISA_VENV            -- created if absent
#   3. the LISA engine, pip-installed from the resolved commit (no checkout)
#   4. the project's own requirements        -- so the in-venv driver + ACS
#                                               e-mail notifier work too
#   5. a smoke check                         -- `lisa --help` resolves
#
# Re-runnable: reinstalling is idempotent, existing venv reused. Override any of the
# paths/refs via env vars (defaults match the workflow's LISA_VENV default).
#
#   LISA_VENV   venv dir            (default: $HOME/lisa-venv)
#   LISA_REPO   engine git URL      (default: https://github.com/Azure/azfiles-lisa.git)
#   LISA_REF    engine branch/SHA   (default: main -- resolved to a SHA per run)
#   REQUIREMENTS  project reqs file (default: autodetected from repo root)
#
# The engine is installed as an ordinary package straight from git -- no source
# checkout is kept, so there is nothing on the runner to hand-edit and nothing
# that can drift unnoticed. Fixes we carry against it live in
# phase3/testsuites/_lisa_fixes.py, which LISA loads as a runbook extension.
#
# Usage (on the runner):
#   bash phase3/setup_lisa.sh
set -euo pipefail

LISA_VENV="${LISA_VENV:-$HOME/lisa-venv}"
LISA_REPO="${LISA_REPO:-https://github.com/Azure/azfiles-lisa.git}"
# Follows upstream main so engine fixes arrive without anyone chasing them. Set
# LISA_REF to a SHA (env or the LISA_REF repo variable) to freeze it -- worth
# doing while chasing a regression, so the engine stops moving under you.
LISA_REF="${LISA_REF:-main}"

# LISA + its deps are public packages: pin pip to public PyPI so a stray private
# feed (e.g. a leftover ~/.pip/pip.conf pointing at an auth-only Azure Artifacts
# feed) can't hijack the install with a 401. Override PIP_INDEX_URL to use a
# different index on purpose.
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple/}"

# Repo root = two levels up from this script (phase3/ -> repo root).
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_REPO_ROOT="$(cd "$_SCRIPT_DIR/.." && pwd)"
REQUIREMENTS="${REQUIREMENTS:-$_REPO_ROOT/requirements.txt}"

log() { printf '\n=== %s ===\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. System build dependencies (LISA's azure extra builds a few native wheels).
#    Best-effort: needs sudo; if unavailable we warn and continue (a CI image
#    may already have them baked in).
# ---------------------------------------------------------------------------
APT_PKGS=(git gcc libgirepository1.0-dev libcairo2-dev qemu-utils libvirt-dev
          python3-pip python3-venv unixodbc-dev pkg-config)
log "system deps (apt)"
if command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PKGS[@]}"
else
  echo "WARN: sudo/apt-get unavailable; assuming build deps already present."
fi

# ---------------------------------------------------------------------------
# 2. Python venv.
# ---------------------------------------------------------------------------
log "venv -> $LISA_VENV"
if [ ! -x "$LISA_VENV/bin/python" ]; then
  python3 -m venv "$LISA_VENV"
fi
# shellcheck disable=SC1091
source "$LISA_VENV/bin/activate"
python -m pip install --upgrade pip wheel

# ---------------------------------------------------------------------------
# 3. LISA engine: azure extra only (NOT libvirt), installed as an ordinary
#    package from a resolved commit -- not editable, no checkout left behind.
# ---------------------------------------------------------------------------
log "pip install LISA ($LISA_REPO @ $LISA_REF)"
# Resolve to the commit the ref points at RIGHT NOW and install that, so the run
# records exactly which engine it used. Installing "@main" would leave no way to
# tell afterwards whether the engine moved between two runs.
LISA_SHA=$(bash "$_SCRIPT_DIR/resolve_lisa_ref.sh" "$LISA_REPO" "$LISA_REF")
echo "$LISA_REF resolves to $LISA_SHA"
# Not editable, and no checkout left behind: pip builds from a temporary clone
# and installs the result. mslisa on PyPI is upstream LISA and lacks the Nfs
# feature this suite needs, so it has to come from the fork.
pip install --upgrade "mslisa[azure] @ git+${LISA_REPO}@${LISA_SHA}"

# ---------------------------------------------------------------------------
# 4. Project requirements (the driver runs in THIS venv and lazily imports the
#    Phase 1 ACS notifier, which needs azure-communication-email etc.).
# ---------------------------------------------------------------------------
if [ -f "$REQUIREMENTS" ]; then
  log "pip install project requirements ($REQUIREMENTS)"
  pip install -r "$REQUIREMENTS"
else
  echo "WARN: $REQUIREMENTS not found; skipping project requirements."
fi

# ---------------------------------------------------------------------------
# 5. Smoke check.
# ---------------------------------------------------------------------------
log "verify"
if ! lisa --help >/dev/null 2>&1; then
  # `cmd && echo` would NOT fail the script under set -e, letting an unusable
  # CLI through to fail later with far less context.
  echo "ERROR: the lisa CLI is not usable in $LISA_VENV" >&2
  exit 1
fi
echo "OK: lisa CLI resolves in $LISA_VENV"
echo "LISA engine: $(pip freeze | grep -i mslisa || echo mslisa)"
echo "Activate with: source $LISA_VENV/bin/activate"
echo "Set the workflow repo variable LISA_VENV=$LISA_VENV"
