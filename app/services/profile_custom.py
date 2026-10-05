"""Кастомизация профиля: что можно настроить, допустимые значения и валидация.

Всё хранится в users.profile (JSONB) + users.avatar_url / users.banner_url / display_name / bio.
Сервер принимает только известные ключи и значения из белых списков — никакого
произвольного CSS/HTML от юзеров (XSS и «сломай вёрстку всем» исключены).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from sqlalchemy import select

from ..errors import ApiError
from ..models import Kombucha, Upload, User, UserBadge
from .markdown import MEDIA_RE

THEMES = {
    "default": "Классика", "neon": "Неон", "sunset": "Закат", "ocean": "Океан", "forest": "Лес",
    "candy": "Сладкая вата", "mono": "Монохром", "midnight": "Полночь", "sakura": "Сакура", "retro": "Ретро-VHS",
}
FONTS = {"default": "Обычный", "rounded": "Округлый", "mono": "Моноширинный", "serif": "С засечками"}
CARD_STYLES = {"glass": "Стекло", "solid": "Плотные", "outline": "Контур"}
LAYOUTS = {"classic": "Классика", "centered": "По центру", "compact": "Компактно"}
# Рамки аватара открываются уровнем — повод расти
FRAMES = {"none": ("Без рамки", 1), "neon": ("Неон", 2), "fire": ("Огонь", 3), "gold": ("Золото", 5),
          "rainbow": ("Радуга", 8)}
SECTIONS = {"streak": "Стрик", "badges": "Бейджи", "stats": "Грибная статистика",
            "garden": "Живые грибы", "shelf": "Полка с замороженными грибами"}

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_LINKS, MAX_INTERESTS, MAX_SHOWCASE = 5, 10, 3

DEFAULTS = {
    "theme": "default", "accent": None, "font": "default", "card_style": "glass", "layout": "classic",
    "avatar_frame": "none", "status_emoji": "", "status_text": "", "about": "", "city": "", "pronouns": "",
    "links": [], "interests": [], "showcase_badges": [], "pinned_kombucha_id": None, "hidden_sections": [],
}


def options() -> dict:
    return {"themes": THEMES, "fonts": FONTS, "card_styles": CARD_STYLES, "layouts": LAYOUTS,
            "frames": {k: {"title": t, "min_level": lvl} for k, (t, lvl) in FRAMES.items()},
            "sections": SECTIONS,
            "limits": {"links": MAX_LINKS, "interests": MAX_INTERESTS, "showcase_badges": MAX_SHOWCASE,
                       "status_text": 60, "about": 1000, "bio": 300, "display_name": 64, "city": 40,
                       "pronouns": 20}}


def merged(u: User) -> dict:
    return {**DEFAULTS, **(u.profile or {})}


def _s(data: dict, key: str, max_len: int) -> str:
    v = data.get(key) or ""
    if not isinstance(v, str):
        raise ApiError(f"{key}: ожидается строка", 400, "validation_error", field=key)
    v = v.strip()
    if len(v) > max_len:
        raise ApiError(f"{key}: не длиннее {max_len} символов", 400, "validation_error", field=key)
    return v


def _choice(data: dict, key: str, allowed) -> str:
    v = data.get(key)
    if v not in allowed:
        raise ApiError(f"{key}: одно из {', '.join(allowed)}", 400, "validation_error", field=key)
    return v


def _link(item) -> dict:
    if not isinstance(item, dict):
        raise ApiError("links: список объектов {title, url}", 400, "validation_error", field="links")
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()[:30]
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or len(url) > 200:
        raise ApiError("Ссылка должна начинаться с https:// (до 200 символов)", 400, "validation_error",
                       field="links")
    return {"title": title or parts.netloc, "url": url}


async def _own_media(s, url, user_id: int, field: str) -> str | None:
    if url in (None, ""):
        return None
    if not isinstance(url, str) or not MEDIA_RE.match(url):
        raise ApiError("Картинка должна быть загружена через /api/uploads", 400, "validation_error", field=field)
    owner = await s.scalar(select(Upload.user_id).where(Upload.name == url.rsplit("/", 1)[1]))
    if owner != user_id:
        raise ApiError("Картинка не найдена", 400, "validation_error", field=field)
    return url


async def apply_update(s, user: User, data: dict) -> None:
    """Частичное обновление: меняем только присланные ключи."""
    prof = merged(user)
    if "display_name" in data:
        name = _s(data, "display_name", 64)
        user.display_name = name or user.username
    if "bio" in data:
        user.bio = _s(data, "bio", 300) or None
    if "avatar_url" in data:
        user.avatar_url = await _own_media(s, data["avatar_url"], user.id, "avatar_url")
    if "banner_url" in data:
        user.banner_url = await _own_media(s, data["banner_url"], user.id, "banner_url")
    for key, allowed in (("theme", THEMES), ("font", FONTS), ("card_style", CARD_STYLES), ("layout", LAYOUTS)):
        if key in data:
            prof[key] = _choice(data, key, allowed)
    if "avatar_frame" in data:
        frame = _choice(data, "avatar_frame", FRAMES)
        need = FRAMES[frame][1]
        if user.level < need and user.rating_tier == 0:
            raise ApiError(f"Рамка «{FRAMES[frame][0]}» открывается с {need} уровня", 403, "locked",
                           field="avatar_frame")
        prof["avatar_frame"] = frame
    if "accent" in data:
        acc = data["accent"]
        if acc not in (None, "") and not (isinstance(acc, str) and HEX_RE.match(acc)):
            raise ApiError("accent: цвет в формате #RRGGBB", 400, "validation_error", field="accent")
        prof["accent"] = acc.lower() if acc else None
    if "status_emoji" in data:
        emo = _s(data, "status_emoji", 8)
        if emo and (re.search(r"[<>\"'&]", emo) or any(ch.isalnum() for ch in emo)):
            raise ApiError("status_emoji: только эмодзи", 400, "validation_error", field="status_emoji")
        prof["status_emoji"] = emo
    for key, n in (("status_text", 60), ("about", 1000), ("city", 40), ("pronouns", 20)):
        if key in data:
            prof[key] = _s(data, key, n)
    if "links" in data:
        links = data["links"] or []
        if not isinstance(links, list) or len(links) > MAX_LINKS:
            raise ApiError(f"links: до {MAX_LINKS} ссылок", 400, "validation_error", field="links")
        prof["links"] = [_link(x) for x in links]
    if "interests" in data:
        tags = data["interests"] or []
        if not isinstance(tags, list) or len(tags) > MAX_INTERESTS:
            raise ApiError(f"interests: до {MAX_INTERESTS} тегов", 400, "validation_error", field="interests")
        clean = []
        for t in tags:
            t = str(t).strip().lstrip("#")[:24]
            if t and t.lower() not in {c.lower() for c in clean}:
                clean.append(t)
        prof["interests"] = clean
    if "showcase_badges" in data:
        codes = data["showcase_badges"] or []
        if not isinstance(codes, list) or len(codes) > MAX_SHOWCASE:
            raise ApiError(f"showcase_badges: до {MAX_SHOWCASE} бейджей", 400, "validation_error",
                           field="showcase_badges")
        owned = set((await s.scalars(select(UserBadge.code).where(UserBadge.user_id == user.id))).all())
        owned.update(item["code"] for item in ((user.profile or {}).get("halloween_raid_badges") or [])
                     if isinstance(item, dict) and item.get("code"))
        if not set(codes) <= owned:
            raise ApiError("В витрину можно поставить только свои бейджи", 400, "validation_error",
                           field="showcase_badges")
        prof["showcase_badges"] = list(dict.fromkeys(codes))
    if "pinned_kombucha_id" in data:
        kid = data["pinned_kombucha_id"]
        if kid is not None:
            k = await s.get(Kombucha, kid) if isinstance(kid, int) and not isinstance(kid, bool) else None
            if k is None or k.user_id != user.id:
                raise ApiError("Закрепить можно только своего гриба", 400, "validation_error", field="pinned_kombucha_id")
        prof["pinned_kombucha_id"] = kid
    if "hidden_sections" in data:
        hs = data["hidden_sections"] or []
        if not isinstance(hs, list) or not set(hs) <= SECTIONS.keys():
            raise ApiError(f"hidden_sections: из {', '.join(SECTIONS)}", 400, "validation_error",
                           field="hidden_sections")
        prof["hidden_sections"] = sorted(set(hs))
    user.profile = {k: v for k, v in prof.items() if v != DEFAULTS.get(k)}


def public_custom(u: User) -> dict:
    """То, что видят все (about рендерится в markdown отдельно)."""
    p = merged(u)
    return {k: p[k] for k in ("theme", "accent", "font", "card_style", "layout", "avatar_frame",
                              "status_emoji", "status_text", "about", "city", "pronouns", "links",
                              "interests", "showcase_badges", "pinned_kombucha_id", "hidden_sections")} | {
        "banner_url": u.banner_url, "avatar_url": u.avatar_url}
