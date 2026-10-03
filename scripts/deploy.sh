#!/usr/bin/env bash
# Полная установка schematoz-bulboz.org на чистый Ubuntu 24.04 / Debian 12+ одной командой:
#
#   sudo ./scripts/deploy.sh ДОМЕН EMAIL [ЛОГИН_АДМИНА]
#
# Что делает (повторный запуск безопасен — уже сделанное пропускается, .env и пароли не перезаписываются):
#   1. ставит пакеты: python3.12, postgresql, redis, nginx, certbot, ufw
#   2. создаёт системного пользователя bulboz и копирует код в /srv/bulboz/app
#   3. создаёт роль и базу PostgreSQL со случайным паролем
#   4. пишет .env (случайный SECRET_KEY, DEMO_MODE=0, secure-куки)
#   5. venv + зависимости, alembic upgrade head, seed
#   6. создаёт админа со случайным паролем (печатает в конце один раз)
#   7. systemd-сервис bulboz (hypercorn на 127.0.0.1:8000, автоперезапуск)
#   8. nginx + HTTPS (scripts/install_nginx.sh)
#   9. ежедневный бэкап БД и загрузок в /var/backups/bulboz (хранится 14 дней)
#  10. файрвол ufw: только SSH и 80/443
#
# Обновление после git pull:  sudo ./scripts/deploy.sh --update
set -euo pipefail

APP_USER=bulboz
APP_HOME=/srv/bulboz
APP_DIR=$APP_HOME/app
APP_PORT=${APP_PORT:-8000}
BACKUP_DIR=/var/backups/bulboz
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "запусти через sudo"

