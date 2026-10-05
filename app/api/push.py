"""PWA/Web Push subscriptions and per-alert controls."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from flask import current_app, g, request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import PushPreference, PushSubscription
from ..services import push as push_service
from . import bp
from .utils import json_body


def _public_endpoint(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ApiError("Некорректный Push endpoint", 400, "validation_error")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ApiError("Push endpoint должен быть HTTPS URL", 400, "validation_error")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ApiError("Локальные Push endpoints не поддерживаются", 400, "validation_error")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ApiError("Приватные Push endpoints не поддерживаются", 400, "validation_error")
    except ValueError:
        pass
    return value


@bp.get("/push/settings")
@login_required
async def push_settings():
    async with session_scope() as s:
        pref = await s.get(PushPreference, g.user.id)
        subscribed = bool(await s.scalar(select(PushSubscription.id).where(
            PushSubscription.user_id == g.user.id).limit(1)))
    return push_service.prefs_out(
        pref, subscribed, current_app.config.get("VAPID_PUBLIC_KEY") or None,
        bool(current_app.config.get("VAPID_PUBLIC_KEY") and current_app.config.get("VAPID_PRIVATE_KEY")),
    )


@bp.put("/push/settings")
@login_required
async def update_push_settings():
    data = json_body()
    async with session_scope() as s:
        pref = await s.get(PushPreference, g.user.id, with_for_update=True)
        try:
            fields = push_service.validate_preferences(data, pref)
        except ValueError as exc:
            raise ApiError(str(exc), 400, "validation_error") from exc
        if pref is None:
            pref = PushPreference(user_id=g.user.id, **fields)
            s.add(pref)
        else:
            for key, value in fields.items():
                setattr(pref, key, value)
        await s.flush()
        subscribed = bool(await s.scalar(select(PushSubscription.id).where(
            PushSubscription.user_id == g.user.id).limit(1)))
    return push_service.prefs_out(
        pref, subscribed, current_app.config.get("VAPID_PUBLIC_KEY") or None,
        bool(current_app.config.get("VAPID_PUBLIC_KEY") and current_app.config.get("VAPID_PRIVATE_KEY")),
    )


@bp.post("/push/subscriptions")
@login_required
async def push_subscribe():
    if not current_app.config.get("VAPID_PUBLIC_KEY") or not current_app.config.get("VAPID_PRIVATE_KEY"):
        raise ApiError("Web Push не настроен на сервере", 503, "push_not_configured")
    data = json_body()
    endpoint = _public_endpoint(data.get("endpoint"))
    keys = data.get("keys")
    if not isinstance(keys, dict):
        raise ApiError("В подписке отсутствуют ключи", 400, "validation_error")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not isinstance(p256dh, str) or not 20 <= len(p256dh) <= 128 or not isinstance(auth, str) or not 8 <= len(auth) <= 64:
        raise ApiError("Некорректные ключи Push-подписки", 400, "validation_error")
    async with session_scope() as s:
        existing = await s.scalar(select(PushSubscription).where(
            PushSubscription.endpoint == endpoint).with_for_update())
        if existing and existing.user_id != g.user.id:
            raise ApiError("Эта подписка уже привязана к другому аккаунту", 409, "subscription_in_use")
        if existing:
            existing.p256dh, existing.auth = p256dh, auth
            existing.user_agent = (request.user_agent.string or "")[:256]
        else:
            s.add(PushSubscription(user_id=g.user.id, endpoint=endpoint, p256dh=p256dh, auth=auth,
                                   user_agent=(request.user_agent.string or "")[:256]))
        pref = await s.get(PushPreference, g.user.id, with_for_update=True)
        if pref is None:
            pref = PushPreference(user_id=g.user.id, enabled=True, categories=push_service.DEFAULT_CATEGORIES.copy())
            s.add(pref)
        else:
            pref.enabled = True
        await s.flush()
    return {"ok": True, "subscribed": True}


@bp.delete("/push/subscriptions")
@login_required
async def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    async with session_scope() as s:
        stmt = select(PushSubscription).where(PushSubscription.user_id == g.user.id)
        if endpoint:
            stmt = stmt.where(PushSubscription.endpoint == endpoint)
        rows = (await s.scalars(stmt)).all()
        for row in rows:
            await s.delete(row)
        remains = bool(await s.scalar(select(PushSubscription.id).where(
            PushSubscription.user_id == g.user.id).limit(1)))
        if not remains:
            pref = await s.get(PushPreference, g.user.id, with_for_update=True)
            if pref:
                pref.enabled = False
    return {"ok": True, "removed": len(rows), "subscribed": remains}
