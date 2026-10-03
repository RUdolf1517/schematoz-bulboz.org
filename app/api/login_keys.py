"""Файл входа: пользователь скачивает файл с ключом и входит им без логина и пароля.

Ключ — 256 бит случайности, в БД только sha256 (как у API-токенов). Файл = пароль:
кто получил файл, тот вошёл, поэтому ключи можно отозвать, а вход по ключу защищён
тем же антибрутфорсом, что и пароль (после 5 промахов — капча).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from flask import g
from sqlalchemy import func, select, update

from ..auth.rbac import active_global_ban, login_required
from ..auth.sessions import login_user
from ..db import session_scope
from ..errors import ApiError
from ..models import LoginKey, User
from ..services import antispam
from ..services.captcha import captcha_required
from . import bp
from .utils import json_body, user_public

KEY_PREFIX = "sbk_"
FILE_TYPE = "schematoz-bulboz-login-key"
MAX_ACTIVE_KEYS = 5


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_out(k: LoginKey) -> dict:
    return {"id": k.id, "label": k.label, "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}


@bp.get("/auth/login-keys")
@login_required
async def list_login_keys():
    async with session_scope() as s:
        rows = (await s.scalars(select(LoginKey).where(LoginKey.user_id == g.user.id, LoginKey.revoked_at.is_(None))
                                .order_by(LoginKey.id.desc()))).all()
    return {"items": [key_out(k) for k in rows], "max": MAX_ACTIVE_KEYS}


@bp.post("/auth/login-keys")
@login_required
async def create_login_key():
    label = (json_body().get("label") or "").strip()[:64] or "Файл входа"
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    async with session_scope() as s:
        active = await s.scalar(select(func.count()).select_from(LoginKey)
                                .where(LoginKey.user_id == g.user.id, LoginKey.revoked_at.is_(None)))
        if active >= MAX_ACTIVE_KEYS:
            raise ApiError(f"Не больше {MAX_ACTIVE_KEYS} файлов входа — отзови ненужный", 409, "too_many_keys")
        k = LoginKey(user_id=g.user.id, key_hash=_hash(key), label=label)
        s.add(k)
        await s.flush()
        await s.refresh(k)
        out = key_out(k)
    # Ключ показываем один раз — повторно его не получить.
    return {"key": out, "file": {"type": FILE_TYPE, "version": 1, "username": g.user.username,
                                 "key": key, "created_at": out["created_at"]},
            "filename": f"bulboz-{g.user.username}.key"}, 201


@bp.delete("/auth/login-keys/<int:key_id>")
@login_required
async def revoke_login_key(key_id: int):
    async with session_scope() as s:
        res = await s.execute(update(LoginKey).where(LoginKey.id == key_id, LoginKey.user_id == g.user.id,
                                                     LoginKey.revoked_at.is_(None))
                              .values(revoked_at=datetime.now(timezone.utc)))
        if not res.rowcount:
            raise ApiError("Ключ не найден", 404, "not_found")
    return {"revoked": True}


@bp.post("/auth/login-file")
@captcha_required()  # после 5 промахов за 15 минут — капча, как у пароля
async def login_by_file():
    data = json_body()
    key = data.get("key")
    if isinstance(data.get("file"), dict):           # можно прислать содержимое файла целиком
        key = data["file"].get("key")
    if not isinstance(key, str) or not key.startswith(KEY_PREFIX) or len(key) > 128:
        raise ApiError("Это не файл входа schematoz-bulboz", 400, "invalid_key_file")
    async with session_scope() as s:
        row = (await s.execute(select(LoginKey, User).join(User, User.id == LoginKey.user_id)
                               .where(LoginKey.key_hash == _hash(key), LoginKey.revoked_at.is_(None)))).first()
        if row is not None:
            row[0].last_used_at = datetime.now(timezone.utc)
    if row is None:
        if antispam.hit_rate("login_fail", antispam.client_key(), 5, 900):
            antispam.mark_suspicious(antispam.client_key(), "login_bruteforce")
        raise ApiError("Ключ недействителен или отозван", 401, "invalid_key")
    user = row[1]
    ban = await active_global_ban(user.id)
    login_user(user.id)
    return {"user": user_public(user), "banned": ban is not None}