as_app() { sudo -u "$APP_USER" -H bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && $*"; }

sync_code() {
  log "Код → $APP_DIR"
  mkdir -p "$APP_DIR"
  if [ "$SRC_DIR" != "$APP_DIR" ]; then
    rsync -a --delete --exclude .venv --exclude .env --exclude var --exclude .pgdata --exclude node_modules \
      "$SRC_DIR"/ "$APP_DIR"/
  fi
  mkdir -p "$APP_DIR/var/uploads"
  chown -R "$APP_USER:$APP_USER" "$APP_HOME"
}

install_deps_and_migrate() {
  log "Зависимости и миграции"
  [ -x "$APP_DIR/.venv/bin/python" ] || sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/.venv"
  sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -U pip
  sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
  as_app ".venv/bin/alembic upgrade head"
  as_app ".venv/bin/flask --app app seed"
  as_app ".venv/bin/flask --app app doctor" || die "flask doctor нашёл проблему — см. вывод выше"
}

# ---------- режим обновления ----------
if [ "${1:-}" = "--update" ]; then
  [ -f "$APP_DIR/.env" ] || die "сначала полная установка"
  sync_code
  install_deps_and_migrate
  systemctl restart bulboz
  sleep 2; curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/" && log "Обновлено, сайт отвечает" || die "сайт не отвечает: journalctl -u bulboz -n 50"
  exit 0
fi

DOMAIN=${1:-}; EMAIL=${2:-}; ADMIN=${3:-admin}
[ -n "$DOMAIN" ] && [ -n "$EMAIL" ] || die "использование: sudo $0 ДОМЕН EMAIL [ЛОГИН_АДМИНА]"

# ---------- 1. пакеты ----------
log "Пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
if ! apt-cache show python3.12 >/dev/null 2>&1; then
  apt-get install -y -q software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa && apt-get update -q
fi
apt-get install -y -q python3.12 python3.12-venv postgresql redis-server nginx certbot python3-certbot-nginx ufw rsync curl openssl
systemctl enable --now postgresql redis-server

# ---------- 2. пользователь ----------
id "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home "$APP_HOME" "$APP_USER"
sync_code

# ---------- 3–4. база и .env ----------
if [ ! -f "$APP_DIR/.env" ]; then
  log "PostgreSQL и .env"
  DB_PASS=$(openssl rand -hex 16)
  if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" | grep -q 1; then
    sudo -u postgres psql -qc "ALTER ROLE $APP_USER PASSWORD '$DB_PASS';"
  else
    sudo -u postgres psql -qc "CREATE ROLE $APP_USER LOGIN PASSWORD '$DB_PASS';"
  fi
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$APP_USER'" | grep -q 1 \
    || sudo -u postgres createdb -O "$APP_USER" "$APP_USER"
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=postgresql+asyncpg://$APP_USER:$DB_PASS@localhost:5432/$APP_USER
REDIS_URL=redis://localhost:6379/0
SESSION_COOKIE_SECURE=1
DEMO_MODE=0
ANTIBOT_DISABLED=0
KREMLE_AUTO_GUARD=1
UPLOAD_DIR=$APP_DIR/var/uploads
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
else
  log ".env уже есть — не трогаю"
fi
grep -q "^SECRET_KEY=change-me\|^SECRET_KEY=dev-secret" "$APP_DIR/.env" && die "в .env дефолтный SECRET_KEY"
grep -q "^DEMO_MODE=1\|^ANTIBOT_DISABLED=1" "$APP_DIR/.env" && die "в .env включён DEMO_MODE или ANTIBOT_DISABLED — на проде нельзя"

# ---------- 5. зависимости, миграции ----------
install_deps_and_migrate

# ---------- 6. админ ----------
ADMIN_PASS=""
if [ ! -f "$APP_HOME/.admin_created" ]; then
  log "Админ @$ADMIN"
  ADMIN_PASS=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
  as_app ".venv/bin/flask --app app create-admin '$ADMIN' 'admin@$DOMAIN' --password '$ADMIN_PASS'"
  touch "$APP_HOME/.admin_created"
fi

# ---------- 7. systemd ----------
log "systemd-сервис"
cat > /etc/systemd/system/bulboz.service <<EOF
[Unit]
Description=schematoz-bulboz.org
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/hypercorn app.asgi:asgi_app --bind 127.0.0.1:$APP_PORT --workers 2
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$APP_DIR/var

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable bulboz >/dev/null
systemctl restart bulboz
for _ in $(seq 1 20); do curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/" && break; sleep 1; done
curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/" || die "приложение не стартовало: journalctl -u bulboz -n 50"

# ---------- 8. nginx + HTTPS ----------
log "nginx + HTTPS"
APP_PORT=$APP_PORT APP_DIR=$APP_DIR UPLOAD_DIR=$APP_DIR/var/uploads "$APP_DIR/scripts/install_nginx.sh" "$DOMAIN" "$EMAIL"

# ---------- 9. бэкапы ----------
log "Бэкапы → $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"; chown postgres:postgres "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
cat > /etc/cron.daily/bulboz-backup <<EOF
#!/bin/sh
set -e
D=\$(date +%F)
sudo -u postgres pg_dump -Fc $APP_USER > $BACKUP_DIR/db-\$D.dump
tar -czf $BACKUP_DIR/uploads-\$D.tar.gz -C $APP_DIR/var uploads
find $BACKUP_DIR -type f -mtime +14 -delete
EOF
chmod +x /etc/cron.daily/bulboz-backup

# ---------- 10. файрвол ----------
log "Файрвол"
ufw allow OpenSSH >/dev/null; ufw allow 'Nginx Full' >/dev/null; ufw --force enable >/dev/null

log "Готово: https://$DOMAIN"
if [ -n "$ADMIN_PASS" ]; then
  printf '\n  Админ: \033[1m%s\033[0m   пароль: \033[1m%s\033[0m\n  Сохрани его — больше он не покажется. Смени в «Настройки → Пароль».\n' "$ADMIN" "$ADMIN_PASS"
fi
cat <<EOF

  Дальше руками:
   • зайди в /admin и заполни Правила, Соглашение, Политику, Реквизиты, FAQ
   • пройди капчу kremle-detect вручную (единственное, что не проверено e2e)
   • бэкапы лежат в $BACKUP_DIR — копируй их на другой сервер (rsync/S3)
   • логи: journalctl -u bulboz -f
   • обновление: cd ~/schematoz-bulboz.org && git pull && sudo ./scripts/deploy.sh --update
EOF
