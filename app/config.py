"""Конфигурация. Всё, что зависит от окружения, берётся из переменных среды."""
from __future__ import annotations

import os

try:  # .env подхватывается сам — не нужно делать export руками
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("ENV_FILE", ".env"), override=False)
except ImportError:  # python-dotenv — необязательная зависимость
    pass


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://bulboz:bulboz@localhost:5432/bulboz"
    )
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    REDIS_CLIENT = None  # тесты подсовывают сюда fakeredis

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    # Превью/встраивание в iframe на другом домене: cookie должна быть SameSite=None; Secure.
    if _bool("COOKIE_CROSS_SITE", False):
        SESSION_COOKIE_SAMESITE = "None"
        SESSION_COOKIE_SECURE = True
        # Partitioned (CHIPS): иначе Chrome блокирует стороннюю cookie во фрейме — и вход «не работает»
        SESSION_COOKIE_PARTITIONED = True
    # Показывать тестовые аккаунты на странице входа (НИКОГДА не включать в проде)
    DEMO_MODE = _bool("DEMO_MODE", False)
    ANTIBOT_DISABLED = _bool("ANTIBOT_DISABLED", False)  # только для e2e!
    SESSION_TTL_SECONDS = 30 * 24 * 3600

    # kremle-detect
    # цитаты для гриба: внешние API (через запятую). Пусто — только встроенный корпус.
    QUOTES_REMOTE = _bool("QUOTES_REMOTE", True)
    # принимаются только русские цитаты (проверка на кириллицу)
    QUOTES_DUBIOUS_URLS = os.environ.get("QUOTES_DUBIOUS_URLS", "")
    QUOTES_PHILO_URLS = os.environ.get("QUOTES_PHILO_URLS", "")  # обычные афоризмы — не «спорные», по умолчанию выкл.
    KREMLE_AUTO_GUARD = _bool("KREMLE_AUTO_GUARD", True)  # детект спец. трафика на всех роутах
    KREMLE_CATEGORIES = ["math", "physics", "russian", "literature"]
    KREMLE_QUESTION_COUNT = int(os.environ.get("KREMLE_QUESTION_COUNT", "5"))
    KREMLE_MAX_ERRORS = int(os.environ.get("KREMLE_MAX_ERRORS", "1"))

    # Репутация

    # Антиспам (правила, без ML)
    ANTISPAM_POSTS_PER_MINUTE = 5

    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "var", "uploads"))
    MAX_CONTENT_LENGTH = 9 * 1024 * 1024
