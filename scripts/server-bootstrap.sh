#!/usr/bin/env bash
# Первичная настройка сервера под sut-bot. Запускать от root на свежей Ubuntu 22.04/24.04:
#
#   CI_PUBKEY='ssh-ed25519 AAAA... sut-bot-ci-deploy' bash scripts/server-bootstrap.sh
#
# Необязательно ADMIN_PUBKEY='ssh-ed25519 ...' — личный ключ для входа ssh deploy@<IP>.
#
# Делает: swap 2 ГБ, Docker, firewall, пользователь deploy (вход только по ключу),
# клон репозитория в /opt/sut-bot, заготовка .env, отключение входа по паролю.
# Скрипт идемпотентный — можно запускать повторно.
set -euo pipefail

REPO="${REPO:-https://github.com/Qusar0/sut-bot.git}"
APP_DIR="${APP_DIR:-/opt/sut-bot}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"

[[ $EUID -eq 0 ]] || { echo "Запускать от root"; exit 1; }
[[ -n "${CI_PUBKEY:-}" ]] || { echo "Не задан CI_PUBKEY (публичный ключ для CI-деплоя)"; exit 1; }

echo "==> Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ufw ca-certificates

echo "==> Swap"
# многие образы Ubuntu уже идут со swap (/swap.img и т. п.) — второй файл только зря ест диск
if [ -z "$(swapon --show)" ]; then
  echo "   swap не найден — создаю 2 ГБ"
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
  echo "   swap уже есть, пропускаю: $(swapon --show --noheadings | awk '{print $1}' | tr '\n' ' ')"
fi
sysctl -wq vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf

echo "==> Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

echo "==> Firewall (22, 80, 443)"
ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "==> Пользователь $DEPLOY_USER"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
AUTH="/home/$DEPLOY_USER/.ssh/authorized_keys"
touch "$AUTH"
grep -qF "$CI_PUBKEY" "$AUTH" || echo "$CI_PUBKEY" >> "$AUTH"
# личный ключ администратора для интерактивного входа (необязательно)
if [[ -n "${ADMIN_PUBKEY:-}" ]]; then
  grep -qF "$ADMIN_PUBKEY" "$AUTH" || echo "$ADMIN_PUBKEY" >> "$AUTH"
fi
chmod 600 "$AUTH"
chown "$DEPLOY_USER:$DEPLOY_USER" "$AUTH"

echo "==> Репозиторий в $APP_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO" "$APP_DIR"
fi
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

echo "==> Заготовка .env"
ENV="$APP_DIR/.env"
if [[ ! -f "$ENV" ]]; then
  cp "$APP_DIR/.env.example" "$ENV"
  PGPASS="$(openssl rand -hex 24)"
  WHSECRET="$(openssl rand -hex 24)"
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PGPASS|" "$ENV"
  sed -i "s|^WEBHOOK_SECRET=.*|WEBHOOK_SECRET=$WHSECRET|" "$ENV"
  sed -i "s|^USE_WEBHOOK=.*|USE_WEBHOOK=false|" "$ENV"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV"
  chmod 600 "$ENV"
fi

echo "==> Защита SSH: вход по паролю выключен, root — только по ключу"
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-sut-bot.conf <<'SSHD'
PasswordAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
SSHD
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true

cat <<DONE

================= ГОТОВО =================
Сервер настроен. Дальше:

1) Заполнить секреты в $ENV (от пользователя $DEPLOY_USER):
     BOT_TOKEN, ENCRYPTION_KEY, ADMIN_ID
   POSTGRES_PASSWORD и WEBHOOK_SECRET уже сгенерированы.

2) Сделать пакет образа публичным в GHCR (Packages -> sut-bot -> Package settings -> Change visibility -> Public),
   либо залогиниться: docker login ghcr.io -u <github-user> (токен с read:packages).

3) Поднять бота:
     cd $APP_DIR
     sudo -u $DEPLOY_USER docker compose pull   # если образ ещё не в GHCR: docker compose up -d --build
     sudo -u $DEPLOY_USER docker compose up -d
     docker compose logs -f bot

Проверка входа по ключу (с вашей машины):  ssh $DEPLOY_USER@<IP>
Вход по паролю отключён — запасной доступ через веб-консоль панели хостинга.
=========================================
DONE
