# Модель данных: таблица, папки, форматы файлов

Всё состояние лежит в двух местах: таблица n8n `tiktok_accounts` (токены) и папка `infra/files/` (в контейнере `/files`). Базы данных кроме встроенной SQLite n8n нет. Данные в репозиторий не входят (`.gitignore`).

## 1. Таблица n8n `tiktok_accounts` (Data table)
| Колонка | Тип | Содержимое |
|---|---|---|
| `account` | string | имя аккаунта в системе (нижний регистр, `[a-z0-9_-]{1,40}`), уникальный ключ (upsert по нему) |
| `open_id` | string | идентификатор пользователя TikTok; по нему отсекается подключение одного TikTok-аккаунта под двумя именами |
| `access_token` | string | токен доступа, **зашифрован** (`enc:<iv>:<tag>:<data>`, AES-256-GCM, ключ scrypt от `N8N_ENCRYPTION_KEY`) |
| `refresh_token` | string | токен обновления, зашифрован так же |
| `access_expires_at` | number | миллисекунды Unix, обычно живёт около суток |
| `refresh_expires_at` | number | миллисекунды Unix, обычно около года; когда истечёт, нужно переподключить аккаунт |
Строка без `refresh_token` = аккаунт не подключён. Отключение удаляет строку и отзывает токен в TikTok.

## 2. Структура папки `infra/files/`
```
accounts.json            настройки аккаунтов (см. ниже)           [+ .bak]
schedule.json            расписание: профили, группы, паузы         [+ .bak]
posts.jsonl              журнал публикаций, одна JSON-строка на событие
panel_cache.json         кэш панели (статистика по журналу), можно удалять
plan_summary.json        сводка планировщика для панели
errors.log               журнал внутренних ошибок
inbox/<аккаунт>/<папка ролика>/<видео>.mp4|mov|m4v [+ <видео>.txt]   очередь видео
done/<аккаунт>/<папка ролика>/   опубликованные: исходные файлы + <имя>_published.mp4 + <имя>_post.json
failed/<аккаунт>/                с ошибкой: + <имя>_error.txt
removed/                         папки удалённых из панели аккаунтов
work/ prepared/ out/             временные файлы подготовки и готовые к публикации ролики
plan/<слот>.json                 слоты планировщика (по файлу на слот)
pools/<язык|аккаунт>/{hooks,captions,hashtags}.txt   тексты по умолчанию (en, ru) и свои у аккаунта
music/<calm|energetic|mysterious>/   треки; файлы прямо в music/ годятся для любого видео
fonts/font.ttf           шрифт для текста на видео
scripts/                 shell-скрипты обработки видео (копия папки scripts/)
workflows/               файлы воркфлоу для импорта
invites/<токен>.json     приглашения владельцам
identity/<аккаунт>.json  кто подключён: open_id, display_name, avatar_url, connected_at, via
tickets/<id>.json        одноразовые билеты на подключение из панели (живут 2 минуты)
state/                   служебные маркеры (см. ниже)
```
Папка ролика в `inbox` может содержать несколько видео и картинки; публикуется видео, остальное едет вместе в `done`. Файл `<видео>.txt`: первая строка = хук (текст на видео в первые секунды), остальное = подпись.

## 3. Форматы файлов
**`accounts.json`**: `{ "<аккаунт>": { "created_at": ISO, "group": "batch-1", "bio_link": "https://…", "bio_link_set": false, "aigc": true } }`. `aigc: false` отключает AI-метку у аккаунта (по умолчанию метка ставится, `AIGC_LABEL=0` отключает для всех).

**`schedule.json`**:
```
{ "global": { "paused": true, "catchup_hours": 6, "max_parallel": 2, "max_prepare": 2,
              "prepare_ahead_hours": 12, "pause_after_errors": 3, "min_free_gb": 5, "max_prepared": 400 },
  "default_profile": "default",
  "profiles": { "default": { "posts_per_day": 2, "windows": [["10:00","22:00"]], "min_gap_min": 120,
                "days": [1,2,3,4,5,6,7], "tz": "Europe/Warsaw", "ramp": null, "enabled": true } },
  "group_profile": { "<группа>": "<профиль>" },
  "overrides": { "<аккаунт>": { "profile": "<профиль>", "posts_per_day": 3 } } }
```
Окно, у которого конец раньше начала, переходит через полночь (`22:00-02:00`); `24:00` допустимо как конец.

**Слот `plan/<ГГГГММДДЧЧММ>_<аккаунт>_<4 символа>.json`**: `id, account, at (ISO), state, attempts, manual, created, updated, reason, video {orig, rel, file, hintOrig}, meta {hook, caption, hashtags[], music, ai_used, ai_error}`. Состояния: `planned → preparing → prepared → publishing → done`, а также `skipped`, `failed`.

**`posts.jsonl`**: `{ at, id, account, file, rel, status, hook, caption, publish_id, tiktok_status, privacy, ai_used, ai_error, music, error, kept, slot }`. Статусы: `Processing`, `Posted`, `Check` (TikTok не подтвердил, проверить вручную), `Error`, `DryRun`. Записи одного `id` обновляют друг друга (берётся последняя).

**`invites/<48 hex>.json`**: `{ token, account, note, created_at, expires_at, status (pending|revoked|used), opened_at, used_at }`. Ссылка: `https://<N8N_HOST>/webhook/tiktok-invite?t=<token>`.

**`state/`**: `paused/<аккаунт>.json` (`reason, until` пауза аккаунта), `errors/<аккаунт>.json` (счётчик ошибок подряд), `published/<хэш>.json` (метка «видео уже отправлено в TikTok», защита от дубля), `locks/` (блокировки аккаунтов и записи панели), `first_plan/` и `plan_dates.json` (учёт планирования), `auth_fail/` (счётчики неверных ключей по IP), `removed/`, `housekeeping.json`.

## 4. Вебхуки (все на `https://<N8N_HOST>/webhook/…`)
| Путь | Метод | Воркфлоу | Доступ |
|---|---|---|---|
| `tiktok-start?ticket=` | GET | 01 | одноразовый билет |
| `tiktok-callback` | GET | 01 | подписанный `state` (HMAC) от TikTok |
| `tiktok-invite?t=` | GET | 01 | токен приглашения |
| `console-api` (`action=run|disconnect`, без action: статус) | GET | 03 | `Authorization: Bearer <CONNECT_SECRET>` |
| `panel-api` (`action=overview|names|posts|pools|invites|schedule`) | GET | 05 | то же |
| `panel-save` (`action=saveAccount|addAccounts|savePools|saveSchedule|pauseAll|resumeAll|setOverride|pauseAccounts|skipSlot|publishNow|createInvites|revokeInvite|deleteAccount|connectTicket|…`) | POST | 05 | то же |
Воркфлоу 06 запускается по таймеру раз в минуту, 07 и 08 вызываются из 06 (Execute Workflow), 04 вызывается из 03.

## 5. Переменные окружения
Полный список с описаниями: `infra/.env.example`. Ключевые: `TIKTOK_CLIENT_KEY/SECRET`, `CONNECT_SECRET`, `N8N_ENCRYPTION_KEY`, `N8N_HOST`, `NGROK_AUTHTOKEN`, `TIKTOK_PRIVACY`, `DRY_RUN`, `MAX_POSTS_PER_RUN`, `POOL_LANG`, `MUSIC_MODE`, `AI_*`, `AIGC_LABEL`, `SITE_URL`, `HEARTBEAT_URL`, `TELEGRAM_CHAT_ID`.
