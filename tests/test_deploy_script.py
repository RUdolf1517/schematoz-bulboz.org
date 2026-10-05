"""Тесты deploy-скрипта: диагностика pip, безопасный порядок обновления, VAPID-предупреждения.

Скрипт подключается через `source` с BULBOZ_DEPLOY_SOURCE_ONLY=1 (без root и systemd).
sudo-обёртки, рестарт и curl переопределяются на заглушки, а rsync — на минимальный шим
(в контейнерах без rsync), так что проверяется реальный код скрипта, а не его копия.
"""
from __future__ import annotations

import os
import pwd
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="для тестов deploy нужен bash")

RESOLVER_ERROR = """Collecting pywebpush>=2.0 (from schematoz-bulboz==0.1.0)
Collecting http-ece>=1.1.0 (from pywebpush>=2.0)
ERROR: Cannot install schematoz-bulboz because these package versions have conflicting dependencies.

The conflict is caused by:
    pywebpush 2.5.0 depends on http-ece>=1.1.0
    pywebpush 2.4.0 depends on http-ece>=1.1.0

Additionally, some packages in these conflicts have no matching distributions available for your environment:
    http-ece

To fix this you could try to:
1. loosen the range of package versions you've specified
2. remove package versions to allow pip to attempt to solve the dependency conflict

ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/
"""

# Минимальный rsync для тестов: -a, --delete, --exclude TOPNAME, src/ dst/.
RSYNC_SHIM = """#!/usr/bin/env bash
set -euo pipefail
exclude=(); delete=0; pos=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exclude) exclude+=("$2"); shift 2 ;;
    --delete) delete=1; shift ;;
    -a|--archive|-r|-rlptgoD) shift ;;
    *) pos+=("$1"); shift ;;
  esac
done
src=${pos[0]:?}; dst=${pos[1]:?}
mkdir -p "$dst"
copy_tree() {  # $1 = откуда, $2 = куда, $3 = только-добавить/1 = с удалением
  local from=$1 to=$2 prune=${3:-0} entry name skip
  while IFS= read -r -d '' entry; do
    name=$(basename "$entry")
    skip=0
    for ex in "${exclude[@]:-}"; do [ "$name" = "$ex" ] && skip=1; done
    [ "$skip" = 1 ] && continue
    cp -a "$entry" "$to"/
  done < <(find "$from" -mindepth 1 -maxdepth 1 -print0)
  if [ "$prune" = 1 ]; then
    while IFS= read -r -d '' entry; do
      name=$(basename "$entry")
      skip=0
      for ex in "${exclude[@]:-}"; do [ "$name" = "$ex" ] && skip=1; done
      [ "$skip" = 1 ] && continue
      [ -e "$from$name" ] || rm -rf "$entry"
    done < <(find "$to" -mindepth 1 -maxdepth 1 -print0)
  fi
}
copy_tree "${src%/}/" "$dst" "$delete"
"""


