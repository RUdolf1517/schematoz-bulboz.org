"""Тонкий адаптер над kremle-detect (KremleFlask).

* KremleFlask сам детектит «специфичный» трафик (auto_guard) и отдаёт капчу
  из заданий ЕГЭ на /kremle/challenge, проверку — на /kremle/verify.
* Мы добавляем декоратор `captcha_required`: для регистрации/входа капча нужна
  всегда, для остальных действий — если антиспам пометил пользователя/IP как
  подозрительного. Пройденная капча «тратится» на одно защищённое действие.
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
    kremle.init_app(app)


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
    """always=True — капча перед каждым действием (регистрация, вход).
    always=False — только если антиспам считает клиента подозрительным."""
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
