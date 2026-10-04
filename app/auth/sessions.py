"""Серверные сессии в Redis. В подписанной Flask-cookie лежит только случайный sid,
поэтому сессию можно отозвать (логаут, бан) на стороне сервера."""
from __future__ import annotations

import secrets

from flask import current_app, session

from ..extensions import get_redis

SID_KEY = "sid"


def _key(sid: str) -> str:
    return f"sess:{sid}"


def login_user(user_id: int) -> None:
    sid = secrets.token_urlsafe(32)
    ttl = current_app.config["SESSION_TTL_SECONDS"]
    r = get_redis()
    r.setex(_key(sid), ttl, user_id)
    r.sadd(f"user_sessions:{user_id}", sid)
    session[SID_KEY] = sid
    session.permanent = True


def logout_user() -> None:
    sid = session.pop(SID_KEY, None)
    if sid:
        r = get_redis()
        uid = r.get(_key(sid))
        r.delete(_key(sid))
        if uid:
            r.srem(f"user_sessions:{uid}", sid)


def revoke_all_sessions(user_id: int) -> None:
    r = get_redis()
    sids = r.smembers(f"user_sessions:{user_id}")
    if sids:
        r.delete(*[_key(s) for s in sids])
    r.delete(f"user_sessions:{user_id}")


def current_user_id() -> int | None:
    sid = session.get(SID_KEY)
    if not sid:
        return None
    uid = get_redis().get(_key(sid))
    return int(uid) if uid else None
