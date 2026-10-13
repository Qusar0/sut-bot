# Разворачивание на сервере

Нужно: VPS с Linux (Ubuntu 22.04/24.04), 1–2 vCPU, 2 ГБ RAM, Docker; домен, указывающий на сервер (для вебхука,
подписки на календарь и Mini App — Telegram и Google требуют HTTPS).

## 1. Сервер

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/Qusar0/sut-bot.git /opt/sut-bot && cd /opt/sut-bot
cp .env.example .env   # заполнить, см. ниже
docker compose up -d --build
docker compose logs -f bot
```

## 2. `.env` на сервере

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

## 3. HTTPS (Caddy — сертификат получает сам)

```bash
apt install -y caddy
cat >/etc/caddy/Caddyfile <<'CADDY'
bot.example.ru {
    reverse_proxy 127.0.0.1:8080
}
CADDY
systemctl reload caddy
```

Проверка: `curl https://bot.example.ru/health` → `ok`.

## 4. Обновление

```bash
cd /opt/sut-bot && git pull && docker compose up -d --build
```
Миграции базы бот применяет сам при старте.

## 5. Резервная копия базы

```bash
docker compose exec -T postgres pg_dump -U sutbot sutbot | gzip > /opt/backup/sutbot-$(date +%F).sql.gz
```
Положить в cron раз в сутки.