class DeploySandbox:
    """Мини-копия прода: /srv/bulboz/app + отдельный «репозиторий» с новым кодом."""

    def __init__(self, tmp_path: Path, *, pip_fails: bool = True) -> None:
        self.root = tmp_path
        self.home = tmp_path / "srv"
        self.app = self.home / "app"
        self.repo = tmp_path / "repo"
        self.logs = self.home / "logs"
        self.systemd = tmp_path / "systemd"
        self.bin = tmp_path / "bin"
        self.marker = tmp_path / "calls.log"
        self.pip_should_fail = pip_fails

        for d in (self.app / ".venv" / "bin", self.app / "var" / "uploads",
                  self.app / "app" / "static", self.repo / "app" / "static",
                  self.repo / "var" / "uploads", self.logs, self.systemd, self.bin):
            d.mkdir(parents=True, exist_ok=True)

        # То, что обновление не должно трогать: production .env, текущий код, загрузки.
        self.env_file = self.app / ".env"
        self.env_file.write_text(
            "SECRET_KEY=prod-secret\n"
            "DATABASE_URL=postgresql+asyncpg://bulboz:pw@localhost:5432/bulboz\n"
        )
        self.env_file.chmod(0o600)
        (self.app / "CURRENT.txt").write_text("old-version\n")
        (self.app / "var" / "uploads" / "user.png").write_bytes(b"png-bytes")
        # «Репозиторий» с новой версией кода.
        (self.repo / "NEW.txt").write_text("new-version\n")
        (self.repo / "app" / "static" / "site.css").write_text("body{}\n")

        self._tool(self.app / ".venv" / "bin" / "python", "#!/bin/sh\nexit 0\n")
        self._tool(self.bin / "rsync", RSYNC_SHIM)
        self.write_fake_pip()
        self._tool(self.app / ".venv" / "bin" / "alembic",
                   '#!/bin/sh\necho "alembic $*" >> "$CALLS_MARKER"\nexit 0\n')
        self._tool(self.app / ".venv" / "bin" / "flask",
                   '#!/bin/sh\necho "flask $*" >> "$CALLS_MARKER"\nexit 0\n')
        self._tool(self.bin / "systemctl", """#!/bin/sh
echo "systemctl $*" >> "$CALLS_MARKER"
case "$*" in *is-active*) exit 1 ;; esac
exit 0
""")
        self.pip_error_file = self.root / "pip-error.txt"
        self.pip_error_file.write_text(RESOLVER_ERROR)

    # ---- helpers -------------------------------------------------------
    def _tool(self, path: Path, body: str) -> None:
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def write_fake_pip(self) -> None:
        self._tool(self.app / ".venv" / "bin" / "pip", """#!/bin/sh
echo "pip $*" >> "$CALLS_MARKER"
case "$*" in
  *"install -e"*)
    if [ "$PIP_SHOULD_FAIL" = "1" ]; then
      cat "$PIP_ERROR_FILE" >&2
      exit 1
    fi
    ;;
esac
exit 0
""")

    def run(self, body: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        prelude = f'''
set -euo pipefail
export BULBOZ_DEPLOY_SOURCE_ONLY=1
source "{SCRIPT}"
APP_USER="$(id -un)"
APP_HOME="{self.home}"
APP_DIR="{self.app}"
STAGE_DIR="{self.home}/stage"
ROLLBACK_DIR="{self.home}/rollback"
LOG_DIR="{self.logs}"
SYSTEMD_DIR="{self.systemd}"
SRC_DIR="{self.repo}"
NOTIFY_SERVICE=bulboz-notifications.service
NOTIFY_TIMER=bulboz-notifications.timer
export CALLS_MARKER="{self.marker}"
as_user() {{ "$@"; }}
as_user_env() {{ shift; env "$@"; }}
as_app_in() {{ local d="$1"; shift; ( cd "$d" && eval "$*" ); }}
systemd_available() {{ return 0; }}
restart_service() {{ echo "restart bulboz" >> "$CALLS_MARKER"; return 0; }}
wait_up() {{ return 0; }}
check_static() {{ return 0; }}
export PIP_SHOULD_FAIL="${{PIP_SHOULD_FAIL:-{1 if self.pip_should_fail else 0}}}"
export PIP_ERROR_FILE="{self.pip_error_file}"
'''
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        env.update(extra_env or {})
        return subprocess.run(["bash", "-c", prelude + "\n" + body], capture_output=True,
                              text=True, env=env, timeout=180)

    def calls(self) -> str:
        return self.marker.read_text() if self.marker.exists() else ""


@pytest.fixture()
def sandbox(tmp_path):
    return DeploySandbox(tmp_path)


@pytest.fixture()
def ok_sandbox(tmp_path):
    return DeploySandbox(tmp_path, pip_fails=False)


# ---------------------------------------------------------------------------
# 1. Ошибка pip: не мигрируем, не перезапускаем, печатаем полный блок ошибки
# ---------------------------------------------------------------------------
def test_pip_failure_stops_before_migrations_and_keeps_production(sandbox):
    r = sandbox.run('rc=0; update_app || rc=$?; echo "RC=$rc"')
    out = r.stdout + r.stderr

    assert "RC=1" in r.stdout, out
    assert "ЭТАП «ЗАВИСИМОСТИ» ПРОВАЛЕН" in out
    assert "pip вернул код 1" in out
    # полный resolver-блок, а не «-q» и молчание
    assert "The conflict is caused by:" in out
    assert "http-ece" in out
    assert "ResolutionImpossible" in out
    assert "no matching distributions available" in out
    assert "разрешить sdist" in out, "должна быть конкретная инструкция, как починить индекс/политику pip"
    # миграции и перезапуск не запускались
    calls = sandbox.calls()
    assert "alembic" not in calls
    assert "flask" not in calls
    assert "restart bulboz" not in calls
    # рабочая версия, .env и загрузки не изменены
    assert (sandbox.app / "CURRENT.txt").read_text() == "old-version\n"
    assert "SECRET_KEY=prod-secret" in sandbox.env_file.read_text()
    assert not (sandbox.app / "NEW.txt").exists()
    assert not (sandbox.home / "stage").exists()
    # полный лог pip сохранён
    logs = list(sandbox.logs.glob("pip-*.log"))
    assert logs and "http-ece" in logs[0].read_text()


def test_pip_failure_reports_stage_and_log_path(sandbox):
    r = sandbox.run("update_app || true; echo done")
    out = r.stdout + r.stderr
    assert "ЭТАП «ЗАВИСИМОСТИ» ПРОВАЛЕН" in out
    assert f"Полный лог pip: {sandbox.logs}" in out
    assert "Миграции и перезапуск сервиса НЕ выполнялись" in out
    assert "Рабочая версия в" in out and "не изменена" in out
    # диагностика окружения pip тоже печатается
    assert "pip config list" in out
    assert "политика wheel/sdist" in out


def test_pip_error_masks_secrets_in_diagnostics(sandbox):
    r = sandbox.run(
        'export PIP_INDEX_URL="https://ci:SUPERSECRET@nexus.local/simple"; '
        'report_pip_failure 1 "$PIP_ERROR_FILE" "$APP_DIR/.venv"'
    )
    out = r.stdout + r.stderr
    assert "SUPERSECRET" not in out, "токен из PIP_INDEX_URL не должен попадать в вывод"
    assert "https://ci:***@nexus.local/simple" in out
    assert "ResolutionImpossible" in out


# ---------------------------------------------------------------------------
# 2. Успешное обновление: код подменяется, .env и uploads на месте, есть точка отката
# ---------------------------------------------------------------------------
def test_successful_update_swaps_code_and_keeps_env_and_uploads(ok_sandbox):
    r = ok_sandbox.run('rc=0; update_app || rc=$?; echo "RC=$rc"')
    out = r.stdout + r.stderr

    assert "RC=0" in r.stdout, out
    assert (ok_sandbox.app / "NEW.txt").read_text() == "new-version\n"
    assert not (ok_sandbox.app / "CURRENT.txt").exists()
    assert ok_sandbox.env_file.read_text().startswith("SECRET_KEY=prod-secret")
    assert (ok_sandbox.app / "var" / "uploads" / "user.png").read_bytes() == b"png-bytes"
    # миграции и проверки выполнялись на промежуточной копии, затем перезапуск
    calls = ok_sandbox.calls()
    assert "alembic upgrade head" in calls
    assert "flask --app app seed" in calls
    assert "flask --app app doctor" in calls
    assert "restart bulboz" in calls
    # точка отката с прежним кодом и venv
    assert (ok_sandbox.home / "rollback" / "app" / "CURRENT.txt").exists()
    assert (ok_sandbox.home / "rollback" / "venv" / "bin" / "pip").exists()
    assert not (ok_sandbox.home / "stage").exists()
    assert "Обновлено: сайт отвечает" in out
    # в .env дописаны только отсутствующие VAPID-строки, ключи не сгенерированы
    env = ok_sandbox.env_file.read_text()
    assert env.count("VAPID_PUBLIC_KEY=") == 1
    assert env.count("VAPID_PRIVATE_KEY=") == 1


def test_update_is_idempotent(ok_sandbox):
    r = ok_sandbox.run('rc=0; update_app >/dev/null 2>&1 || rc=$?; update_app || rc=$?; echo "RC=$rc"')
    assert "RC=0" in r.stdout, r.stdout + r.stderr
    assert (ok_sandbox.app / "NEW.txt").read_text() == "new-version\n"
    assert ok_sandbox.env_file.read_text().count("VAPID_PUBLIC_KEY=") == 1
    assert ok_sandbox.calls().count("systemctl enable --now bulboz-notifications.timer") == 2


# ---------------------------------------------------------------------------
# 3. Сайт не поднялся после подмены → откат кода и venv
# ---------------------------------------------------------------------------
def test_rollback_when_service_does_not_come_up(ok_sandbox):
    r = ok_sandbox.run('wait_up() { return 1; }\nrc=0; update_app || rc=$?; echo "RC=$rc"')
    out = r.stdout + r.stderr

    assert "RC=1" in r.stdout, out
    assert "откатываюсь" in out
    assert "вернул прежний код и venv" in out
    assert (ok_sandbox.app / "CURRENT.txt").read_text() == "old-version\n"
    assert not (ok_sandbox.app / "NEW.txt").exists()
    assert (ok_sandbox.app / ".venv" / "bin" / "pip").exists()
    assert (ok_sandbox.env_file.read_text().startswith("SECRET_KEY=prod-secret"))
    assert list(ok_sandbox.home.glob("venv-failed-*")), "неудачный venv должен сохраниться для разбора"


def test_code_and_venv_untouched_when_migrations_fail(ok_sandbox):
    r = ok_sandbox.run(
        'as_app_in() { local d="$1"; shift; case "$*" in *"alembic upgrade head"*) return 1 ;; esac; '
        '( cd "$d" && eval "$*" ); }\nrc=0; update_app || rc=$?; echo "RC=$rc"'
    )
    out = r.stdout + r.stderr
    assert "RC=1" in r.stdout, out
    assert "ЭТАП «МИГРАЦИИ/ПРОВЕРКИ» ПРОВАЛЕН" in out
    assert "Рабочая версия не изменена" in out
    # подмена кода и перезапуск не выполнялись
    assert (ok_sandbox.app / "CURRENT.txt").read_text() == "old-version\n"
    assert not (ok_sandbox.app / "NEW.txt").exists()
    assert "restart bulboz" not in ok_sandbox.calls()


# ---------------------------------------------------------------------------
# 4. .env и VAPID
# ---------------------------------------------------------------------------
def test_ensure_vapid_env_adds_all_missing_keys(sandbox):
    r = sandbox.run('ensure_vapid_env "owner@bulboz.example"; echo "RC=$?"')
    assert "RC=0" in r.stdout
    env = sandbox.env_file.read_text()
    assert env.count("VAPID_PUBLIC_KEY=") == 1
    assert env.count("VAPID_PRIVATE_KEY=") == 1
    assert env.count("VAPID_SUBJECT=") == 1
    assert "VAPID_SUBJECT=mailto:owner@bulboz.example" in env
    assert "SECRET_KEY=prod-secret" in env
    assert stat.S_IMODE(sandbox.env_file.stat().st_mode) == 0o600
    assert "generate-vapid" in env, "в .env должна остаться инструкция, как включить push"
    assert list(sandbox.app.glob(".env.bak-vapid-*")), "перед правкой .env делается бэкап"


def test_ensure_vapid_env_inserts_domain_subject_when_no_email(sandbox):
    sandbox.run('ensure_vapid_env "schematoz-bulboz.org"')
    assert "VAPID_SUBJECT=mailto:admin@schematoz-bulboz.org" in sandbox.env_file.read_text()


def test_ensure_vapid_env_never_overwrites_existing_keys(sandbox):
    sandbox.env_file.write_text(
        "SECRET_KEY=prod-secret\n"
        "VAPID_PUBLIC_KEY=PUBLIC-REAL\n"
        "VAPID_PRIVATE_KEY=base64:PRIVATE-REAL\n"
        "VAPID_SUBJECT=mailto:me@my-domain.example\n"
    )
    r = sandbox.run('ensure_vapid_env "other@example.com"; ensure_vapid_env "other@example.com"')
    env = sandbox.env_file.read_text()
    assert env.count("VAPID_PUBLIC_KEY=") == 1
    assert "VAPID_PUBLIC_KEY=PUBLIC-REAL" in env
    assert "VAPID_PRIVATE_KEY=base64:PRIVATE-REAL" in env
    assert "VAPID_SUBJECT=mailto:me@my-domain.example" in env
    assert "other@example.com" not in env
    # приватный ключ не должен попадать в вывод скрипта
    assert "PRIVATE-REAL" not in r.stdout + r.stderr


def test_web_push_status_warns_and_gives_exact_command(sandbox):
    r = sandbox.run("warn_web_push_if_unconfigured; web_push_status")
    out = r.stdout + r.stderr
    assert "Web Push НЕ настроен" in out
    assert "внутренние уведомления" in out  # сайт и /notifications продолжают работать
    assert "generate-vapid" in out
    assert str(sandbox.env_file) in out
    assert "VAPID_PUBLIC_KEY" in out and "VAPID_PRIVATE_KEY" in out and "VAPID_SUBJECT" in out
    assert "systemctl restart bulboz" in out
    assert "run-notification-jobs" in out, "должна быть инструкция про планировщик каждые 5 минут"


def test_web_push_status_does_not_print_private_key(sandbox):
    sandbox.env_file.write_text(
        "SECRET_KEY=prod-secret\n"
        "VAPID_PUBLIC_KEY=PUBLIC-REAL\n"
        "VAPID_PRIVATE_KEY=base64:PRIVATE-REAL\n"
        "VAPID_SUBJECT=mailto:me@my-domain.example\n"
    )
    r = sandbox.run("warn_web_push_if_unconfigured; web_push_status")
    out = r.stdout + r.stderr
    assert "PRIVATE-REAL" not in out
    assert "Web Push: ключи в .env есть" in out
    assert "VAPID_SUBJECT: mailto:me@my-domain.example" in out


def test_web_push_status_warns_about_placeholder_subject(sandbox):
    sandbox.env_file.write_text(
        "SECRET_KEY=prod-secret\n"
        "VAPID_PUBLIC_KEY=PUBLIC-REAL\n"
        "VAPID_PRIVATE_KEY=base64:PRIVATE-REAL\n"
        "VAPID_SUBJECT=mailto:admin@example.com\n"
    )
    r = sandbox.run("web_push_status")
    assert "нужен реальный адрес владельца" in r.stdout + r.stderr


def test_vapid_subject_helpers():
    out = subprocess.run(
        ["bash", "-c", f'''
set -euo pipefail
export BULBOZ_DEPLOY_SOURCE_ONLY=1
source "{SCRIPT}"
echo "A=$(vapid_subject_for "me@my-domain.example")"
echo "B=$(vapid_subject_for "schematoz-bulboz.org")"
echo "C=$(vapid_subject_for "")"
for s in "" "mailto:admin@example.com" "mailto:CHANGE-ME@example.com" "mailto:me@my-domain.example"; do
  if vapid_subject_is_placeholder "$s"; then echo "placeholder:$s"; else echo "real:$s"; fi
done
'''],
        capture_output=True, text=True, timeout=60)
    o = out.stdout
    assert "A=mailto:me@my-domain.example" in o
    assert "B=mailto:admin@schematoz-bulboz.org" in o
    assert "C=mailto:CHANGE-ME@example.com" in o
    assert "placeholder:mailto:admin@example.com" in o
    assert "placeholder:mailto:CHANGE-ME@example.com" in o
    assert "real:mailto:me@my-domain.example" in o


# ---------------------------------------------------------------------------
# 5. Планировщик run-notification-jobs
# ---------------------------------------------------------------------------
def test_notification_timer_is_installed_idempotently(sandbox):
    r = sandbox.run("install_notification_timer; install_notification_timer; echo done")
    out = r.stdout + r.stderr
    service = sandbox.systemd / "bulboz-notifications.service"
    timer = sandbox.systemd / "bulboz-notifications.timer"
    assert service.exists() and timer.exists()
    body = service.read_text()
    assert f"User={pwd.getpwuid(os.getuid()).pw_name}" in body
    assert "WorkingDirectory=" in body
    assert "EnvironmentFile=" in body
    assert "run-notification-jobs" in body
    assert "OnUnitActiveSec=5min" in timer.read_text()
    assert "Persistent=true" in timer.read_text()
    assert sandbox.calls().count("systemctl enable --now bulboz-notifications.timer") == 2
    assert "Планировщик: bulboz-notifications.timer включён" in out


def test_notification_timer_without_systemd_falls_back_to_cron_hint(sandbox):
    r = sandbox.run("systemd_available() { return 1; }\ninstall_notification_timer")
    out = r.stdout + r.stderr
    assert not (sandbox.systemd / "bulboz-notifications.service").exists()
    assert "/etc/cron.d/bulboz-notifications" in out
    assert "*/5 * * * *" in out


def test_cron_hint_uses_app_dir(sandbox):
    r = sandbox.run("notification_cron_hint")
    out = r.stdout + r.stderr
    assert f"cd {sandbox.app}" in out
    assert "run-notification-jobs" in out
    assert "/etc/cron.d/bulboz-notifications" in out


# ---------------------------------------------------------------------------
# 6. Статические требования к скрипту
# ---------------------------------------------------------------------------
def test_script_syntax_and_no_quiet_pip_or_legacy_resolver():
    text = SCRIPT.read_text()
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
    assert "install -q" not in text, "pip не должен прятать вывод через -q"
    assert "legacy-resolver" not in text, "resolver обходить нельзя"
    assert "--only-binary=:all:" not in text, "нельзя запрещать sdist вместо разбора причины"
    assert "pip вернул код" in text, "ошибка pip должна печатать код возврата"
    assert "PIP_ONLY_BINARY" in text, "подсказка про запрет sdist должна быть в диагностике"
    assert "Полный лог pip:" in text


def test_update_flow_stages_before_touching_production():
    text = SCRIPT.read_text()
    assert 'install_deps "$STAGE_DIR" "$STAGE_DIR/.venv"' in text
    assert "rsync -a --delete --exclude .venv --exclude .env --exclude var" in text
    assert "rollback_app" in text
    # миграции идут после pip и до подмены кода
    assert text.index('run_migrations_and_checks "$STAGE_DIR"') < text.index('Точка отката и подмена кода')


def test_env_is_never_overwritten_by_deploy():
    text = SCRIPT.read_text()
    # .env исключён из rsync, var/uploads не участвуют в подмене
    assert "--exclude .env" in text and "--exclude var" in text
    assert "VAPID_SUBJECT=mailto:$EMAIL" in text, "полная установка пишет реальный контакт владельца"
    assert "openssl rand" not in text[text.index("ensure_vapid_env"):text.index("warn_web_push_if_unconfigured")], \
        "deploy никогда сам не генерирует VAPID-пару"
