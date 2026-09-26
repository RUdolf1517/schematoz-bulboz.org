#!/usr/bin/env bash
# Готовит локальный PostgreSQL (Homebrew на Mac, пакет на Linux) под проект:
#   роль + база → миграции → seed → (по желанию) демо-данные.
# Использование:  ./scripts/setup_local_pg.sh [--demo]
# Параметры берутся из DATABASE_URL в .env (по умолчанию bulboz:bulboz@localhost:5432/bulboz).
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; echo "• создал .env из .env.example"; }
PY=${PY:-.venv/bin/python}
[ -x "$PY" ] || PY=python3

URL=$(grep -E '^DATABASE_URL=' .env | tail -1 | cut -d= -f2-)
URL=${URL:-postgresql+asyncpg://bulboz:bulboz@localhost:5432/bulboz}
read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME < <($PY - "$URL" <<'PYEOF'
import sys
from urllib.parse import urlsplit
u = urlsplit(sys.argv[1].replace("+asyncpg", ""))
print(u.username or "bulboz", u.password or "bulboz", u.hostname or "localhost", u.port or 5432, (u.path or "/bulboz")[1:])
PYEOF
)

command -v psql >/dev/null || {
  echo "✗ Не найден psql. Установи PostgreSQL:"
  echo "    Mac:   brew install postgresql@16 && brew services start postgresql@16"
  echo "           (и добавь в PATH: echo 'export PATH=\"$(brew --prefix 2>/dev/null || echo /opt/homebrew)/opt/postgresql@16/bin:\$PATH\"' >> ~/.zshrc)"
  echo "    Linux: sudo apt install postgresql"
  echo "  Или обойдись без Postgres: ./scripts/reset_dev_db.sh (см. README)"
  exit 1
}

# Суперпользователь: на Mac/Homebrew это твой логин, на Linux — postgres (через sudo).
ADMIN_PSQL=(psql -h "$DB_HOST" -p "$DB_PORT" -d postgres -v ON_ERROR_STOP=1 -qtA)
if ! "${ADMIN_PSQL[@]}" -c "select 1" >/dev/null 2>&1; then
  if command -v sudo >/dev/null && sudo -u postgres psql -qtA -c "select 1" >/dev/null 2>&1; then
    ADMIN_PSQL=(sudo -u postgres psql -v ON_ERROR_STOP=1 -qtA)
  else
    echo "✗ Не могу подключиться к PostgreSQL на $DB_HOST:$DB_PORT."
    echo "  Запущен ли он?  Mac: brew services start postgresql@16"
    exit 1
  fi
fi

if [ "$("${ADMIN_PSQL[@]}" -c "select 1 from pg_roles where rolname='$DB_USER'")" != "1" ]; then
  "${ADMIN_PSQL[@]}" -c "CREATE ROLE \"$DB_USER\" LOGIN PASSWORD '$DB_PASS'"
  echo "• создал роль $DB_USER"
else
  echo "• роль $DB_USER уже есть"
fi
if [ "$("${ADMIN_PSQL[@]}" -c "select 1 from pg_database where datname='$DB_NAME'")" != "1" ]; then
  "${ADMIN_PSQL[@]}" -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\""
  echo "• создал базу $DB_NAME"
else
  echo "• база $DB_NAME уже есть"
fi

# Redis: если не запущен — для разработки переключаемся на in-memory (fakeredis)
REDIS_LINE=$(grep -E '^REDIS_URL=' .env | tail -1 | cut -d= -f2- || true)
if [ "${REDIS_LINE:-}" != "memory://" ] && ! (command -v redis-cli >/dev/null && redis-cli ping >/dev/null 2>&1); then
  if $PY -c "import fakeredis" 2>/dev/null; then
    if grep -qE '^REDIS_URL=' .env; then
      sed -i.bak 's#^REDIS_URL=.*#REDIS_URL=memory://#' .env && rm -f .env.bak
    else
      echo "REDIS_URL=memory://" >> .env
    fi
    echo "• Redis не запущен → в .env поставил REDIS_URL=memory:// (для разработки хватит)"
    echo "  Настоящий Redis: brew install redis && brew services start redis, затем верни REDIS_URL в .env"
  else
    echo "! Redis не запущен. Либо brew install redis && brew services start redis,"
    echo "  либо pip install fakeredis и REDIS_URL=memory:// в .env"
  fi
fi

$PY -m alembic upgrade head
$PY -m flask --app app seed
if [ "${1:-}" = "--demo" ]; then
  $PY scripts/demo_data.py
  $PY -m flask --app app recompute-ratings
fi
$PY -m flask --app app doctor || true
echo
echo "Готово. Админа создай так:  flask --app app create-admin admin admin@example.com"
echo "Запуск:                     hypercorn \"app.asgi:asgi_app\" --bind 0.0.0.0:8000"
