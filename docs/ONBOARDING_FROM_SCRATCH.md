# Запуск системы с нуля (для нового владельца)

В репозитории нет ключей, данных, базы, видео и учётных записей прежнего владельца. Всё ниже нужно создать самому. Порядок важен.

## 1. Аккаунты и доступы, которые нужно завести самому
| Что | Зачем | Где взять |
|---|---|---|
| Компьютер с Windows 10/11 (или Linux/Mac), работающий 24/7, 16+ ГБ диска под видео | Система работает локально, спящий режим отключить | свой ПК или мини-ПК |
| Docker Desktop | запускает n8n, шлюз и ngrok | docker.com |
| Аккаунт **ngrok** (бесплатный) + **статический домен** `xxx.ngrok-free.dev` + authtoken | публичный HTTPS-адрес для вебхуков (OAuth TikTok требует HTTPS) | dashboard.ngrok.com → Domains, Your Authtoken |
| Аккаунт **GitHub** + репозиторий с GitHub Pages | хостинг панели и страниц Privacy/Terms (их требует TikTok) | github.com |
| Аккаунт **TikTok Developer** + приложение с продуктами **Login Kit** и **Content Posting API (Direct Post)** | OAuth и публикация | developers.tiktok.com |
| TikTok-аккаунты, на которые публикуем (закрытые до аудита) | цели публикации; регистрируются вручную, владельцами | tiktok.com |
| (необязательно) ключ OpenAI-совместимого ИИ | ИИ пишет хук и подпись по кадрам; без него берутся пулы текстов | OpenRouter, OpenAI и др., сервис должен быть доступен из вашего региона |
| (необязательно) Telegram-бот и свой chat id | уведомления об ошибках публикации | @BotFather |
| (необязательно) healthchecks.io | пульс: оповещение, если ПК/Docker остановились | `HEARTBEAT_URL` |

Работа с TikTok-аккаунтами: только владелец подключает аккаунт сам (вход TikTok). Автоматическую массовую регистрацию аккаунтов не делать: нарушает правила TikTok.

## 2. Порядок установки
1. Склонировать репозиторий (ветка `project` или `main`, где лежит проект).
2. `infra/.env`: скопировать `infra/.env.example` и заполнить. Сгенерировать **свои** секреты: `N8N_ENCRYPTION_KEY` (`openssl rand -hex 32`, сохранить в менеджере паролей, потеря = потеря токенов аккаунтов), `CONNECT_SECRET` (`openssl rand -hex 16`, это ключ входа в панель), `N8N_HOST` = ваш ngrok-домен без https://, `NGROK_AUTHTOKEN`, `TZ`, `N8N_VERSION` (в проекте 2.31.6). TikTok-ключи появятся на шаге 3.
3. Приложение TikTok (подробнее в `docs/SETUP_WORKFLOWS.md`): Redirect URI `https://<N8N_HOST>/webhook/tiktok-callback`, scopes `user.info.basic` и `video.publish`, Terms/Privacy URL со своей Pages-страницы (папка `site/`: заменить контакт-email `gu1gu2gu4@gmail.com`, название «EXE Agency», домен и ссылки `lexus0333.github.io/legal` на свои во всех файлах `site/*.html` и в `SITE_URL`). До аудита аккаунты добавить как Target users (sandbox). Client key/secret в `.env`.
4. Запуск: `cd infra`, затем `docker compose -f docker-compose.local.yml --env-file .env --profile tunnel up -d --build n8n gate ngrok`. Редактор: `http://localhost:5678` (создать владельца n8n, включить 2FA).
5. **Таблица:** в n8n Data tables создать таблицу `tiktok_accounts` (колонки в `docs/DATA_MODEL.md`).
6. Импорт воркфлоу из **`workflows/`** (не из `infra/files/workflows/`: там привязка к таблице прежнего владельца): `docker exec infra-n8n-1 n8n import:workflow --input=/files/workflows/<файл>.json` для 01, 03, 04, 05, 06, 07, 08 (путь `/files/` соответствует папке `infra/files/`, поэтому сначала скопировать файлы из `workflows/` в `infra/files/workflows/` или смонтировать). Затем `n8n publish:workflow --id=<id>` для каждого и `docker restart infra-n8n-1`. Если в воркфлоу узлы Data table не нашли таблицу, выбрать её вручную в узлах типа Data table: 01 «Save account (upsert)»; 03 «Accounts», «Get account», «Delete account»; 04 и 08 «Get tokens», «Save tokens»; 05 и 06 «Accounts».
7. Папки: `infra/files/{inbox,done,failed,work,prepared,out,music,fonts,pools,scripts}` создаются сами/из репозитория; положить шрифт `infra/files/fonts/font.ttf` (в репозитории есть) и скрипты из `scripts/` в `infra/files/scripts/`. Тексты по умолчанию: `infra/files/pools/en/{hooks,captions,hashtags}.txt` (по одной строке на вариант).
8. Панель: опубликовать `site/` на GitHub Pages; в `site/console.html` в защите/политике (CSP) разрешены любые https-адреса, поэтому правки адреса не нужны; в `allowedOrigins` вебхуков воркфлоу 03 и 05 стоит `https://lexus0333.github.io`: заменить в `tools/gen03.py` и `tools/gen05.py` (константа `ORIGIN`) на свой домен Pages, пересобрать и импортировать заново.
9. Вход в панель: адрес сервера `https://<N8N_HOST>`, ключ = `CONNECT_SECRET`.
10. Подключить первый аккаунт (вкладка Accounts → Connect TikTok account), положить видео в `infra/files/inbox/<аккаунт>/`, `DRY_RUN=1` для пробы, затем `DRY_RUN=0` и настоящая приватная публикация.
11. Бэкап: `scripts/backup_local.ps1` и задача в Планировщике Windows (как это делалось: ежедневно 03:30), см. `docs/BACKUP_RESTORE.md`.
12. Аудит приложения TikTok: записать демо (панель, подключение аккаунта с экраном разрешений, видео в inbox, публикация, результат в профиле), отправить заявку, после отправки сменить `CONNECT_SECRET`. После одобрения `TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE`.

## 3. Что проверить после установки
- Из интернета открывается только `/webhook/*` (корень и `/signin` отдают 404).
- Запрос панели без ключа даёт 403, с неверным 10 раз подряд даёт 429.
- В `DRY_RUN=1` кнопка Publish проходит весь путь, видео остаётся в `inbox`, в `posts.jsonl` запись `DryRun`.
- Планировщик по умолчанию на паузе (`schedule.json` → `global.paused`); включать после проверки ручной публикации.
