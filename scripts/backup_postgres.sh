#!/usr/bin/env bash`nset -euo pipefail`n: "${DATABASE_URL:?set DATABASE_URL}"`npg_dump --format=custom --file="${1:-backup.dump}" "$DATABASE_URL"
