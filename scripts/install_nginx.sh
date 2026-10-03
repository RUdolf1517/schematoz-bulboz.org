#!/usr/bin/env bash
# Установка nginx перед hypercorn для schematoz-bulboz.org (Debian/Ubuntu).
#
#   sudo ./scripts/install_nginx.sh schematoz-bulboz.org            # только http
#   sudo ./scripts/install_nginx.sh schematoz-bulboz.org me@mail.ru # + HTTPS от Let's Encrypt
#
# Переменные (необязательно): APP_PORT=8000  APP_DIR=<корень репо>  UPLOAD_DIR=$APP_DIR/var/uploads
set -euo pipefail

DOMAIN="${1:?Укажи домен: sudo $0 example.org [email]}"
EMAIL="${2:-}"
APP_PORT="${APP_PORT:-8000}"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
UPLOAD_DIR="${UPLOAD_DIR:-$APP_DIR/var/uploads}"
CONF="/etc/nginx/sites-available/bulboz.conf"

[ "$(id -u)" -eq 0 ] || { echo "Запусти через sudo"; exit 1; }
command -v apt-get >/dev/null || { echo "Скрипт рассчитан на Debian/Ubuntu (apt)"; exit 1; }

echo "→ ставлю nginx"
apt-get update -qq
apt-get install -y -qq nginx >/dev/null

mkdir -p "$UPLOAD_DIR"
# nginx (www-data) должен читать статику и загрузки
chmod o+rx "$APP_DIR" "$APP_DIR/app" "$APP_DIR/app/static" "$UPLOAD_DIR" 2>/dev/null || true
d="$APP_DIR"; while [ "$d" != "/" ]; do chmod o+x "$d" 2>/dev/null || true; d="$(dirname "$d")"; done

echo "→ пишу $CONF"
cat > "$CONF" <<EOF
# сгенерировано scripts/install_nginx.sh
limit_req_zone \$binary_remote_addr zone=bulboz_api:10m rate=20r/s;

upstream bulboz_app {
    server 127.0.0.1:${APP_PORT};
    keepalive 16;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} www.${DOMAIN};

    client_max_body_size 10m;          # загрузки картинок до 8 МБ
    server_tokens off;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header X-Frame-Options SAMEORIGIN always;

    # статика и загрузки — напрямую с диска, мимо Python
    location /static/ {
        alias ${APP_DIR}/app/static/;
        expires 7d;
        access_log off;
    }
    location /media/ {
        alias ${UPLOAD_DIR}/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        add_header X-Content-Type-Options nosniff always;
        access_log off;
    }

    location /api/ {
        limit_req zone=bulboz_api burst=40 nodelay;
        proxy_pass http://bulboz_app;
        include /etc/nginx/bulboz_proxy.conf;
    }

    location / {
        proxy_pass http://bulboz_app;
        include /etc/nginx/bulboz_proxy.conf;
    }
}
EOF

cat > /etc/nginx/bulboz_proxy.conf <<'EOF'
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
# ВАЖНО: перезаписываем, а не дописываем — иначе клиент подделает IP и обойдёт антиспам
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_read_timeout 60s;
EOF

ln -sf "$CONF" /etc/nginx/sites-enabled/bulboz.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx >/dev/null
systemctl reload nginx

if [ -n "$EMAIL" ]; then
    echo "→ HTTPS через certbot"
    apt-get install -y -qq certbot python3-certbot-nginx >/dev/null
    # www.ДОМЕН добавляем в сертификат, только если для него есть DNS-запись — иначе certbot упадёт
    if getent hosts "www.$DOMAIN" >/dev/null; then
        certbot --nginx -n --agree-tos -m "$EMAIL" --redirect -d "$DOMAIN" -d "www.$DOMAIN"
    else
        echo "  (www.$DOMAIN не найден в DNS — сертификат только на $DOMAIN)"
        certbot --nginx -n --agree-tos -m "$EMAIL" --redirect -d "$DOMAIN"
    fi
fi

cat <<EOF

✅ nginx готов: http${EMAIL:+s}://${DOMAIN}
   Приложение должно слушать 127.0.0.1:${APP_PORT}, например:
     hypercorn app.asgi:asgi_app --bind 127.0.0.1:${APP_PORT} --workers 2
   Загрузки: ${UPLOAD_DIR} (тот же путь задай в UPLOAD_DIR приложения)
   Проверка:  curl -I http://${DOMAIN}/static/site.css
EOF
