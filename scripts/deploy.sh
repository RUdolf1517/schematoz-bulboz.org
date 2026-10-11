#!/usr/bin/env bash
# Полная установка schematoz-bulboz.org на чистый Ubuntu 24.04 / Debian 12+ одной командой:
#
#   sudo ./scripts/deploy.sh ДОМЕН EMAIL [ЛОГИН_АДМИНА]
#
# Что делает (повторный запуск безопасен — уже сделанное пропускается, .env и пароли не перезаписываются):
#   1. ставит пакеты: python3.12, postgresql, redis, nginx, certbot, ufw
#   2. создаёт системного пользователя bulboz и копирует код в /srv/bulboz/app
#   3. создаёт роль и базу PostgreSQL со случайным паролем
#   4. пишет .env (случайный SECRET_KEY, DEMO_MODE=0, secure-куки, пустые VAPID-ключи и mailto владельца)
#   5. venv + зависимости, alembic upgrade head, seed, doctor
#   6. создаёт админа со случайным паролем (печатает в конце один раз)
#   7. systemd-сервис bulboz (hypercorn на 127.0.0.1:8000, автоперезапуск)
#      и systemd-таймер bulboz-notifications.timer — `run-notification-jobs` каждые 5 минут (Web Push)
#   8. nginx + HTTPS (scripts/install_nginx.sh)
#   9. ежедневный бэкап БД и загрузок в /var/backups/bulboz (хранится 14 дней)
#  10. файрвол ufw: только SSH и 80/443
#
# Обновление после git pull:  sudo ./scripts/deploy.sh --update
#   • зависимости ставятся в промежуточную копию ($STAGE_DIR): рабочая версия в $APP_DIR
#     не меняется, пока pip и миграции не пройдут успешно;
#   • ошибка pip не запускает миграции и не перезапускает сервис — печатается этап, код возврата,
#     полный блок ошибки resolver’а и путь к полному логу pip;
#   • перед подменой кода сохраняется точка отката ($ROLLBACK_DIR); если сайт не поднялся,
#     deploy сам возвращает прежний код и venv;
#   • .env, база данных и var/uploads не перезаписываются;
#   • Web Push: если VAPID-ключей нет — явное предупреждение с точной командой генерации;
#     недостающие строки VAPID_* дописываются в .env, существующие значения не перезаписываются,
#     новые ключи никогда не генерируются и приватный ключ не попадает в вывод скрипта.
set -euo pipefail

