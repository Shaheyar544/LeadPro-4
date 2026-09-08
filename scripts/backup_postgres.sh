#!/usr/bin/env bash
set -euo pipefail
# PostgreSQL's native PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSFILE environment.
# Do not put passwords in a command-line URL.
: "${PGDATABASE:?set PGDATABASE}"
: "${PGUSER:?set PGUSER}"
destination="${1:?supply a backup path outside Git}"
if [[ -e "$destination" ]]; then
  echo 'Refusing to overwrite an existing backup' >&2
  exit 1
fi
umask 077
pg_dump --format=custom --file="$destination"
