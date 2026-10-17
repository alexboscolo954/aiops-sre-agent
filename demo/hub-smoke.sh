#!/usr/bin/env bash
# The Hub's compose stack (deploy/hub) on this machine, with the demo Contracts:
# - comes up healthy, and both Contracts decrypt inside the image;
# - only the alert route is public: everything else through Caddy is a 404,
#   the console included, even with a forged Tailscale identity header;
# - the console renders on 127.0.0.1 for the Operator's identity plus the token cookie;
# - an alert is stored and fails as expected (no cluster, no model key in CI);
# - a backup restores, and a bad contracts update never restarts the Hub.
# Usage: demo/hub-smoke.sh [image]
set -euo pipefail
image=${1:-aiops-sre-agent:ci}
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
export COMPOSE_PROJECT_NAME=aiops-smoke
dc() { (cd "$work" && docker compose "$@"); }
trap 'dc down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
fail() { echo "FAIL: $*" >&2; dc logs hub --tail 50 >&2 || true; exit 1; }
git_() { git -c user.name=smoke -c user.email=smoke@localhost "$@"; }

cp "$root"/deploy/hub/{compose.yaml,Caddyfile,backup.sh,update-contracts.sh} "$work"/

# The contracts repo as the VM has it: a clone of a remote. demo-shop gets a
# webhook token the way an Operator adds one.
new=$(docker run --rm "$image" contracts new-token 2>/dev/null)
token=$(sed -n 1p <<<"$new" | awk '{print $NF}')
git_ init -q -b main "$work/seed"
cp -R "$root"/demo/contracts/. "$work/seed/"
rm -rf "$work/seed/test-keys"   # keys never live in the contracts repo
sed -n 2p <<<"$new" | sed 's/^contract.yaml: *//' >>"$work/seed/demo-shop/contract.yaml"
git_ -C "$work/seed" add -A && git_ -C "$work/seed" commit -qm seed
git clone -q --bare "$work/seed" "$work/origin.git"
git clone -q "$work/origin.git" "$work/contracts"

