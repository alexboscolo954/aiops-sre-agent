#!/usr/bin/env bash
# Pull the contracts repo and restart the Hub, only if every Contract still
# validates. The Hub refuses to start on any bad Contract, so restarting on one
# would stop alert intake for all of them. On failure the clone goes back to the
# commit that was running, and the Hub keeps running untouched.
set -euo pipefail
cd "$(dirname "$0")"
contracts=${AIOPS_CONTRACTS:-./contracts}
before=$(git -C "$contracts" rev-parse HEAD)
git -C "$contracts" pull --ff-only --quiet
if ! docker compose run --rm --no-deps -T hub contracts validate /contracts; then
  git -C "$contracts" reset --hard --quiet "$before"
  echo "contracts invalid: back to $before, Hub not restarted" >&2
  exit 1
fi
docker compose restart hub
