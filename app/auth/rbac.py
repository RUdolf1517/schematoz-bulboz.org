"""RBAC на уровне API. Декораторы асинхронные: пользователь, права и баны
загружаются в той же корутине (и том же event loop), что и сама вьюха."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g
from sqlalchemy import or_, select

from ..db import session_scope
from ..errors import ApiError
from ..extensions import get_redis
from ..models import Ban, BanScope, Permission, User, UserRole, role_permissions
from .sessions import current_user_id

PERM_CACHE_TTL = 300


def _perm_key(uid: int) -> str:
    return f"perm:{uid}"


def invalidate_perms(user_id: int) -> None:
    get_redis().delete(_perm_key(user_id))


async def get_user_perms(user_id: int) -> set[str]:
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


def login_required(view):
    @wraps(view)
    async def wrapper(*args, **kwargs):
        await _load_user()
        return await view(*args, **kwargs)
    return wrapper


def _require_permissions(perms: set[str], *, any_of: bool):
    def deco(view):
        @wraps(view)
        async def wrapper(*args, **kwargs):
            user = await _load_user()
            ban = await active_global_ban(user.id)
            if ban is not None:
                raise ApiError(
                    "Аккаунт заблокирован", 403, "banned",
                    ban_id=ban.id, until=ban.ends_at.isoformat() if ban.ends_at else None,
                    reason=ban.reason,
                )
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
