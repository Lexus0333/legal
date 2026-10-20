# Запуск: приложение TikTok, n8n на своём ПК, подключение аккаунтов

Система работает локально: Docker Desktop (n8n) + ngrok (публичный HTTPS-адрес только для вебхуков) + панель на GitHub Pages. Google Sheets не используется.

## 1. Приложение TikTok (developers.tiktok.com)
1. Страницы Terms и Privacy лежат в `site/` и опубликованы на GitHub Pages.
2. Manage apps → Connect an app. Продукты: **Login Kit** и **Content Posting API** (включить Direct Post).
3. Redirect URI: `https://<N8N_HOST>/webhook/tiktok-callback`. Scopes: `user.info.basic`, `video.publish`.
4. До аудита все посты приватные (`TIKTOK_PRIVACY=SELF_ONLY`). После одобрения: `PUBLIC_TO_EVERYONE`.
5. Client key и secret в `infra/.env` (`TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`). Никому не показывать.

## 2. Запуск
```
cd infra
docker compose -f docker-compose.local.yml --env-file .env --profile tunnel up -d n8n gate ngrok
```
Редактор n8n: http://localhost:5678 (из интернета недоступен, наружу отдаются только `/webhook/*`).

## 3. Воркфлоу
Готовые файлы: `infra/files/workflows/` (01, 03–08). Они собираются генераторами из `tools/` (см. `tools/README.md`). Импорт и публикация:
```
docker exec infra-n8n-1 n8n import:workflow --input=/files/workflows/<файл>.json
docker exec infra-n8n-1 n8n publish:workflow --id=<id воркфлоу>
docker restart infra-n8n-1
```
Таблица `tiktok_accounts` (Data table в n8n): account, access_token, refresh_token, access_expires_at, refresh_expires_at, open_id и др. Токены хранятся зашифрованными (`enc:`).

## 4. Панель
`https://lexus0333.github.io/legal/console.html`: адрес сервера = `https://<N8N_HOST>`, ключ = `CONNECT_SECRET` из `.env`. Ключ передаётся только в заголовке запроса.

## 5. Подключение аккаунтов
- Свои аккаунты: в панели «Connect TikTok account» (создаётся одноразовый билет на 2 минуты).
- Аккаунты других людей: вкладка Invitations, ссылка-приглашение отправляется владельцу.

## 6. Ежедневное и аварийное
См. `docs/DAILY_USE.md` и `docs/BACKUP_RESTORE.md`.
