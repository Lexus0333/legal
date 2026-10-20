# Резервные копии

Скрипт `scripts/backup_local.ps1` каждый день в 03:30 (задача Планировщика Windows «TT backup», если ПК выключен — при следующем включении) создаёт архив `infra/backups/tt-backup-<дата>.zip`:
- `database.sqlite`: база n8n с токенами аккаунтов (копия через VACUUM INTO, n8n может работать);
- `files/`: настройки аккаунтов, расписание, журнал публикаций, приглашения, тексты, воркфлоу (без папок с видео);
- `.env`: все секретные ключи.

Хранится 14 последних копий. **Архив содержит секреты: не отправляйте его никому, периодически копируйте на внешний диск или в надёжное облако.** Видео в архив не входят.

Ручной запуск: `powershell -ExecutionPolicy Bypass -File scripts\backup_local.ps1 [-Dest D:\Backups]`.

## Восстановление
1. Остановить n8n: `docker compose -f docker-compose.local.yml --env-file .env stop n8n`.
2. Распаковать архив в отдельную папку.
3. `.env` вернуть в `infra/`. Содержимое `files/` скопировать в `infra/files/` поверх.
4. Базу вернуть в том n8n: `docker run --rm -v infra_n8n_data:/data -v "<папка с архивом>:/in" alpine cp /in/database.sqlite /data/database.sqlite`.
5. Запустить n8n. Ключ `N8N_ENCRYPTION_KEY` в `.env` должен быть тем же, иначе токены не прочитать.

Если повреждён только `accounts.json` или `schedule.json`, система сама восстановит их из `*.bak` (в панели появится уведомление).
