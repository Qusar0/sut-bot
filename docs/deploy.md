# Разворачивание на сервере

Нужно: VPS с Linux (Ubuntu 22.04/24.04), 1 vCPU, от 1 ГБ RAM, Docker; домен, указывающий на сервер (для вебхука,
подписки на календарь и Mini App — Telegram и Google требуют HTTPS). Конфигурация в `docker-compose.yml` рассчитана
на 1 ГБ RAM (лимиты памяти, экономные настройки Postgres/Redis). Образ собирается в CI и публикуется в GHCR — на
сервере он только подтягивается, а не билдится, поэтому 1 vCPU хватает.

## 1. Swap (обязательно для 1 ГБ RAM)

Без swap пики нагрузки упираются в память. Сначала проверьте, нет ли swap уже (`swapon --show` — многие
образы Ubuntu идут со `/swap.img`): если есть — этот шаг пропустите, второй файл только зря ест диск. Если нет:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl -w vm.swappiness=10 && echo 'vm.swappiness=10' >> /etc/sysctl.d/99-swap.conf
```

## 2. Сервер

Образ лежит в GitHub Container Registry. Если пакет приватный — сначала логин
(`docker login ghcr.io -u <user>` с токеном, имеющим `read:packages`); публичный пакет тянется без логина.

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/Qusar0/sut-bot.git /opt/sut-bot && cd /opt/sut-bot
cp .env.example .env   # заполнить, см. ниже
docker compose pull    # тянем готовый образ из GHCR
docker compose up -d
docker compose logs -f bot
```

## 3. `.env` на сервере

| Переменная | Значение |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `ENCRYPTION_KEY` | тот же ключ, что и раньше (не терять!) |
| `ADMIN_ID` | ваш Telegram ID — для /stats и алертов |
| `POSTGRES_PASSWORD` | длинный случайный пароль |
| `PUBLIC_URL` | `https://bot.example.ru` |
| `USE_WEBHOOK` | `true` |
| `WEBHOOK_SECRET` | длинная случайная строка |

`DATABASE_URL` и `REDIS_URL` docker-compose подставляет сам.

## 4. HTTPS (Caddy в Docker — сертификат получает сам)

Нужно для webhook, Mini App и подписки на календарь. Домен должен A-записью указывать на сервер; без своего
домена подойдёт `46.38.156.87.sslip.io` (sslip.io резолвит IP из имени, регистрация не нужна).

В `.env` добавить (к уже существующему `COMPOSE_FILE` допишите через `:` файл caddy):
```
COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml:docker-compose.caddy.yml
CADDY_DOMAIN=46.38.156.87.sslip.io
PUBLIC_URL=https://46.38.156.87.sslip.io
USE_WEBHOOK=true
```
Поднять и проверить:
```bash
cd /opt/sut-bot && docker compose up -d
curl -fsS https://$CADDY_DOMAIN/health   # -> ok (через минуту после выдачи сертификата)
```
Caddy сам получит и будет продлевать сертификат. Бот при `PUBLIC_URL`+`USE_WEBHOOK=true` сам переключится
на webhook и включит кнопку Mini App.

## 5. Обновление

```bash
cd /opt/sut-bot && git pull && docker compose pull && docker compose up -d
```
Миграции базы бот применяет сам при старте.

## 6. Резервная копия базы

```bash
docker compose exec -T postgres pg_dump -U sutbot sutbot | gzip > /opt/backup/sutbot-$(date +%F).sql.gz
```
Положить в cron раз в сутки.

## 7. Прокси для sut.ru (если IP сервера заблокирован вузом)

sut.ru может резать TCP 80/443 с зарубежных/хостинговых IP (проверка: `curl --max-time 10 https://www.sut.ru/`
— таймаут, при этом `ya.ru` открывается). Тогда запросы к sut.ru/lk.sut.ru пускаем через прокси в разрешённой
сети (Xray с рабочим конфигом, выход которого sut.ru пускает). Поднимается рядом в `docker-compose.proxy.yml`.

Нужен рабочий конфиг VLESS/Reality и т. п., выход которого достаёт sut.ru (проверить заранее). Экспорт из
клиента (в Happ — «Копировать JSON») сохранить в `/opt/sut-bot/proxy.json`, затем:
```bash
mkdir -p /opt/sut-bot/xray
python3 /opt/sut-bot/scripts/make_xray_proxy.py /opt/sut-bot/proxy.json /opt/sut-bot/xray/config.json
```

В `.env` добавить:
```
COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml
SUT_PROXY=socks5h://proxy:1080
```
Поднять и проверить, что через прокси sut.ru доступен:
```bash
cd /opt/sut-bot && docker compose up -d
docker run --rm --network sut-bot_default curlimages/curl -sS -x socks5h://proxy:1080 \
  -o /dev/null -w "%{http_code}\n" --max-time 20 https://www.sut.ru/
```
`xray/config.json` и `proxy.json` содержат секрет VPN — в git не попадают (см. `.gitignore`).

## 8. Автоматическая выкладка из CI

После зелёных проверок в `main` GitHub Actions собирает образ, пушит его в GHCR, затем заходит на сервер по SSH и
выполняет `git reset --hard origin/main`, `docker compose pull` и `docker compose up -d`. Включение:

1. На сервере создать пользователя для деплоя с доступом к Docker и к `/opt/sut-bot`, сгенерировать ключ:
   `ssh-keygen -t ed25519 -f deploy_key -N ""`, публичную часть добавить в `~/.ssh/authorized_keys`.
2. В репозитории: Settings → Secrets and variables → Actions:
   - Secrets: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (приватный ключ), при необходимости `DEPLOY_PORT`;
   - Variables: `DEPLOY_ENABLED=true`, при необходимости `DEPLOY_PATH`.
3. Settings → Environments → создать `production` (можно включить ручное подтверждение выкладки).

`.env` на сервере CI не трогает — он живёт только там.
