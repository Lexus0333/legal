# Передача проекта: что это и как устроено

Автопубликация видео в TikTok через n8n. Работает локально на ПК (Docker Desktop + ngrok), панель управления на GitHub Pages. Рассчитано на 50–1000 аккаунтов.

## Карта проекта
| Путь | Что там |
|---|---|
| `site/` | Панель и страницы политики (отдельный репозиторий `Lexus0333/legal`, GitHub Pages: `/legal/console.html`) |
| `infra/` | Docker: `docker-compose.local.yml`, шлюз `Caddyfile.gate`, `.env.example`, Dockerfile (n8n + ffmpeg) |
| `infra/files/workflows/`, `workflows/` | Готовые воркфлоу n8n (01, 03–08). Не править руками |
| `tools/` | Генераторы воркфлоу (`genNN.py`), общие блоки (`blocks.py`, `snippets.py`), шаблоны |
| `scripts/` | Скрипты видео: `make_variants.sh` (хук на видео), `add_music.sh`, `analyze_mood.sh`, `extract_frames.sh`, бэкап `backup_local.ps1` |
| `docs/` | `SETUP_WORKFLOWS.md` (запуск), `DAILY_USE.md` (ежедневная работа), `SCHEDULER_DESIGN.md`, `BACKUP_RESTORE.md` |
| `legacy/` | Устаревшая версия через Google Sheets, не используется |

## Воркфлоу
01 подключение аккаунта (OAuth TikTok, приглашения), 03 API кнопки «Publish», 04 ручная публикация из папки, 05 API панели, 06 планировщик (раз в минуту), 07 подготовка слота, 08 публикация слота.
Изменение логики: правка в `tools/genNN.py` или `blocks.py` → `python tools/genNN.py` → `node --check` кода узлов → импорт (`n8n import:workflow`, `publish:workflow`, перезапуск). Подробности в `docs/SETUP_WORKFLOWS.md`.

## Данные (в репозиторий не входят)
Папка `infra/files/` на ПК: `accounts.json`, `schedule.json`, `posts.jsonl` (журнал), `plan/` (слоты), `pools/` (хуки, подписи, хэштеги), `inbox/<аккаунт>/` (видео), `invites/`, `identity/`, `state/`. Токены аккаунтов лежат в таблице n8n `tiktok_accounts`, зашифрованные (AES-256-GCM, ключ от `N8N_ENCRYPTION_KEY`).

## Секреты (в репозиторий не входят, передавать отдельно и безопасно)
`infra/.env`: `TIKTOK_CLIENT_KEY/SECRET`, `CONNECT_SECRET` (ключ панели), `N8N_ENCRYPTION_KEY`, `NGROK_AUTHTOKEN`, ключ ИИ. Шаблон: `infra/.env.example`. Потеря `N8N_ENCRYPTION_KEY` = токены аккаунтов не прочитать, аккаунты придётся подключать заново.

## Безопасность
Наружу через ngrok и шлюз Caddy видны только `/webhook/*`. Ключ панели только в заголовке `Authorization: Bearer`, блокировка по IP после 10 ошибок. Подключение аккаунта из панели через одноразовый билет. Редактор n8n только на `http://localhost:5678`.

## Состояние на 2026-10-20 и решения
- Приложение TikTok пока в песочнице: посты приватные (`TIKTOK_PRIVACY=SELF_ONLY`). Заявка на аудит НЕ отправлена: нужно демо-видео (подключение, публикация), после отправки сменить `CONNECT_SECRET`. В `.env` `MAX_POSTS_PER_RUN=1` под демо.
- Scopes: только `user.info.basic`, `video.publish`. Статистика (`video.list`) выключена флагом `STATS_ENABLED=0`, в заявку не добавлять.
- Остаёмся локально: арендованный ранее VPS слишком слабый. Не переносить туда.
- ИИ (Gemini) из региона не работает (HTTP 400), хуки и подписи берутся из пулов `pools/`.
- Массовую авторегистрацию аккаунтов TikTok не делаем (нарушает правила TikTok): аккаунты добавляются вручную или через ссылки-приглашения владельцам.
- Не проверено: реальное подключение аккаунта по приглашению (нужен клик в TikTok), настоящая публикация через планировщик (проверено только в `DRY_RUN`). Планировщик по умолчанию на паузе.
- Ловушки: `saveDataSuccessExecution: none` в воркфлоу зависает; Execute Workflow вызывает только активные воркфлоу; в Git Bash для `docker exec` нужен `MSYS_NO_PATHCONV=1`; имена аккаунтов хранятся в нижнем регистре; после тестов вернуть `DRY_RUN=0` и удалить тестовые аккаунты.
- Открытые доработки: подтверждение при несохранённых правках в панели, отдельный статус `Check` в журнале, пересоздание будущих слотов при смене профиля, показ `ai_error` на вкладке Videos.
