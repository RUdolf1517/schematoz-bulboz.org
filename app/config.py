"""Конфигурация. Всё, что зависит от окружения, берётся из переменных среды."""
from __future__ import annotations

import os


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
    SESSION_TTL_SECONDS = 30 * 24 * 3600

    # kremle-detect
    KREMLE_AUTO_GUARD = _bool("KREMLE_AUTO_GUARD", True)  # детект спец. трафика на всех роутах
    KREMLE_CATEGORIES = ["math", "physics", "russian", "literature"]
    KREMLE_QUESTION_COUNT = int(os.environ.get("KREMLE_QUESTION_COUNT", "5"))
    KREMLE_MAX_ERRORS = int(os.environ.get("KREMLE_MAX_ERRORS", "1"))

    # Репутация
    VOTE_CHANGE_COOLDOWN_SECONDS = 600       # менять голос не чаще раза в 10 минут
    NEW_ACCOUNT_VOTE_HOLD_HOURS = 24         # голоса «свежих» аккаунтов пишутся с delta=0

    # Антиспам (правила, без ML)
    ANTISPAM_POSTS_PER_MINUTE = 5

    # Фича-флаги типов ответа (значения по умолчанию; админ переопределяет в settings)
    FEATURES = {
        "ANSWER_TEXT_ENABLED": True,
        "ANSWER_VOICE_ENABLED": False,
        "ANSWER_VIDEO_ENABLED": False,
    }
    ANSWER_TEXT_MAX_LEN = 5000
    ANSWER_MEDIA_MAX_DURATION_MS = 60_000
