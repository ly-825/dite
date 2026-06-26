#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/diet-delushan}"
UPLOAD_ROOT="${UPLOAD_ROOT:-/var/lib/diet-delushan/uploads}"
MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-diet_app}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
MYSQL_DB="${MYSQL_DB:-diet_delushan}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

timestamp="$(date +%Y%m%d_%H%M%S)"
mysql_dir="${BACKUP_ROOT}/mysql"
uploads_dir="${BACKUP_ROOT}/uploads"

mkdir -p "${mysql_dir}" "${uploads_dir}"

export MYSQL_PWD="${MYSQL_PASSWORD}"
mysqldump \
    --single-transaction \
    --routines \
    --triggers \
    --host="${MYSQL_HOST}" \
    --port="${MYSQL_PORT}" \
    --user="${MYSQL_USER}" \
    "${MYSQL_DB}" \
    | gzip > "${mysql_dir}/${MYSQL_DB}_${timestamp}.sql.gz"
unset MYSQL_PWD

if [ -d "${UPLOAD_ROOT}" ]; then
    tar -czf "${uploads_dir}/uploads_${timestamp}.tar.gz" \
        -C "$(dirname "${UPLOAD_ROOT}")" \
        "$(basename "${UPLOAD_ROOT}")"
fi

find "${mysql_dir}" -type f -name "*.sql.gz" -mtime +"${RETENTION_DAYS}" -delete
find "${uploads_dir}" -type f -name "*.tar.gz" -mtime +"${RETENTION_DAYS}" -delete

echo "backup finished: ${timestamp}"
