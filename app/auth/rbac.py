"""RBAC на уровне API. Декораторы асинхронные: пользователь, права и баны
загружаются в той же корутине (и том же event loop), что и сама вьюха."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g
from sqlalchemy import or_, select

from ..db import session_scope
from ..errors import ApiError
from ..extensions import get_redis
from ..models import Ban, BanScope, Permission, User, UserRole, role_permissions
from ..permissions import ALL_PERMS
from .sessions import current_user_id

PERM_CACHE_TTL = 300

log = logging.getLogger(__name__)

# Версия каталога прав в ключе кэша: после деплоя с новыми правами
# старые записи Redis перестают использоваться и права перечитываются из БД — иначе админ
# до истечения TTL остаётся без новых прав.
CATALOG_VERSION = hashlib.sha1("|".join(sorted(ALL_PERMS)).encode()).hexdigest()[:10]
_catalog_synced = False


def _perm_key(uid: int) -> str:
    return f"perm:{uid}:{CATALOG_VERSION}"


def reset_catalog_cache() -> None:
    """Заставит пере-синхронизировать каталог прав при следующей проверке (тесты, деплой)."""
    global _catalog_synced
    _catalog_synced = False


async def _ensure_catalog() -> None:
    """Раз на процесс досыпает недостающие права/роли из кода (`seed_permissions`).

    Так новые права появляются у админов сразу после деплоя, даже если `flask seed`
    пропустили. Ошибки (БД ещё мигрируется) не валят запрос — попробуем в следующий раз.
    """
    global _catalog_synced
    if _catalog_synced:
        return
    from ..seed import seed_permissions
    try:
        async with session_scope() as s:
            await seed_permissions(s)
    except Exception as exc:  # noqa: BLE001 — каталог досыпем при следующем запросе
        log.warning("Каталог прав не синхронизирован: %s", exc)
        return
    _catalog_synced = True


def invalidate_perms(user_id: int) -> None:
    # чистим и старый (безверсионный) ключ — он мог остаться от прежнего кода
    get_redis().delete(_perm_key(user_id), f"perm:{user_id}")


async def get_user_perms(user_id: int) -> set[str]:
    await _ensure_catalog()
    r = get_redis()
    cached = r.smembers(_perm_key(user_id))
    if cached:
        return set(cached)
    async with session_scope() as s:
        rows = await s.scalars(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == role_permissions.c.role_id)
            .where(UserRole.user_id == user_id)
        )
        perms = set(rows)
    if perms:
        r.sadd(_perm_key(user_id), *perms)
        r.expire(_perm_key(user_id), PERM_CACHE_TTL)
    return perms


async def active_global_ban(user_id: int) -> Ban | None:
    now = datetime.now(timezone.utc)
    async with session_scope() as s:
        return await s.scalar(
            select(Ban).where(
                Ban.user_id == user_id,
                Ban.scope == BanScope.GLOBAL,
                Ban.lifted_at.is_(None),
                Ban.starts_at <= now,
                or_(Ban.ends_at.is_(None), Ban.ends_at > now),
            ).order_by(Ban.ends_at.desc().nulls_first()).limit(1)
        )


async def _load_user() -> User:
    uid = current_user_id()
    if uid is None:
        raise ApiError("Нужно войти", 401, "unauthorized")
    async with session_scope() as s:
        user = await s.get(User, uid)
        now = datetime.now(timezone.utc)
        # Track real account activity without writing on every tiny API call.
        if user and (user.last_seen_at is None or user.last_seen_at < now - timedelta(minutes=5)):
            user.last_seen_at = now
    if user is None:
        raise ApiError("Нужно войти", 401, "unauthorized")
    g.user = user
    return user


def _ban_error(ban: Ban) -> ApiError:
    return ApiError(
        "Аккаунт заблокирован", 403, "banned",
        ban_id=ban.id, until=ban.ends_at.isoformat() if ban.ends_at else None,
        reason=ban.reason,
    )


async def _ensure_not_banned(user_id: int) -> None:
    ban = await active_global_ban(user_id)
    if ban is not None:
        raise _ban_error(ban)


def login_required(view=None, *, allow_banned: bool = False):
    """Требует входа и по умолчанию запрещает любые действия при активном глобальном бане.

    ``allow_banned`` предназначен только для страницы статуса, /me и подачи апелляции.
    """
    def decorate(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            user = await _load_user()
            if not allow_banned:
                await _ensure_not_banned(user.id)
            return await fn(*args, **kwargs)
        return wrapper

    return decorate(view) if view is not None else decorate


def _require_permissions(perms: set[str], *, any_of: bool):
    def deco(view):
        @wraps(view)
        async def wrapper(*args, **kwargs):
            user = await _load_user()
            await _ensure_not_banned(user.id)
            granted = await get_user_perms(user.id)
            allowed = bool(perms & granted) if any_of else perms <= granted
            if not allowed:
                raise ApiError("Недостаточно прав", 403, "forbidden")
            g.perms = granted
            return await view(*args, **kwargs)
        return wrapper
    return deco


def require_perm(*perms: str):
    """Пропускает, только если у пользователя есть ВСЕ перечисленные права и нет активного бана."""
    return _require_permissions(set(perms), any_of=False)


def require_any_perm(*perms: str):
    """Пропускает, если есть хотя бы одно из прав (и нет активного бана)."""
    if not perms:
        raise ValueError("require_any_perm requires at least one permission")
    return _require_permissions(set(perms), any_of=True)
