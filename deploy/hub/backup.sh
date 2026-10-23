#!/bin/sh
# A pg_dump whenever the newest one is a day old, checked every 5 minutes, kept
# KEEP_DAYS days. Judged by the dumps' file times, never by a 24-hour sleep: a
# sleeping laptop stops the container's clock, and a dump that fails (Postgres still
# starting after a restart) is tried again 5 minutes later, not a day later.
# `backup.sh once` takes one dump and exits. Dumps hold Contract data (Reports, raw
# tool results), so they are owner-only. A dump on this host is lost with it:
# copying /backups somewhere else is the Operator's job.
set -eu
umask 077
dump() {
  f="/backups/aiops-$(date -u +%Y%m%dT%H%M%SZ).dump"
  if ! pg_dump --format=custom --file="$f.part"; then
    rm -f "$f.part"
    return 1
  fi
  mv "$f.part" "$f" && echo "backup: $f"
  find /backups -name 'aiops-*.dump' -mtime +"${KEEP_DAYS:-14}" -delete
}
if [ "${1:-}" = once ]; then
  dump
  exit
fi
find /backups -name 'aiops-*.dump.part' -delete  # left by a dump that was killed
while true; do
  if [ -z "$(find /backups -name 'aiops-*.dump' -mmin -1440)" ]; then
    dump || echo "backup failed; trying again in 5 minutes" >&2
  fi
  sleep 300
done
