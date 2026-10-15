#!/bin/sh
# A pg_dump at start and then every 24 h, kept KEEP_DAYS days. `backup.sh once`
# takes one dump and exits. Dumps hold Contract data (Reports, raw tool results),
# so they are owner-only. A dump on this VM is lost with the VM: copying
# /backups somewhere else is the Operator's job.
set -eu
umask 077
dump() {
  f="/backups/aiops-$(date -u +%Y%m%dT%H%M%SZ).dump"
  pg_dump --format=custom --file="$f.part" && mv "$f.part" "$f" && echo "backup: $f"
  find /backups -name 'aiops-*.dump' -mtime +"${KEEP_DAYS:-14}" -delete
}
if [ "${1:-}" = once ]; then
  dump
  exit
fi
while true; do
  dump || echo "backup failed" >&2
  sleep 86400
done
