#!/usr/bin/env bash
# Ночной бэкап: база n8n + папка n8n (там ключи и настройки). Хранит 7 последних копий.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)

docker compose exec -T postgres pg_dump -U n8n n8n | gzip > "backups/db-$STAMP.sql.gz"
docker run --rm -v "$(basename "$PWD")_n8n_data:/data:ro" -v "$PWD/backups:/out" alpine \
  tar czf "/out/n8n-data-$STAMP.tar.gz" -C /data .

# удаляем всё старше 7 дней
find backups -type f -mtime +7 -delete
echo "Бэкап готов: backups/*-$STAMP.*"