APP_USER=bulboz
APP_HOME=/srv/bulboz
APP_DIR=$APP_HOME/app
APP_PORT=${APP_PORT:-8000}
BACKUP_DIR=/var/backups/bulboz
# Временная сборка и точка отката: рабочая версия не меняется до успешной проверки.
STAGE_DIR=$APP_HOME/stage
ROLLBACK_DIR=$APP_HOME/rollback
LOG_DIR=${LOG_DIR:-/var/log/bulboz}
SYSTEMD_DIR=${SYSTEMD_DIR:-/etc/systemd/system}
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NOTIFY_SERVICE=bulboz-notifications.service
NOTIFY_TIMER=bulboz-notifications.timer

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }
# Тесты подключают скрипт (source) с BULBOZ_DEPLOY_SOURCE_ONLY=1: только функции, без root и systemd.
source_only() { [ "${BULBOZ_DEPLOY_SOURCE_ONLY:-0}" = "1" ]; }
systemd_available() { [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; }

# as_app: выполнить команду от пользователя приложения с рабочим .env.
as_app() { sudo -u "$APP_USER" -H bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && $*"; }
# as_app_in DIR CMD — то же, но в другой папке (промежуточная сборка) с .env рабочей версии.
as_app_in() {
  local dir=$1; shift
  sudo -u "$APP_USER" -H bash -c "cd '$dir' && set -a && . '$APP_DIR/.env' && set +a && $*"
}
# Обёртки над sudo: в тестах переопределяются на прямой запуск.
as_user() { sudo -u "$APP_USER" -H "$@"; }
as_user_env() {
  local home_dir=$1; shift
  sudo -u "$APP_USER" -H env "HOME=$home_dir" "$@"
}
restart_service() { systemctl restart bulboz; }

sync_code_to() {
  local dest=$1
  mkdir -p "$dest"
  # Код копируется в промежуточную папку или в рабочую, но .env, var/ и .venv не трогаются никогда.
  if [ "$SRC_DIR" != "$dest" ]; then
    rsync -a --delete --exclude .venv --exclude .env --exclude var --exclude .pgdata --exclude node_modules \
      "$SRC_DIR"/ "$dest"/
  fi
}

# nginx (www-data) отдаёт /static и /media с диска сам — ему нужно право читать файлы и проходить по папкам.
# Без этого CSS/JS отдаются с 403 и сайт выглядит «голым».
fix_perms() {
  local dir=${1:-$APP_DIR}
  mkdir -p "$APP_HOME" "$dir/var/uploads"
  chown -R "$APP_USER:$APP_USER" "$APP_HOME"
  chmod -R o+rX "$dir/app/static" "$dir/var/uploads" 2>/dev/null || true
  local d="$dir"; while [ "$d" != "/" ]; do chmod o+x "$d"; d=$(dirname "$d"); done
}

# ---------- установка зависимостей ----------
# pip запускается БЕЗ -q: весь вывод идёт в лог, а при ошибке печатается блок resolver’а.
# HOME/PIP_CACHE_DIR/TMPDIR заданы явно (под sudo -u они иначе могут указывать в /root и ломать установку).
run_pip() {
  local venv=$1 logf=$2; shift 2
  as_user_env "$APP_HOME" \
    "PIP_CACHE_DIR=$APP_HOME/.pip-cache" \
    "PIP_DISABLE_PIP_VERSION_CHECK=1" \
    "PIP_NO_INPUT=1" \
    "TMPDIR=$APP_HOME/tmp" \
    "$venv/bin/pip" "$@" >>"$logf" 2>&1
}

# install_deps DIR VENV LOG — окружение и зависимости для указанной копии кода.
# Возвращает код pip (0 = успех); ничего не мигрирует и не перезапускает.
install_deps() {
  local dir=$1 venv=$2 logf=$3 rc=0
  log "Зависимости: $dir"
  mkdir -p "$(dirname "$logf")" "$APP_HOME/.pip-cache" "$APP_HOME/tmp"
  chown -R "$APP_USER:$APP_USER" "$APP_HOME/.pip-cache" "$APP_HOME/tmp" 2>/dev/null || true
  if [ ! -x "$venv/bin/python" ]; then
    if ! command -v python3.12 >/dev/null 2>&1; then
      echo "  ❌ python3.12 не найден — сначала полная установка: sudo $0 ДОМЕН EMAIL" >&2
      return 66
    fi
    log "Создаю venv: $venv"
    as_user python3.12 -m venv "$venv" || rc=$?
    [ "$rc" -eq 0 ] || return "$rc"
  fi
  : >"$logf"; chown "$APP_USER:$APP_USER" "$logf" 2>/dev/null || true
  {
    echo "=== pip config list -v (как $APP_USER, HOME=$APP_HOME) ==="
  } >>"$logf"
  as_user_env "$APP_HOME" "$venv/bin/pip" config list -v >>"$logf" 2>&1 || true
  {
    echo
    echo "=== pip --version ==="
  } >>"$logf"
  run_pip "$venv" "$logf" --version || rc=$?
  if [ "$rc" -eq 0 ]; then
    {
      echo
      echo "=== pip install -U pip ==="
    } >>"$logf"
    run_pip "$venv" "$logf" install -U pip || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    {
      echo
      echo "=== pip install -e $dir ==="
    } >>"$logf"
    run_pip "$venv" "$logf" install -e "$dir" || rc=$?
  fi
  return "$rc"
}

# Печатает блок ошибки resolver’а из лога pip + подсказки по типовым причинам.
resolver_block() {
  awk '
    /ERROR: Cannot install|ERROR: Could not find a version|ERROR: No matching distribution|ERROR: ResolutionImpossible|ERROR: Failed to build/ {print}
    /The conflict is caused by|Additionally, some packages|depends on / {print}
  ' "$1" 2>/dev/null | tail -n 80 || true
}

# Скрывает пароли в URL (index-url с токеном), чтобы диагностика не утекала в логи.
mask_secrets() {
  sed -E 's#(://[^:/@[:space:]]+):[^@[:space:]]+@#\1:***@#g; s#(password|token|_auth|api[_-]?key)=[^[:space:]]+#\1=***#Ig'
}

report_pip_failure() {
  local rc=$1 logf=$2 venv=$3
  {
    echo
    printf '\033[1;31m  ❌ ЭТАП «ЗАВИСИМОСТИ» ПРОВАЛЕН (pip вернул код %s).\033[0m\n' "$rc"
    echo "     Миграции и перезапуск сервиса НЕ выполнялись."
    echo "     Рабочая версия в $APP_DIR не изменена (зависимости ставились в $STAGE_DIR)."
    echo "  Полный лог pip: $logf"
    echo "  ── блок ошибки resolver’а ─────────────────────────────────────────"
    resolver_block "$logf"
    echo "  ── конец блока; ниже последние строки лога ─────────────────────────"
    tail -n 15 "$logf" 2>/dev/null || true
    echo
    if grep -q "no matching distributions available" "$logf" 2>/dev/null; then
      echo "  ⚠ Индекс pip не отдал ни одного подходящего дистрибутива для пакета из блока выше."
      echo "     Частая причина: пакет публикуется только как sdist (без wheel), а pip/индекс запрещают sdist."
      echo "     Известный случай в этом проекте: pywebpush → http-ece (на PyPI только sdist, без wheel)."
      echo "     Проверь политику (вывод ниже, строки PIP_*):"
      echo "       PIP_ONLY_BINARY=:all:  или  pip config set global.only-binary :all:  или зеркало только с wheel."
      echo "     Как починить: разрешить sdist — снять PIP_ONLY_BINARY, 'pip config unset global.only-binary',"
      echo "     либо добавить в зеркало wheel http-ece (собирается из sdist: pip wheel http-ece)."
    elif grep -q "depends on" "$logf" 2>/dev/null; then
      echo "  ⚠ Версии зависимостей действительно конфликтуют — нужен весь блок «The conflict is caused by» выше."
    else
      echo "  ⚠ Причина не распознана автоматически — нужен весь лог: $logf"
    fi
    echo "  ── диагностика pip ────────────────────────────────────────────────"
    {
      "$venv/bin/pip" --version 2>&1 || true
      echo "--- pip config list как $APP_USER (именно так pip и запускается; пароли замаскированы) ---"
      as_user_env "$APP_HOME" "$venv/bin/pip" config list 2>&1 || echo "(не удалось прочитать конфиг пользователя)"
      echo "--- pip config list как root ---"
      "$venv/bin/pip" config list 2>&1 || true
      echo "--- политика wheel/sdist: PIP_*/UV_* в окружении deploy-скрипта ---"
      env | grep -E '^(PIP|UV)_' | mask_secrets || echo "(переменных PIP_* нет)"
      echo "--- политика wheel/sdist: PIP_*/UV_* у $APP_USER ---"
      as_user_env "$APP_HOME" env 2>/dev/null | grep -E '^(PIP|UV)_' | mask_secrets || echo "(переменных PIP_* нет)"
    } | mask_secrets
  } >&2
}

# ---------- миграции и проверки ----------
# Запускается только после успешного pip; ошибка НЕ вызывает перезапуск.
run_migrations_and_checks() {
  local dir=$1 logf=$2 rc=0
  log "Миграции и проверки: $dir"
  mkdir -p "$(dirname "$logf")"
  : >"$logf"; chown "$APP_USER:$APP_USER" "$logf" 2>/dev/null || true
  as_app_in "$dir" ".venv/bin/alembic upgrade head" >>"$logf" 2>&1 || rc=$?
  if [ "$rc" -eq 0 ]; then
    as_app_in "$dir" ".venv/bin/flask --app app seed" >>"$logf" 2>&1 || rc=$?
  fi
  if [ "$rc" -eq 0 ]; then
    as_app_in "$dir" ".venv/bin/flask --app app doctor" >>"$logf" 2>&1 || rc=$?
  fi
  [ "$rc" -eq 0 ] && log "Миграции и проверки — ок (лог: $logf)"
  return "$rc"
}

wait_up() {
  for _ in $(seq 1 60); do curl -fsS -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>/dev/null && return 0; sleep 1; done
  return 1
}

rollback_app() {
  [ -d "$ROLLBACK_DIR/app" ] || { warn "точки отката $ROLLBACK_DIR нет"; return 1; }
  log "Откат: возвращаю прежний код и venv"
  local failed_venv
  failed_venv="$APP_HOME/venv-failed-$(date +%Y%m%d-%H%M%S)"
  [ -d "$APP_DIR/.venv" ] && mv "$APP_DIR/.venv" "$failed_venv"
  rsync -a --delete --exclude .venv --exclude .env --exclude var "$ROLLBACK_DIR/app"/ "$APP_DIR"/
  [ -d "$ROLLBACK_DIR/venv" ] && mv "$ROLLBACK_DIR/venv" "$APP_DIR/.venv"
  fix_perms
  warn "Неудачный venv сохранён: $failed_venv (можно удалить)"
}

# ---------- обновление (--update) ----------
# Порядок: сборка → зависимости → .env → миграции/проверки → точка отката и подмена → перезапуск → отчёт.
update_app() {
  local ts pip_log check_log rc=0
  ts=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$APP_HOME" "$LOG_DIR"
  pip_log="$LOG_DIR/pip-$ts.log"
  check_log="$LOG_DIR/checks-$ts.log"

  log "1/6 Код в промежуточную папку $STAGE_DIR"
  rm -rf "$STAGE_DIR"
  sync_code_to "$STAGE_DIR"
  mkdir -p "$STAGE_DIR/var/uploads"
  if [ -x "$APP_DIR/.venv/bin/python" ]; then
    log "Копирую текущий venv (рабочий не трогаю)"
    cp -a "$APP_DIR/.venv" "$STAGE_DIR/.venv"
  fi
  chown -R "$APP_USER:$APP_USER" "$STAGE_DIR" 2>/dev/null || true

  log "2/6 Зависимости"
  install_deps "$STAGE_DIR" "$STAGE_DIR/.venv" "$pip_log" && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    report_pip_failure "$rc" "$pip_log" "$STAGE_DIR/.venv"
    rm -rf "$STAGE_DIR"
    warn "Обновление отменено на шаге зависимостей: рабочая версия и .env не изменены, миграции не запускались."
    return 1
  fi
  log "Зависимости установлены (лог: $pip_log)"

  log "3/6 Web Push: проверяю .env"
  ensure_vapid_env "$(site_domain)" || true
  warn_web_push_if_unconfigured

  log "4/6 Миграции и проверки (на промежуточной копии, с рабочим .env)"
  run_migrations_and_checks "$STAGE_DIR" "$check_log" && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '\033[1;31m  ❌ ЭТАП «МИГРАЦИИ/ПРОВЕРКИ» ПРОВАЛЕН (код %s).\033[0m\n' "$rc" >&2
    echo "     Лог: $check_log" >&2
    tail -n 25 "$check_log" >&2 || true
    echo "     Рабочая версия не изменена: перезапуск не выполнялся." >&2
    rm -rf "$STAGE_DIR"
    return 1
  fi

  log "5/6 Точка отката и подмена кода"
  rm -rf "$ROLLBACK_DIR"; mkdir -p "$ROLLBACK_DIR"
  rsync -a --exclude .venv --exclude var --exclude .env "$APP_DIR"/ "$ROLLBACK_DIR/app"/
  [ -d "$APP_DIR/.venv" ] && mv "$APP_DIR/.venv" "$ROLLBACK_DIR/venv"
  mv "$STAGE_DIR/.venv" "$APP_DIR/.venv"
  rsync -a --delete --exclude .venv --exclude .env --exclude var "$STAGE_DIR"/ "$APP_DIR"/
  rm -rf "$STAGE_DIR"
  fix_perms
  log "Прежняя версия сохранена в $ROLLBACK_DIR (для отката)"

  log "6/6 Перезапуск сервиса"
  if ! restart_service; then
    warn "systemctl restart bulboz не сработал — откатываюсь"
    rollback_app || true
    restart_service || true
    wait_up || true
    warn "Обновление отменено: вернул прежний код и venv. Смотри: journalctl -u bulboz -n 80"
    return 1
  fi
  if ! wait_up; then
    warn "сайт не отвечает за 60 секунд — откатываюсь на прежнюю версию"
    rollback_app || true
    restart_service || true
    wait_up || true
    warn "Обновление отменено: вернул прежний код и venv. Смотри: journalctl -u bulboz -n 80"
    return 1
  fi
  check_static
  install_notification_timer
  log "Обновлено: сайт отвечает"
  web_push_status
  return 0
}

# ---------- Web Push: .env, предупреждения, планировщик ----------
env_has_var() { grep -qE "^[[:space:]]*$1=" "$APP_DIR/.env" 2>/dev/null; }
# ВАЖНО: пустой результат тоже код 0 — функция вызывается под set -o pipefail в обычном потоке.
env_get_var() {
  grep -E "^[[:space:]]*$1=" "$APP_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- \
    | sed -E "s/^[\"']//; s/[\"'][[:space:]]*$//" | tr -d '\r' || true
}
# Домен сайта для mailto: — из nginx, как в check_static; если не нашли, пусто.
site_domain() {
  grep -oE 'server_name [^ ;]+' /etc/nginx/sites-enabled/* 2>/dev/null | head -1 | awk '{print $2}' | grep -v '^_$' || true
}
# mailto владельца/домена: email из установки, иначе admin@<домен>, иначе явная заглушка.
vapid_subject_for() {
  local owner=${1:-}
  case "$owner" in
    *@*) printf 'mailto:%s' "$owner" ;;
    "") printf 'mailto:CHANGE-ME@example.com' ;;
    *) printf 'mailto:admin@%s' "$owner" ;;
  esac
}
# Явные заглушки, которые нельзя оставлять как production-значение.
vapid_subject_is_placeholder() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    ""|*admin@example.com*|*admin@schematoz-bulboz.org*|*change-me*|*your-domain*) return 0 ;;
    *) return 1 ;;
  esac
}
# Дописывает недостающие VAPID_* в .env. Существующие значения не перезаписывает,
# приватный ключ в лог не попадает (печатаются только имена переменных и статус).
ensure_vapid_env() {
  local owner=${1:-} subject added=0
  [ -f "$APP_DIR/.env" ] || return 0
  subject=$(vapid_subject_for "$owner")
  if env_has_var VAPID_PUBLIC_KEY && env_has_var VAPID_PRIVATE_KEY && env_has_var VAPID_SUBJECT; then
    return 0
  fi
  cp -a "$APP_DIR/.env" "$APP_DIR/.env.bak-vapid-$(date +%Y%m%d-%H%M%S)"
  {
    if ! env_has_var VAPID_PUBLIC_KEY || ! env_has_var VAPID_PRIVATE_KEY; then
      cat <<EOF

# --- Web Push (VAPID) ---
# Пустые значения = Web Push выключен: сайт и внутренние уведомления работают как обычно.
# Ключи создаёт команда (из папки приложения):
#   sudo -u $APP_USER $APP_DIR/.venv/bin/flask --app app generate-vapid
# Затем подставь сюда VAPID_PUBLIC_KEY и VAPID_PRIVATE_KEY (значение base64:…) из вывода команды
# и перезапусти: sudo systemctl restart bulboz
EOF
      env_has_var VAPID_PUBLIC_KEY || printf 'VAPID_PUBLIC_KEY=\n'
      env_has_var VAPID_PRIVATE_KEY || printf 'VAPID_PRIVATE_KEY=\n'
      added=1
    fi
    if ! env_has_var VAPID_SUBJECT; then
      printf '# VAPID_SUBJECT: контакт владельца домена (RFC 8292), например mailto:you@your-domain\n'
      printf 'VAPID_SUBJECT=%s\n' "$subject"
      added=1
    fi
  } >>"$APP_DIR/.env"
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
  if [ "$added" = 1 ]; then
    log "В .env добавлены недостающие строки VAPID (существующие значения не тронуты)"
  fi
  return 0
}

warn_web_push_if_unconfigured() {
  local pub priv sub
  pub=$(env_get_var VAPID_PUBLIC_KEY); priv=$(env_get_var VAPID_PRIVATE_KEY); sub=$(env_get_var VAPID_SUBJECT)
  if [ -n "$pub" ] && [ -n "$priv" ]; then
    return 0
  fi
  {
    echo
    printf '\033[1;33m  ⚠ Web Push НЕ настроен: в %s нет VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY.\033[0m\n' "$APP_DIR/.env"
    echo "     Обычный сайт, вход, игры и внутренние уведомления (/notifications) работают как всегда;"
    echo "     браузеры просто не получают push, а кнопка в «Настройки → 🔔 Уведомления» выключена."
    echo
    echo "     Чтобы включить (3 шага):"
    echo "       1) sudo -u $APP_USER $APP_DIR/.venv/bin/flask --app app generate-vapid"
    echo "       2) добавить в $APP_DIR/.env три строки из вывода команды:"
    echo "            VAPID_PUBLIC_KEY=<публичный ключ>"
    echo "            VAPID_PRIVATE_KEY=<значение base64:…>"
    echo "            VAPID_SUBJECT=mailto:<реальный адрес владельца домена>"
    echo "       3) sudo systemctl restart bulboz"
    echo
    echo "     Ключи генерируются один раз; deploy их не создаёт и не перезаписывает,"
    echo "     приватный ключ не хранится в git и не выводится в логи."
    if vapid_subject_is_placeholder "$sub"; then
      echo "     VAPID_SUBJECT сейчас не задан или похож на пример/заглушку — укажи свой адрес владельца."
    fi
  } >&2
}

web_push_status() {
  local pub priv sub configured=false
  pub=$(env_get_var VAPID_PUBLIC_KEY); priv=$(env_get_var VAPID_PRIVATE_KEY); sub=$(env_get_var VAPID_SUBJECT)
  if [ -n "$pub" ] && [ -n "$priv" ]; then configured=true; fi
  if [ "$configured" = true ]; then
    log "Web Push: ключи в .env есть (публичный ключ …${pub: -8})"
    if vapid_subject_is_placeholder "$sub"; then
      warn "VAPID_SUBJECT=${sub:-не задан} — нужен реальный адрес владельца домена (mailto:), иначе push-сервисы отклонят отправку."
    else
      log "VAPID_SUBJECT: $sub"
    fi
  else
    warn "Web Push не настроен; сайт и внутренние уведомления работают. Включить: sudo -u $APP_USER $APP_DIR/.venv/bin/flask --app app generate-vapid → VAPID_* в $APP_DIR/.env → sudo systemctl restart bulboz"
  fi
  if systemd_available && systemctl is-active --quiet "$NOTIFY_TIMER" 2>/dev/null; then
    log "Планировщик напоминаний и push: $NOTIFY_TIMER активен (каждые 5 минут)"
  else
    warn "Планировщик $NOTIFY_TIMER не активен — push и напоминания не отправляются!"
    notification_cron_hint
  fi
}

notification_cron_hint() {
  cat >&2 <<EOF
     Включи таймер:  sudo systemctl enable --now $NOTIFY_TIMER
     Если systemd нет — cron-задание раз в 5 минут:
       echo '*/5 * * * * $APP_USER cd $APP_DIR && $APP_DIR/.venv/bin/flask --app app run-notification-jobs >> $LOG_DIR/notifications.log 2>&1' | sudo tee /etc/cron.d/bulboz-notifications
EOF
}

# Идемпотентно ставит systemd service+timer для `run-notification-jobs` от пользователя bulboz.
install_notification_timer() {
  if ! systemd_available; then
    warn "systemd недоступен — планировщик push не установлен"
    notification_cron_hint
    return 0
  fi
  mkdir -p "$LOG_DIR"; chown "$APP_USER:$APP_USER" "$LOG_DIR"
  cat >"$SYSTEMD_DIR/$NOTIFY_SERVICE" <<EOF
[Unit]
Description=schematoz-bulboz.org: напоминания и отправка Web Push
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/flask --app app run-notification-jobs
Nice=10
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$APP_DIR/var
EOF
  cat >"$SYSTEMD_DIR/$NOTIFY_TIMER" <<EOF
[Unit]
Description=run-notification-jobs каждые 5 минут (Web Push и напоминания)

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
RandomizedDelaySec=20s
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload 2>/dev/null || true
  if ! systemctl enable --now "$NOTIFY_TIMER" >/dev/null 2>&1; then
    warn "не удалось включить $NOTIFY_TIMER"
    notification_cron_hint
    return 0
  fi
  log "Планировщик: $NOTIFY_TIMER включён (каждые 5 минут; журнал: journalctl -u ${NOTIFY_SERVICE%.service})"
}

# CSS через nginx должен отдаваться с 200, иначе сайт «страшненький»
check_static() {
  local dom code
  dom=$(grep -oE 'server_name [^ ;]+' /etc/nginx/sites-enabled/* 2>/dev/null | head -1 | awk '{print $2}')
  [ -n "$dom" ] || return 0
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $dom" "http://127.0.0.1/static/site.css")
  case "$code" in
    200|301|302|308) log "Статика через nginx: $code — ок" ;;
    *) echo "  ⚠ /static/site.css через nginx отдаёт $code. Смотри: tail -20 /var/log/nginx/error.log" ;;
  esac
}

# Роль и пароль PostgreSQL всегда приводим к тому, что записано в .env (DATABASE_URL).
# Тогда не бывает «password authentication failed», если роль создали раньше руками или .env правили.
sync_db_role() {
  local url user pass host db port err hba
  url=$(grep -E '^DATABASE_URL=' "$APP_DIR/.env" | tail -1 | cut -d= -f2- | tr -d "\"' ")
  [ -n "$url" ] || die "в .env нет DATABASE_URL"
  # postgresql+asyncpg://USER:PASS@HOST:PORT/DB
  user=$(sed -E 's#^[^:]+://([^:@/]+).*#\1#' <<<"$url")
  pass=$(sed -E 's#^[^:]+://[^:@/]+:([^@]*)@.*#\1#' <<<"$url")
  host=$(sed -E 's#^.*@([^:/]+).*#\1#' <<<"$url")
  db=$(sed -E 's#^.*/([^/?]+)(\?.*)?$#\1#' <<<"$url")
  port=$(sed -nE 's#^.*@[^:/]+:([0-9]+)/.*#\1#p' <<<"$url"); port=${port:-5432}
  case "$host" in localhost|127.0.0.1|::1) ;; *) log "БД на внешнем хосте $host — роль не трогаю"; return;; esac
  [[ "$user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && "$db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "странное имя роли/базы в DATABASE_URL"
  [[ "$pass" != *"'"* && "$pass" != *"%"* && -n "$pass" ]] || die "пароль БД в .env пустой или содержит ' или % — замени на hex (openssl rand -hex 16)"
  # кластер на этом порту есть и запущен?
  if command -v pg_lsclusters >/dev/null; then
    if ! pg_lsclusters -h | awk '{print $3}' | grep -qx "$port"; then
      pg_lsclusters
      local ports; ports=$(pg_lsclusters -h | awk '{print $3}' | sort -u)
      if [ "$(wc -l <<<"$ports")" -eq 1 ] && [ -n "$ports" ]; then
        log "В .env порт $port, а PostgreSQL один и слушает $ports — исправляю .env"
        cp "$APP_DIR/.env" "$APP_DIR/.env.bak-$(date +%s)"
        sed -i -E "s#^(DATABASE_URL=[^@]*@[^:/]+)(:[0-9]+)?/#\\\\1:$ports/#" "$APP_DIR/.env"
        port=$ports
      else
        die "в DATABASE_URL порт $port, а кластера на нём нет; кластеров несколько (список выше) — укажи нужный порт в .env"
      fi
    fi
    pg_lsclusters -h | awk -v p="$port" '$3==p && $4!="online" {print $1, $2}' | while read -r v c; do
      log "Запускаю кластер PostgreSQL $v/$c"; pg_ctlcluster "$v" "$c" start; done
  fi
  log "PostgreSQL: роль $user, база $db (пароль — из .env)"
  if sudo -u postgres psql -p "$port" -tAc "SELECT 1 FROM pg_roles WHERE rolname='$user'" | grep -q 1; then
    sudo -u postgres psql -p "$port" -qc "ALTER ROLE \"$user\" WITH LOGIN PASSWORD '$pass';"
  else
    sudo -u postgres psql -p "$port" -qc "CREATE ROLE \"$user\" LOGIN PASSWORD '$pass';"
  fi
  sudo -u postgres psql -p "$port" -tAc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
    || sudo -u postgres createdb -p "$port" -O "$user" "$db"
  sudo -u postgres psql -p "$port" -qc "ALTER DATABASE \"$db\" OWNER TO \"$user\";"
  sudo -u postgres psql -p "$port" -d "$db" -qc "ALTER SCHEMA public OWNER TO \"$user\";"
  # stdout psql гасится, а stderr забирает вызывающий: err=$(try_login 2>&1)
  try_login() { PGPASSWORD="$pass" psql -h 127.0.0.1 -p "$port" -U "$user" -d "$db" -tAc "SELECT 1" >/dev/null; }
  if ! err=$(try_login 2>&1); then
    echo "  psql: $err"
    # чиним pg_hba: свой пользователь по паролю с localhost — первым правилом
    hba=$(sudo -u postgres psql -p "$port" -tAc "SHOW hba_file" 2>/dev/null || true)
    if [ -f "$hba" ] && ! grep -q "# bulboz-deploy" "$hba"; then
      log "Добавляю в $hba правило входа по паролю для $user"
      cp "$hba" "$hba.bak-$(date +%s)"
      { echo "host    $db    $user    127.0.0.1/32    scram-sha-256    # bulboz-deploy"
        echo "host    $db    $user    ::1/128         scram-sha-256    # bulboz-deploy"
        cat "$hba"; } > "$hba.new"
      mv "$hba.new" "$hba"; chown postgres:postgres "$hba"; chmod 640 "$hba"
    fi
    # пароль мог быть сохранён в md5 при старом password_encryption — перезадаём в scram
    sudo -u postgres psql -p "$port" -qc "SET password_encryption='scram-sha-256'; ALTER ROLE \"$user\" WITH PASSWORD '$pass';"
    sudo -u postgres psql -p "$port" -qc "SELECT pg_reload_conf();" >/dev/null
    sleep 1
    err=$(try_login 2>&1) || die "всё ещё не входит как $user на 127.0.0.1:$port: $err"
  fi
  log "Вход в PostgreSQL по паролю из .env — ок"
}

# ---------- точка входа ----------
if source_only; then
  # shellcheck disable=SC2317  # при `source` этот return выходит; при обычном запуске он не срабатывает
  return 0 2>/dev/null || true
fi
[ "$(id -u)" -eq 0 ] || die "запусти через sudo"

# ---------- режим обновления ----------
if [ "${1:-}" = "--update" ]; then
  [ -f "$APP_DIR/.env" ] || die "сначала полная установка"
  sync_db_role
  if ! update_app; then
    die "обновление не применено — рабочая версия осталась прежней (подробности выше)"
  fi
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
sync_code_to "$APP_DIR"
fix_perms "$APP_DIR"

# ---------- 3–4. база и .env ----------
if [ ! -f "$APP_DIR/.env" ]; then
  log ".env"
  DB_PASS=$(openssl rand -hex 16)
  cat > "$APP_DIR/.env" <<EOF
SECRET_KEY=$(openssl rand -hex 32)
DATABASE_URL=postgresql+asyncpg://$APP_USER:$DB_PASS@localhost:5432/$APP_USER
REDIS_URL=redis://localhost:6379/0
SESSION_COOKIE_SECURE=1
DEMO_MODE=0
ANTIBOT_DISABLED=0
KREMLE_AUTO_GUARD=1
UPLOAD_DIR=$APP_DIR/var/uploads
# --- Web Push (VAPID) ---
# Пустые ключи = Web Push выключен; сайт и внутренние уведомления работают.
# Сгенерировать: sudo -u $APP_USER $APP_DIR/.venv/bin/flask --app app generate-vapid
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
# Контакт владельца для push-сервисов (RFC 8292): реальный адрес, не пример.
VAPID_SUBJECT=mailto:$EMAIL
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
else
  log ".env уже есть — не трогаю"
fi
sync_db_role
grep -q "^SECRET_KEY=change-me\|^SECRET_KEY=dev-secret" "$APP_DIR/.env" && die "в .env дефолтный SECRET_KEY"
grep -q "^DEMO_MODE=1\|^ANTIBOT_DISABLED=1" "$APP_DIR/.env" && die "в .env включён DEMO_MODE или ANTIBOT_DISABLED — на проде нельзя"
ensure_vapid_env "$EMAIL"

# ---------- 5. зависимости, миграции ----------
mkdir -p "$LOG_DIR"
DEPS_LOG="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
install_deps "$APP_DIR" "$APP_DIR/.venv" "$DEPS_LOG" && rc=0 || rc=$?
if [ "$rc" -ne 0 ]; then
  report_pip_failure "$rc" "$DEPS_LOG" "$APP_DIR/.venv"
  die "установка зависимостей не удалась (pip код $rc): миграции не запускались, сайт не перезапускался"
fi
run_migrations_and_checks "$APP_DIR" "$LOG_DIR/checks-$(date +%Y%m%d-%H%M%S).log" \
  || die "миграции/проверки не прошли — смотри лог выше"
fix_perms "$APP_DIR"

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
cat > "$SYSTEMD_DIR/bulboz.service" <<EOF
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
wait_up || die "приложение не стартовало за 60 с: journalctl -u bulboz -n 50"
install_notification_timer

# ---------- 8. nginx + HTTPS ----------
log "nginx + HTTPS"
export APP_PORT APP_DIR
UPLOAD_DIR=$APP_DIR/var/uploads
export UPLOAD_DIR
"$APP_DIR/scripts/install_nginx.sh" "$DOMAIN" "$EMAIL"

check_static

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
  printf '\n  Админ: \033[1m%s\033[0m   пароль: \033[1m%s\033[0m\n  Сохрани его — больше он не покажется. Смени в «Настройки → Пароль».\\n' "$ADMIN" "$ADMIN_PASS"
fi
web_push_status
cat <<EOF

  Дальше руками:
   • зайди в /admin и заполни Правила, Соглашение, Политику, Реквизиты, FAQ
   • пройди капчу kremle-detect вручную (единственное, что не проверено e2e)
   • Web Push (необязательно): sudo -u $APP_USER $APP_DIR/.venv/bin/flask --app app generate-vapid
     → VAPID_* в $APP_DIR/.env → sudo systemctl restart bulboz
   • планировщик напоминаний и push уже поставлен: $NOTIFY_TIMER (каждые 5 минут)
   • бэкапы лежат в $BACKUP_DIR — копируй их на другой сервер (rsync/S3)
   • логи: journalctl -u bulboz -f ; журнал планировщика: journalctl -u ${NOTIFY_SERVICE%.service}
   • обновление: cd ~/schematoz-bulboz.org && git pull && sudo ./scripts/deploy.sh --update
EOF
