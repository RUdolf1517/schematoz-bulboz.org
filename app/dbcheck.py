"""Понятные подсказки, когда не удаётся подключиться к PostgreSQL / Redis (вместо простыни traceback)."""
from __future__ import annotations

import re

HINT_SETUP = ("Быстрый путь на Mac: ./scripts/setup_local_pg.sh (создаст роль и базу bulboz в твоём Postgres)\n"
              "   или без установки Postgres вообще: ./scripts/reset_dev_db.sh "
              "и DATABASE_URL=$(python scripts/dev_pg.py) — см. README, «Запуск на своём компьютере».")


def mask_url(url: str) -> str:
    return re.sub(r"//([^:/@]+):[^@]*@", r"//\1:***@", url or "")


def _chain(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = getattr(exc, "orig", None) or exc.__cause__ or exc.__context__


def db_problem(exc: BaseException, url: str = "") -> str | None:
    """Если исключение — проблема подключения к БД, вернуть человеческое объяснение. Иначе None."""
    names = " ".join(type(e).__name__ for e in _chain(exc))
    text = " ".join(str(e) for e in _chain(exc))
    where = f"DATABASE_URL = {mask_url(url)}" if url else "DATABASE_URL"
    m = re.search(r'role "([^"]+)" does not exist', text)
    if m:
        return (f"В PostgreSQL нет пользователя (роли) «{m.group(1)}». {where}\n"
                f"   Создай его: createuser -P {m.group(1)}  (или поправь DATABASE_URL в .env)\n   {HINT_SETUP}")
    m = re.search(r'database "([^"]+)" does not exist', text)
    if m:
        return f"В PostgreSQL нет базы «{m.group(1)}». {where}\n   Создай её: createdb {m.group(1)}\n   {HINT_SETUP}"
    if "password authentication failed" in text or "InvalidPassword" in names:
        return f"PostgreSQL не принял пароль. {where}\n   Проверь логин и пароль в DATABASE_URL (.env).\n   {HINT_SETUP}"
    if "ConnectionRefused" in names or "Connect call failed" in text or "Errno 61" in text or "Errno 111" in text:
        tip = ("\n   Порт 6432 — это PgBouncer (прод). Локальный Postgres обычно на 5432: поправь DATABASE_URL в .env"
               if ":6432/" in (url or "") else "")
        return (f"PostgreSQL не отвечает — он не запущен или слушает другой порт. {where}{tip}\n"
                f"   Mac + Homebrew: brew services start postgresql@16\n   {HINT_SETUP}")
    if "nodename nor servname" in text or "Name or service not known" in text or "gaierror" in names:
        return f"Не удаётся найти хост базы данных. {where}\n   {HINT_SETUP}"
    if "InvalidAuthorizationSpecification" in names:
        return f"PostgreSQL отказал в доступе: {text.splitlines()[0]}. {where}\n   {HINT_SETUP}"
    if 'relation "' in text and "does not exist" in text:
        return ("В базе нет таблиц — не применены миграции.\n"
                "   Выполни: alembic upgrade head && flask --app app seed")
    return None


def redis_problem(exc: BaseException, url: str = "") -> str | None:
    if not any(type(e).__module__.startswith("redis") or isinstance(e, ConnectionRefusedError)
               for e in _chain(exc)):
        return None
    if True:
        return (f"Redis не отвечает (REDIS_URL = {mask_url(url)}).\n"
                "   Mac + Homebrew: brew install redis && brew services start redis\n"
                "   Для разработки можно без Redis: REDIS_URL=memory://  (нужен пакет fakeredis)")
    return None
