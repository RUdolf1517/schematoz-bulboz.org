"""PWA Web Push preferences, transactional outbox and delivery policy."""
from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import PushPreference, PushQueue, PushSubscription

PUSH_TYPES = {
    "stat_low": "Сахар, заварка или чистота ниже 30",
    "pet_ready": "Снова можно погладить гриба",
    "streak_expiring": "Стрик сгорит через 3 часа",
    "missing": "Гриб соскучился: давно не заходил(а)",
    "daily_bonus": "Готов бонус дня",
    "sharing": "Гриб готов делиться",
    "mutation": "Появилась мутация",
    "mold": "Гриб в плесени",
    "dying": "Гриб на грани гибели",
    "dead": "Гриб закис",
    "game_reward": "Мини-игру снова можно пройти с наградой",
    "sale": "Твоего гриба купили на рынке",
    "halloween": "Хэллоуинские события",
}

DEFAULT_CATEGORIES = {key: True for key in PUSH_TYPES}
DEFAULTS = {
    "enabled": False,
    "categories": DEFAULT_CATEGORIES,
    "quiet_start": "23:00",
    "quiet_end": "09:00",
    "timezone": "Europe/Moscow",
}
DAILY_CAP = 8


def _valid_clock(value: str) -> bool:
    try:
        time.fromisoformat(value)
        return len(value) == 5 and value[2] == ":"
    except (TypeError, ValueError):
        return False


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, TypeError):
        return ZoneInfo("Europe/Moscow")


def prefs_out(pref: PushPreference | None, subscribed: bool, vapid_key: str | None, configured: bool | None = None) -> dict:
    categories = {**DEFAULT_CATEGORIES, **((pref.categories or {}) if pref else {})}
    return {
        "enabled": bool(pref.enabled) if pref else False,
        "subscribed": subscribed,
        "configured": bool(vapid_key) if configured is None else configured,
        "vapid_public_key": vapid_key,
        "categories": categories,
        "types": PUSH_TYPES,
        "quiet_start": pref.quiet_start if pref else DEFAULTS["quiet_start"],
        "quiet_end": pref.quiet_end if pref else DEFAULTS["quiet_end"],
        "timezone": pref.timezone if pref else DEFAULTS["timezone"],
        "daily_cap": DAILY_CAP,
    }


def validate_preferences(data: dict, old: PushPreference | None = None) -> dict:
    current = {
        "enabled": old.enabled if old else False,
        "categories": {**DEFAULT_CATEGORIES, **((old.categories or {}) if old else {})},
        "quiet_start": old.quiet_start if old else DEFAULTS["quiet_start"],
        "quiet_end": old.quiet_end if old else DEFAULTS["quiet_end"],
        "timezone": old.timezone if old else DEFAULTS["timezone"],
    }
    if "enabled" in data:
        if not isinstance(data["enabled"], bool):
            raise ValueError("enabled должен быть true или false")
        current["enabled"] = data["enabled"]
    if "categories" in data:
        cats = data["categories"]
        if not isinstance(cats, dict) or any(k not in PUSH_TYPES for k in cats):
            raise ValueError("categories содержит неизвестный тип уведомлений")
        if any(not isinstance(v, bool) for v in cats.values()):
            raise ValueError("Каждый тип уведомлений должен быть true или false")
        current["categories"] = {**current["categories"], **cats}
    for key in ("quiet_start", "quiet_end"):
        if key in data:
            value = data[key]
            if not isinstance(value, str) or not _valid_clock(value):
                raise ValueError(f"{key}: время в формате ЧЧ:ММ")
            current[key] = value
    if "timezone" in data:
        value = data["timezone"]
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("timezone должна быть часовым поясом IANA")
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Неизвестный часовой пояс") from exc
        current["timezone"] = value
    return current


async def enqueue_push(
    s: AsyncSession,
    user_id: int,
    category: str,
    title: str,
    body: str,
    url: str = "/",
    dedupe_key: str = "",
    scheduled_at: datetime | None = None,
) -> bool:
    """Queue a push only for opted-in users with at least one live device."""
    if category not in PUSH_TYPES:
        return False
    pref = await s.get(PushPreference, user_id)
    if not pref or not pref.enabled or not (pref.categories or {}).get(category, True):
        return False
    has_sub = await s.scalar(select(PushSubscription.id).where(PushSubscription.user_id == user_id).limit(1))
    if not has_sub:
        return False
    key = (dedupe_key or f"{category}:{int((scheduled_at or datetime.now(timezone.utc)).timestamp())}")[:128]
    result = await s.execute(
        insert(PushQueue).values(
            user_id=user_id, category=category, dedupe_key=key,
            title=title[:120], body=body[:300],
            url=(url if url.startswith("/") and not url.startswith("//") else "/")[:512],
            scheduled_at=scheduled_at or datetime.now(timezone.utc),
        ).on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"]).returning(PushQueue.id)
    )
    return result.scalar() is not None


