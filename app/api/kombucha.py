"""API мини-игры «Чайный гриб»."""
from __future__ import annotations

import re

from flask import g
from sqlalchemy import select

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import Kombucha, User
from ..services import kombucha as kb
from . import bp
from .utils import json_body

NAME_RE = re.compile(r"^[\w\- .ёЁ]{1,32}$")


def _name(data: dict) -> str | None:
    name = data.get("name")
    if name is None:
        return None
    name = str(name).strip()
    if not NAME_RE.match(name):
        raise ApiError("Имя гриба: 1–32 буквы, цифры, пробел, точка или дефис", 400, "validation_error", field="name")
    return name


@bp.get("/kombucha")
@login_required
async def kombucha_get():
    async with session_scope() as s:
        k = await kb.get_or_create(s, g.user.id)
        return {"kombucha": kb.out(k)}


@bp.post("/kombucha/<any(sugar, tea, clean, pet, daily):action>")
@login_required
async def kombucha_act(action: str):
    async with session_scope() as s:
        k = await kb.get_or_create(s, g.user.id)
        before = kb.stage_for(k.xp)["title"]
        msg = await kb.act(s, k, action)
        res = kb.out(k)
        return {"kombucha": res, "message": msg, "stage_up": res["stage"]["title"] != before}


@bp.patch("/kombucha")
@login_required
async def kombucha_rename():
    name = _name(json_body())
    if not name:
        raise ApiError("Укажи имя", 400, "validation_error", field="name")
    async with session_scope() as s:
        k = await kb.get_or_create(s, g.user.id)
        k.name = name
        return {"kombucha": kb.out(k)}


@bp.post("/kombucha/restart")
@login_required
async def kombucha_restart():
    name = _name(json_body())
    async with session_scope() as s:
        k = await kb.get_or_create(s, g.user.id)
        kb.restart(k, name)
        return {"kombucha": kb.out(k)}


@bp.get("/kombucha/top")
async def kombucha_top():
    """Топ живых грибов по опыту."""
    async with session_scope() as s:
        rows = (await s.execute(
            select(Kombucha, User.username).join(User, User.id == Kombucha.user_id)
            .where(Kombucha.alive.is_(True)).order_by(Kombucha.xp.desc()).limit(10))).all()
    return {"items": [{"username": u, "name": k.name, "xp": k.xp, "generation": k.generation,
                       "stage": kb.stage_for(k.xp)["title"]} for k, u in rows]}
