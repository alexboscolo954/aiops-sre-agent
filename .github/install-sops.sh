#!/usr/bin/env bash
# Pinned sops for CI, verified by checksum. Decrypts the demo Contracts' test secrets.
set -euo pipefail
v=3.13.3
sha=e5bec3346a873ae91d871550f3e698c1aad962aff462a080e40f25fde17fef6b
curl -fsSLO "https://github.com/getsops/sops/releases/download/v$v/sops-v$v.linux.amd64"
echo "$sha  sops-v$v.linux.amd64" | sha256sum -c -
sudo install -m 755 "sops-v$v.linux.amd64" /usr/local/bin/sops
rm "sops-v$v.linux.amd64"