def _quiet_until(now: datetime, pref: PushPreference) -> datetime | None:
    zone = _timezone(pref.timezone)
    local_now = now.astimezone(zone)
    start_h, start_m = map(int, (pref.quiet_start or "23:00").split(":"))
    end_h, end_m = map(int, (pref.quiet_end or "09:00").split(":"))
    start, end = time(start_h, start_m), time(end_h, end_m)
    if start == end:
        return None  # Equal boundaries mean quiet hours are disabled.
    current = local_now.timetz().replace(tzinfo=None)
    quiet = (start <= current < end) if start < end else (current >= start or current < end)
    if not quiet:
        return None
    end_day = local_now.date()
    if start > end and current >= start:
        end_day += timedelta(days=1)
    local_end = datetime.combine(end_day, end, tzinfo=zone)
    return local_end.astimezone(timezone.utc)


def _day_bounds(now: datetime, pref: PushPreference) -> tuple[datetime, datetime]:
    zone = _timezone(pref.timezone)
    local_date = now.astimezone(zone).date()
    begin = datetime.combine(local_date, time.min, tzinfo=zone).astimezone(timezone.utc)
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    return begin, end


def _private_key_pem(value: str) -> str:
    """Decode the one-line base64 form emitted by `flask generate-vapid`; keep PEM/path compatibility."""
    if value.startswith("base64:"):
        raw = value[7:]
        raw += "=" * ((4 - len(raw) % 4) % 4)
        try:
            return base64.urlsafe_b64decode(raw.encode("ascii")).decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("VAPID_PRIVATE_KEY has invalid base64 encoding") from exc
    return value.replace("\\n", "\n")


async def dispatch_pushes(limit: int = 200, now: datetime | None = None) -> dict:
    """Deliver due outbox rows. Safe to run repeatedly from cron/systemd timer."""
    now = now or datetime.now(timezone.utc)
    public_key = current_app.config.get("VAPID_PUBLIC_KEY")
    private_key = current_app.config.get("VAPID_PRIVATE_KEY")
    subject = current_app.config.get("VAPID_SUBJECT", "mailto:admin@example.com")
    if not public_key or not private_key:
        return {"configured": False, "sent": 0, "deferred": 0, "failed": 0}
    private_key = _private_key_pem(private_key)

    sent = deferred = failed = 0
    async with _session_scope_for_push() as s:
        rows = (await s.scalars(
            select(PushQueue).where(
                PushQueue.sent_at.is_(None), PushQueue.scheduled_at <= now, PushQueue.attempts < 8,
            ).order_by(PushQueue.scheduled_at, PushQueue.id).limit(limit).with_for_update(skip_locked=True)
        )).all()
        for row in rows:
            pref = await s.get(PushPreference, row.user_id)
            if not pref or not pref.enabled or not (pref.categories or {}).get(row.category, True):
                row.attempts = 8
                row.last_error = "suppressed: disabled by user"
                continue
            until = _quiet_until(now, pref)
            if until:
                row.scheduled_at = until
                deferred += 1
                continue
            start, end = _day_bounds(now, pref)
            already = await s.scalar(select(func.count(PushQueue.id)).where(
                PushQueue.user_id == row.user_id, PushQueue.sent_at >= start, PushQueue.sent_at < end)) or 0
            if already >= DAILY_CAP:
                zone = _timezone(pref.timezone)
                next_day = now.astimezone(zone).date() + timedelta(days=1)
                row.scheduled_at = datetime.combine(next_day, time.min, tzinfo=zone).astimezone(timezone.utc)
                deferred += 1
                continue
            subscriptions = (await s.scalars(select(PushSubscription).where(
                PushSubscription.user_id == row.user_id).order_by(PushSubscription.id))).all()
            if not subscriptions:
                row.attempts = 8
                row.last_error = "suppressed: no active subscription"
                continue
            payload = json.dumps({"title": row.title, "body": row.body, "url": row.url,
                                  "tag": f"bulboz:{row.dedupe_key}"}, ensure_ascii=False)
            success = False
            errors: list[str] = []
            for sub in subscriptions:
                try:
                    await asyncio.to_thread(
                        _send_webpush, sub.endpoint, sub.p256dh, sub.auth, payload, private_key, subject,
                    )
                    sub.last_used_at = now
                    success = True
                except Exception as exc:  # noqa: BLE001 - one failed device must not block the others
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status in (404, 410):
                        await s.delete(sub)
                    errors.append(f"{type(exc).__name__}: {str(exc)[:180]}")
            row.attempts += 1
            if success:
                row.sent_at = now
                row.last_error = None
                sent += 1
            else:
                row.last_error = "; ".join(errors)[:2000] or "delivery failed"
                failed += 1
    return {"configured": True, "sent": sent, "deferred": deferred, "failed": failed}


@asynccontextmanager
async def _session_scope_for_push():
    # Deferred import avoids coupling the preference helpers to application initialization.
    from ..db import session_scope
    async with session_scope() as s:
        yield s


def _send_webpush(endpoint: str, p256dh: str, auth: str, payload: str, private_key: str, subject: str) -> None:
    from pywebpush import webpush
    webpush(
        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
        data=payload,
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},
        ttl=60 * 60,
    )
