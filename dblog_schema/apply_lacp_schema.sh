#!/usr/bin/env bash
set -euo pipefail

DB_USER="${1:-morophi}"
SCHEMA_FILE="${2:-/home/morophi/lacp_db_schema.sql}"

if [[ -z "${MYSQL_PWD:-}" ]]; then
  echo "MYSQL_PWD must be set for DB_USER=${DB_USER}" >&2
  exit 2
fi

/usr/bin/mariadb -u "${DB_USER}" -e "SHOW DATABASES"
/usr/bin/mariadb -u "${DB_USER}" < "${SCHEMA_FILE}"
/usr/bin/mariadb -u "${DB_USER}" -e "USE lacp_db; SHOW TABLES"
