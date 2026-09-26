#!/usr/bin/env bash
# Пересоздаёт локальную dev-БД (pgserver) с миграциями, seed и демо-данными.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
export DATABASE_URL=$($PY scripts/dev_pg.py) REDIS_URL=${REDIS_URL:-memory://}
$PY - <<'PYEOF'
import pgserver
pgserver.get_server(".pgdata", cleanup_mode=None).psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
PYEOF
$PY -m alembic upgrade head
$PY -m flask --app app seed
$PY scripts/demo_data.py
$PY -m flask --app app recompute-ratings
