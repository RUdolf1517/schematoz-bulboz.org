"""Профиль грибовода: кастомизация, бейджи, грибная статистика, закреплённый гриб."""
from __future__ import annotations

from flask import g
from sqlalchemy import func, select

from ..auth.rbac import login_required, require_perm
from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import Kombucha, KombuchaCodex, User
from ..services import kombucha as kb
from ..services.gamification import user_badges
from ..services.kombucha_mutations import MUTATIONS
from ..services.markdown import render as render_md
from ..services.profile_custom import apply_update, options, public_custom
from . import bp
from .utils import json_body, user_public


async def kombucha_stats(s, user_id: int) -> dict:
    rows = (await s.scalars(select(Kombucha).where(Kombucha.user_id == user_id))).all()
    codex = await s.scalar(select(func.count()).select_from(KombuchaCodex).where(KombuchaCodex.user_id == user_id))
    return {"kombuchas": len(rows), "alive": sum(1 for k in rows if k.alive and not k.frozen),
            "frozen": sum(1 for k in rows if k.frozen), "codex": codex or 0, "codex_total": len(MUTATIONS),
            "best_xp": max((k.best_xp for k in rows), default=0),
            "best_stage": kb.stage_for(max((k.best_xp for k in rows), default=0))["title"],
            "sprouts": sum(k.sprout_count or 0 for k in rows),
            "max_generation": max((k.generation for k in rows), default=0)}


@bp.get("/users/<username>")
async def profile(username: str):
    async with session_scope() as s:
        user = await s.scalar(select(User).where(User.username == username.lower()))
        if user is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        badges = await user_badges(s, user.id)
        stats = await kombucha_stats(s, user.id)
        garden = (await s.scalars(select(Kombucha).where(Kombucha.user_id == user.id, Kombucha.frozen.is_(False))
                                  .order_by(Kombucha.alive.desc(), Kombucha.xp.desc()))).all()
        for k in garden:
            kb.tick(k)
        garden_out = [kb.public_out(k) for k in garden]
        pinned = None
        pid = (user.profile or {}).get("pinned_kombucha_id")
        if pid:
            k = await s.get(Kombucha, pid)
            if k and k.user_id == user.id:
                kb.tick(k)
                pinned = kb.public_out(k)
        viewer = current_user_id()

    custom = public_custom(user)
    is_owner = viewer == user.id
    hidden = set(custom["hidden_sections"]) if not is_owner else set()
    order = {c: i for i, c in enumerate(custom["showcase_badges"])}
    badges = sorted(badges, key=lambda b: (order.get(b["code"], 99),))
    for b in badges:
        b["showcase"] = b["code"] in order
    out = {
        "user": {**user_public(user), "bio": user.bio, "created_at": user.created_at.isoformat()},
        "custom": custom,
        "about_html": render_md(custom["about"]),
        "pinned_kombucha": pinned,
        "is_owner": is_owner,
        "stats": stats,
        "garden": garden_out,
        "badges": badges,
    }
    # скрытые разделы чужим не отдаём вообще (а не просто прячем на фронте)
    if "badges" in hidden:
        out["badges"] = []
    if "stats" in hidden:
        out["stats"] = {}
    if "garden" in hidden:
        out["garden"] = []
    if "streak" in hidden:
        out["user"]["streak_days"] = None
        out["user"]["streak_freeze_available"] = None
    return out


@bp.get("/me/profile")
@login_required
async def my_profile_settings():
    """Текущие настройки + варианты (темы, шрифты, рамки…) + что доступно юзеру."""
    async with session_scope() as s:
        user = await s.get(User, g.user.id)
        badges = await user_badges(s, user.id)
        ks = (await s.scalars(select(Kombucha).where(Kombucha.user_id == user.id).order_by(Kombucha.xp.desc()))).all()
    return {"user": {**user_public(user), "bio": user.bio}, "settings": public_custom(user),
            "options": options(), "badges": badges,
            "kombuchas": [{"id": k.id, "name": k.name, "stage": kb.stage_for(k.xp)["title"]} for k in ks]}


@bp.patch("/me/profile")
@require_perm("kombucha.play")  # забаненный не меняет витрину
async def update_profile_settings():
    data = json_body()
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        await apply_update(s, user, data)
        await s.flush()
        out = {"user": {**user_public(user), "bio": user.bio}, "settings": public_custom(user)}
    return out