# The age keys file exactly as documented: owned by the image's uid 10001, 0400.
cat "$root"/demo/contracts/test-keys/*.agekey >"$work/age-keys.txt"
chmod 0400 "$work/age-keys.txt"
if [[ $(uname) == Linux ]]; then sudo chown 10001 "$work/age-keys.txt"; fi
mkdir -m 0700 "$work/backups"
if [[ $(uname) == Linux ]]; then sudo chown 999 "$work/backups"; fi   # postgres image's uid

cat >"$work/.env" <<EOF
AIOPS_IMAGE=$image
POSTGRES_PASSWORD=smoke-$RANDOM$RANDOM
AIOPS_DOMAIN=localhost
AIOPS_LOCAL_PORT=18000
AIOPS_HTTP_PORT=18081
AIOPS_HTTPS_PORT=18443
EOF
printf 'AIOPS_APPROVER_TOKEN=smoke-approver\nAIOPS_MODEL_API_KEY=not-a-real-key\n' >"$work/hub.env"
echo 'AIOPS_CONSOLE_OPERATORS=["smoke@example.com"]' >>"$work/hub.env"

dc up -d --wait --quiet-pull || fail "stack did not come up healthy"
[[ $(dc port hub 8080) == 127.0.0.1:18000 ]] || fail "hub published on $(dc port hub 8080)"
echo "ok   stack healthy; hub only on 127.0.0.1"

public=https://localhost:18443
code() { curl -sk -o /dev/null -w '%{http_code}' "$@"; }
alert="$public/contracts/demo-shop/alertmanager"
json=(-H 'Content-Type: application/json' --data-binary @"$root/examples/alert-crashloop.json")

[[ $(code -X POST "$alert" -H 'Authorization: Bearer wrong' "${json[@]}") == 401 ]] || fail "wrong token"
id=$(curl -sfk -X POST "$alert" -H "Authorization: Bearer $token" "${json[@]}" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["investigation"])') || fail "alert refused"
echo "ok   alert accepted through Caddy: $id"

for path in /investigations "/investigations/$id" /metrics /healthz /docs /openapi.json \
  /contracts/demo-shop/alertmanager/x; do
  [[ $(code -H 'Authorization: Bearer smoke-approver' "$public$path") == 404 ]] || fail "GET $path is public"
done
[[ $(code -X POST "$public/investigations/$id/decision" -H 'Authorization: Bearer smoke-approver' \
  -H 'Content-Type: application/json' -d '{"approve": true}') == 404 ]] || fail "decisions are public"
[[ $(code -X GET "$alert" -H "Authorization: Bearer $token") == 404 ]] || fail "GET on the alert route"
for path in /contracts/demo-shop/alertmanager/../../investigations \
  /contracts/demo-shop%2F..%2F..%2Finvestigations/alertmanager \
  /contracts/demo-shop/alertmanager%2F..%2F..%2Finvestigations; do
  got=$(code --path-as-is -X POST "$public$path" -H "Authorization: Bearer $token" "${json[@]}")
  [[ $got == 404 ]] || fail "POST $path reached the Hub ($got)"
done
big=$(code -X POST "$alert" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data-binary @<(head -c 2000000 /dev/zero | tr '\0' 'a'))
[[ $big == 413 ]] || fail "a 2 MB body got $big, want 413"
as_operator=(-H 'Tailscale-User-Login: smoke@example.com')
[[ $(code "${as_operator[@]}" "$public/console") == 404 ]] || fail "the console is public"
echo "ok   only the alert route is public; bodies over 1 MB refused"

local_api=http://127.0.0.1:18000
for _ in $(seq 60); do
  inv=$(curl -sf "$local_api/investigations/$id" -H 'Authorization: Bearer smoke-approver')
  status=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["status"])' "$inv")
  [[ $status == failed ]] && break
  sleep 1
done
# No cluster in the container: the Run fails connecting to demo-shop's kind context.
python3 - "$inv" <<'EOF' || fail "unexpected investigation: $inv"
import json, sys
t = json.loads(sys.argv[1])
assert t["status"] == "failed" and t["contract_id"] == "demo-shop", t
assert t["error"].startswith("ConfigException"), t["error"]
EOF
echo "ok   investigation stored, failed as expected without a cluster"

# The console, as `tailscale serve` reaches it: the image has its templates, and
# only the Operator's identity header gets in.
# The cookie the token page sets: an HMAC of the approver token (console.py).
key=$(python3 -c 'import hashlib,hmac; print(hmac.new(b"smoke-approver", b"aiops-console", hashlib.sha256).hexdigest())')
with_token=("${as_operator[@]}" -H "Cookie: aiops_actions=$key")
curl -sf "${with_token[@]}" "$local_api/console" | grep -q 'demo-shop' || fail "console"
curl -sf "${with_token[@]}" "$local_api/console/investigations/$id" | grep -q 'ConfigException' ||
  fail "console investigation page"
curl -sf --max-time 60 "${with_token[@]}" "$local_api/console/health" | grep -q 'FAILING' ||
  fail "console health"   # no cluster in the container: the kubernetes checks fail, and say so
[[ $(code "$local_api/console") == 403 ]] || fail "console without an identity"
[[ $(code "${as_operator[@]}" "$local_api/console") == 303 ]] || fail "console without the token"
echo "ok   console renders on 127.0.0.1 for the Operator with the token only, and is 404 through Caddy"

dc exec -T backup /backup.sh once >/dev/null || fail "backup"
dc exec -T backup sh -c '
  f=$(ls -t /backups/aiops-*.dump | head -1)
  [ "$(stat -c %a "$f")" = 600 ] || { echo "dump mode $(stat -c %a "$f")"; exit 1; }
  createdb restored && pg_restore --no-owner -d restored "$f"
  psql -d restored -tAc "select count(*) from investigations where id = '"'$id'"'"' |
  grep -qx 1 || fail "backup did not restore"
echo "ok   backup is owner-only and restores"

started=$(docker inspect -f '{{.State.StartedAt}}' "$(dc ps -q hub)")
printf 'id: demo-shop\nnaem: typo\n' >"$work/seed/demo-shop/contract.yaml"
git_ -C "$work/seed" commit -qam "bad contract" && git -C "$work/seed" push -q "$work/origin.git" main
good=$(git -C "$work/contracts" rev-parse HEAD)
if (cd "$work" && AIOPS_CONTRACTS=./contracts ./update-contracts.sh) >/dev/null 2>&1; then
  fail "a bad contracts update was applied"
fi
[[ $(git -C "$work/contracts" rev-parse HEAD) == "$good" ]] || fail "clone not rolled back"
[[ $(docker inspect -f '{{.State.StartedAt}}' "$(dc ps -q hub)") == "$started" ]] || fail "hub restarted"
echo "ok   a bad contracts update is refused and rolled back; hub untouched"

echo "hub smoke ok"
