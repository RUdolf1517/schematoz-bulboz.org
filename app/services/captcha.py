"""Тонкий адаптер над kremle-detect (KremleFlask).

* KremleFlask сам детектит «специфичный» трафик (auto_guard) и отдаёт капчу
  из заданий ЕГЭ на /kremle/challenge, проверку — на /kremle/verify.
* Мы добавляем декоратор `captcha_required`: капча нужна, если антиспам пометил
  пользователя/IP как подозрительного (подбор пароля, частые посты, дубли, ссылки
  с нового аккаунта). На входе/регистрации обязательной капчи нет (решение продукта).
  Пройденная капча «тратится» на одно защищённое действие.
"""
from __future__ import annotations

from functools import wraps

from flask import current_app, request, session, url_for
from kremle_detect.integrations.flask_ext import NEXT_KEY, SESSION_KEY, KremleFlask
from kremle_detect.storage import RedisStorage

from ..errors import ApiError
from ..extensions import get_redis
from . import antispam

kremle = KremleFlask(auto_guard=False)


def init_captcha(app) -> None:
    kremle.categories = app.config["KREMLE_CATEGORIES"]
    kremle.question_count = app.config["KREMLE_QUESTION_COUNT"]
    kremle.max_errors = app.config["KREMLE_MAX_ERRORS"]
    kremle.auto_guard = app.config["KREMLE_AUTO_GUARD"]
    kremle.skip_endpoints = {"legal.page", "health"}
    kremle._storage = RedisStorage(redis_client=app.extensions["redis"])
    # свой шаблон (на основе библиотечного) — ради обязательного футера на всех страницах
    import os
    kremle.custom_template = os.path.join(app.root_path, "templates", "kremle_captcha.html")
    kremle.init_app(app)

    @app.before_request
    async def _apply_captcha_settings():
        from flask import request as rq
        if rq.endpoint in ("kremle.challenge", "kremle.verify"):
            await apply_admin_settings()


CAPTCHA_CATEGORIES = ("math", "physics", "russian", "literature")
CACHE_KEY = "settings:captcha"


def validate_captcha_settings(value: dict) -> dict:
    """Настройки капчи из админки: предметы, число вопросов, допустимые ошибки."""
    cats = value.get("categories", list(CAPTCHA_CATEGORIES))
    if not isinstance(cats, list) or not cats or not set(cats) <= set(CAPTCHA_CATEGORIES):
        raise ApiError(f"categories — непустой список из {', '.join(CAPTCHA_CATEGORIES)}",
                       400, "validation_error")
    count = value.get("question_count", 5)
    errors = value.get("max_errors", 1)
    if not isinstance(count, int) or not 1 <= count <= 15:
        raise ApiError("question_count: 1..15", 400, "validation_error")
    if not isinstance(errors, int) or not 0 <= errors < count:
        raise ApiError("max_errors: 0..question_count-1", 400, "validation_error")
    return {"categories": cats, "question_count": count, "max_errors": errors}


async def apply_admin_settings() -> None:
    import json
    from sqlalchemy import select
    from ..db import session_scope
    from ..models import Setting
    r = get_redis()
    raw = r.get(CACHE_KEY)
    if raw is None:
        async with session_scope() as s:
            row = await s.scalar(select(Setting).where(Setting.key == "captcha"))
        raw = json.dumps(row.value if row else {})
        r.setex(CACHE_KEY, 60, raw)
    conf = json.loads(raw)
    engine = kremle.engine
    cfg = current_app.config
    engine.categories = conf.get("categories", cfg["KREMLE_CATEGORIES"])
    engine.question_count = conf.get("question_count", cfg["KREMLE_QUESTION_COUNT"])
    engine.max_errors = conf.get("max_errors", cfg["KREMLE_MAX_ERRORS"])


def invalidate_captcha_settings() -> None:
    get_redis().delete(CACHE_KEY)


def captcha_passed() -> bool:
    return bool(session.get(SESSION_KEY))


def consume_captcha() -> None:
    session.pop(SESSION_KEY, None)


def _challenge() -> ApiError:
    session[NEXT_KEY] = request.referrer or "/"
    return ApiError(
        "Реши задачку из ЕГЭ, чтобы продолжить", 403, "captcha_required",
        challenge_url=url_for("kremle.challenge"),
    )


def captcha_required(always: bool = False):
    """always=False (по умолчанию) — капча, только если антиспам считает клиента подозрительным.
    always=True — капча перед каждым действием (сейчас нигде не используется)."""
    def deco(view):
        @wraps(view)
        async def wrapper(*args, **kwargs):
            if current_app.config.get("CAPTCHA_DISABLED"):
                return await view(*args, **kwargs)
            need = always or antispam.is_suspicious(antispam.client_key())
            if need:
                if not captcha_passed():
                    raise _challenge()
                consume_captcha()
                antispam.clear_suspicion(antispam.client_key())
            return await view(*args, **kwargs)
        return wrapper
    return deco
