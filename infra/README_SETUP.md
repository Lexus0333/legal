# Установка n8n на VPS (Ubuntu 24.04) - пошагово

Что получится: n8n работает на вашем поддомене по HTTPS, сам перезапускается, внутри есть ffmpeg, каждую ночь делается бэкап.

Слова, которые встретятся:
- **VPS** - арендованный компьютер в интернете, который работает 24/7.
- **SSH** - способ управлять им из командной строки.
- **Docker** - программа, запускающая приложения в изолированных "коробках" (контейнерах).

---

## Шаг 1. Арендуйте VPS
- Ubuntu 24.04, минимум **2 vCPU и 4 GB RAM**, диск от 40 GB (ffmpeg на 1 GB RAM будет падать).
- Ориентир цены: $5-8 в месяц (Hetzner, Contabo, DigitalOcean и т.п.).
- При создании добавьте свой SSH-ключ, если провайдер предлагает. Если нет - получите пароль root на почту.
- Запишите **IP-адрес** сервера.

## Шаг 2. Направьте поддомен на сервер
В панели, где управляется ваш домен, создайте запись:
- Тип **A**, имя `n8n` (получится `n8n.вашдомен.com`), значение - IP сервера.

Подождите 5-30 минут. Проверка с вашего ПК (PowerShell): `nslookup n8n.вашдомен.com` - должен показать IP сервера.

## Шаг 3. Зайдите на сервер
В PowerShell на вашем ПК:
```
ssh root@ВАШ_IP
```
На вопрос про fingerprint ответьте `yes`.

## Шаг 4. Базовая безопасность
Создаём обычного пользователя, чтобы не работать под root:
```
adduser deploy
usermod -aG sudo deploy
```
(придумайте пароль, остальные вопросы можно пропустить Enter). Если заходили по ключу, скопируйте его:
```
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```
Файрвол: открываем только SSH, HTTP и HTTPS.
```
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```
Автоустановка обновлений безопасности:
```
apt update && apt install -y unattended-upgrades
```
Теперь выйдите (`exit`) и зайдите как `ssh deploy@ВАШ_IP`. Дальше все команды выполняем под `deploy`.

> Совет: когда убедитесь, что вход по ключу работает, отключите вход по паролю (`PasswordAuthentication no` в `/etc/ssh/sshd_config`, затем `sudo systemctl restart ssh`). Не делайте этого, пока не проверили вход по ключу - иначе потеряете доступ.

## Шаг 5. Установите Docker
```
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
```
Выйдите и зайдите по SSH снова. Проверка: `docker --version` и `docker compose version`.

## Шаг 6. Загрузите файлы
Создайте папку на сервере: `mkdir -p ~/n8n && cd ~/n8n`.
С вашего ПК (PowerShell, из папки `infra`) отправьте файлы:
```
scp docker-compose.yml Dockerfile Caddyfile .env.example backup.sh deploy@ВАШ_IP:~/n8n/
```

## Шаг 7. Заполните .env
На сервере:
```
cd ~/n8n
cp .env.example .env
openssl rand -hex 24   # это POSTGRES_PASSWORD
openssl rand -hex 32   # это N8N_ENCRYPTION_KEY
nano .env
```
Вставьте значения, укажите `N8N_HOST` (ваш поддомен) и `TZ`. Сохранить: Ctrl+O, Enter, выйти: Ctrl+X.

**Сохраните N8N_ENCRYPTION_KEY в менеджере паролей.** Без него бэкап не восстановить.

Проверьте версию n8n на https://hub.docker.com/r/n8nio/n8n/tags и при необходимости поправьте `N8N_VERSION`.

## Шаг 8. Запуск
```
docker compose up -d --build
docker compose ps
```
Все три сервиса должны быть `running`. Первая сборка занимает пару минут. Откройте `https://n8n.вашдомен.com` - создайте владельца (email и пароль). Сертификат появится сам за ~минуту; если нет - смотрите `docker compose logs caddy`.

## Шаг 9. Проверка ffmpeg
```
docker compose exec n8n ffmpeg -version
```
Должна вывестись версия.

## Шаг 10. Проверка автоперезапуска
```
sudo reboot
```
Через минуту зайдите снова и выполните `cd ~/n8n && docker compose ps` - всё должно подняться само (`restart: unless-stopped`, Docker стартует вместе с сервером).

## Шаг 11. Бэкапы
Проверка вручную:
```
cd ~/n8n && chmod +x backup.sh && ./backup.sh && ls backups
```
Автоматически каждую ночь в 03:00: `crontab -e`, добавьте строку (путь поправьте, если другой):
```
0 3 * * * /home/deploy/n8n/backup.sh >> /home/deploy/n8n/backup.log 2>&1
```
Бэкапы лежат на том же сервере, поэтому раз в неделю скачивайте их на свой ПК:
```
scp deploy@ВАШ_IP:~/n8n/backups/* C:\Backups\n8n\
```
**Восстановление базы** (на чистом сервере после шагов 1-8):
```
gunzip -c backups/db-ДАТА.sql.gz | docker compose exec -T postgres psql -U n8n n8n
```
С тем же `N8N_ENCRYPTION_KEY` в `.env`.

## Обновление n8n
Прочитайте заметки к релизу, сделайте `./backup.sh`, поменяйте `N8N_VERSION` в `.env`, затем:
```
docker compose up -d --build
```

## Если не работает
| Симптом | Что проверить |
|---|---|
| Сайт не открывается | `nslookup` показывает IP сервера? Порты 80/443 открыты в `ufw` и у провайдера? |
| Ошибка сертификата | `docker compose logs caddy` - обычно DNS ещё не обновился, подождите |
| n8n не стартует | `docker compose logs n8n` и `docker compose logs postgres` |
| Нет места на диске | `df -h`, `docker system prune` (осторожно, удаляет неиспользуемые образы) |
| Сервер зависает при обработке видео | Мало RAM, возьмите 4 GB+ |

## Что в файлах
- `docker-compose.yml` - n8n, база Postgres и Caddy (HTTPS). Порт n8n наружу закрыт.
- `Dockerfile` - добавляет ffmpeg в n8n. Для работы с видео в n8n включён узел Execute Command, а доступ к файлам ограничен папкой `~/n8n/files`.
- `.env` - секреты, лежит только на сервере. В файлах проекта только `.env.example` с заглушками.
