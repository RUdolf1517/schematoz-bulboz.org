from __future__ import annotations

import re
from datetime import date

from flask import g, request
from sqlalchemy import func, or_, select

from ..auth.passwords import hash_password, verify_password
from ..auth.rbac import active_global_ban, login_required
from ..auth.sessions import login_user, logout_user
from ..db import session_scope
from ..errors import ApiError
from ..models import LegalPage, Role, User, UserConsent, UserRole
from ..services import antispam
from ..services.captcha import captcha_required
from . import bp
from .utils import json_body, req_str, user_public

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_AGE = 14


@bp.post("/auth/register")
@captcha_required()  # капча только при подозрительной активности
async def register():
    data = json_body()
    username = (req_str(data, "username", min_len=3, max_len=32) or "").lower()
    if not USERNAME_RE.match(username):
        raise ApiError("Ник: латиница, цифры и _, 3–32 символа", 400, "validation_error", field="username")
    email = (req_str(data, "email", max_len=254) or "").lower()
    if not EMAIL_RE.match(email):
        raise ApiError("Некорректный email", 400, "validation_error", field="email")
    password = req_str(data, "password", min_len=8, max_len=128)
    birth_year = data.get("birth_year")
    if not isinstance(birth_year, int) or not 1900 < birth_year <= date.today().year:
        raise ApiError("Укажи год рождения", 400, "validation_error", field="birth_year")
    if date.today().year - birth_year < MIN_AGE:
        raise ApiError("Регистрация доступна с 14 лет", 403, "too_young")
    if data.get("accept_terms") is not True:
        raise ApiError("Нужно принять соглашение и политику", 400, "terms_not_accepted")

    async with session_scope() as s:
        taken = await s.scalar(select(User.id).where(or_(User.username == username, User.email == email)))
        if taken:
            raise ApiError("Ник или email уже заняты", 409, "already_exists")
        user = User(username=username, email=email, password_hash=hash_password(password),
                    display_name=(data.get("display_name") or username)[:64], birth_year=birth_year)
        s.add(user)
        await s.flush()
        role_id = await s.scalar(select(Role.id).where(Role.code == "user"))
        if role_id is None:
            raise ApiError("Роли не инициализированы (flask seed)", 500, "not_seeded")
        s.add(UserRole(user_id=user.id, role_id=role_id))
        pages = await s.execute(select(LegalPage.slug, LegalPage.current_version)
                                .where(LegalPage.requires_consent.is_(True)))
        for slug, ver in pages:
            s.add(UserConsent(user_id=user.id, page_slug=slug, version=ver, ip=request.remote_addr))
    login_user(user.id)
    return {"user": user_public(user)}, 201


@bp.post("/auth/login")
@captcha_required()  # после 5 неудачных входов за 15 минут — капча
async def login():
    data = json_body()
    login_ = (req_str(data, "login", max_len=254) or "").lower()
    password = req_str(data, "password", max_len=128)
    async with session_scope() as s:
        user = await s.scalar(select(User).where(or_(User.username == login_, User.email == login_)))
    if user is None or not verify_password(user.password_hash, password):
        if antispam.hit_rate("login_fail", antispam.client_key(), 5, 900):
            antispam.mark_suspicious(antispam.client_key(), "login_bruteforce")
        raise ApiError("Неверный логин или пароль", 401, "invalid_credentials")
    # Забаненный может войти — чтобы увидеть причину и подать апелляцию.
    # Любые действия всё равно режет @require_perm.
    ban = await active_global_ban(user.id)
    login_user(user.id)
    return {"user": user_public(user), "banned": ban is not None}


@bp.post("/auth/logout")
async def logout():
    logout_user()
    return {"ok": True}


@bp.get("/auth/me")
@login_required
async def me():
    from ..auth.rbac import get_user_perms
    from ..services.notifications import unread_count
    ban = await active_global_ban(g.user.id)
    async with session_scope() as s:
        unread = await unread_count(s, g.user.id)
    return {"user": user_public(g.user), "roles": [r.code for r in g.user.roles],
            "unread_notifications": unread,
            "permissions": sorted(await get_user_perms(g.user.id)),
            "ban": {"id": ban.id, "reason": ban.reason,
                    "ends_at": ban.ends_at.isoformat() if ban.ends_at else None,
                    "appeal_status": ban.appeal_status.value} if ban else None}
