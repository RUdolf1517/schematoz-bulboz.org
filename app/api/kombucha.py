"""API мини-игры «Чайный гриб», магазина и кошелька «Деревянных»."""
from __future__ import annotations

import re

from flask import g, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import Kombucha, KombuchaCodex, User, WoodTx
from ..services import kombucha as kb
from ..services import wood
from . import bp
from .utils import json_body

NAME_RE = re.compile(r"^[\w\- .ёЁ]{2,32}$")


def _name(data: dict, required: bool = False) -> str | None:
    name = data.get("name")
    if name in (None, ""):
        if required:
            raise ApiError("Укажи имя", 400, "validation_error", field="name")
        return None
    name = re.sub(r"\s+", " ", str(name)).strip()
    if not NAME_RE.match(name):
        raise ApiError("Имя гриба: 2–32 символа — буквы, цифры, пробел, точка, дефис", 400,
                       "validation_error", field="name")
    return name


async def _state(s, user: User) -> dict:
    items = await kb.list_for(s, user.id)
    codex = (await s.execute(select(KombuchaCodex).where(KombuchaCodex.user_id == user.id)
                             .order_by(KombuchaCodex.found_at))).scalars().all()
    return {"items": [kb.out(k) for k in items], "jars": await kb.jars_info(s, user),
            "wood": await wood.balance(s, user.id), "prices": wood.PRICES,
            "codex": [{"code": c.code, "found_at": c.found_at.isoformat(), "kombucha_name": c.kombucha_name}
                      for c in codex],
            "catalog": kb.catalog()}


@bp.get("/kombucha")
@login_required
async def kombucha_get():
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        await kb.ensure_first(s, user)
        return await _state(s, user)


@bp.post("/kombucha/<int:kid>/<any(sugar, tea, clean, pet, daily):action>")
@login_required
async def kombucha_act(kid: int, action: str):
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.get_own(s, user.id, kid)
        before = kb.stage_for(k.xp)["title"]
        res = await kb.act(s, user, k, action)
        await s.flush()
        state = await _state(s, user)
        state.update(res, kombucha=kb.out(k), stage_up=kb.stage_for(k.xp)["title"] != before)
        return state


@bp.patch("/kombucha/<int:kid>")
@login_required
async def kombucha_rename(kid: int):
    name = _name(json_body(), required=True)
    try:
        async with session_scope() as s:
            k = await kb.get_own(s, g.user.id, kid)
            k.name = await kb.ensure_name(s, name, exclude_id=k.id)
            await s.flush()
            return {"kombucha": kb.out(k)}
    except IntegrityError:  # гонка: кто-то занял имя между проверкой и записью
        raise ApiError(f"Имя «{name}» уже занято другим грибом", 409, "name_taken", field="name")


@bp.post("/kombucha/<int:kid>/restart")
@login_required
async def kombucha_restart(kid: int):
    name = _name(json_body())
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        await kb.restart(s, k, name)
        return {"kombucha": kb.out(k)}


@bp.post("/kombucha/<int:kid>/revive")
@login_required
async def kombucha_revive(kid: int):
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.get_own(s, user.id, kid)
        await kb.revive(s, user, k)
        return {"kombucha": kb.out(k), "wood": await wood.balance(s, user.id)}


@bp.delete("/kombucha/<int:kid>")
@login_required
async def kombucha_discard(kid: int):
    """Выбросить закисший гриб — освобождает банку."""
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        if k.alive:
            raise ApiError("Живой гриб выбрасывать нельзя 🥺", 409, "kombucha_alive")
        await s.delete(k)
    return {"ok": True}


@bp.post("/kombucha/plant")
@login_required
async def kombucha_plant():
    name = _name(json_body())
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.plant(s, user, name)
        return {"kombucha": kb.out(k)}, 201


@bp.post("/shop/jar")
@login_required
async def shop_jar():
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        res = await kb.buy_jar(s, user)
        return {**res, "jars": await kb.jars_info(s, user), "wood": await wood.balance(s, user.id)}


@bp.get("/kombucha/top")
async def kombucha_top():
    """Топ живых грибов по опыту."""
    async with session_scope() as s:
        rows = (await s.execute(
            select(Kombucha, User.username).join(User, User.id == Kombucha.user_id)
            .where(Kombucha.alive.is_(True)).order_by(Kombucha.xp.desc(), Kombucha.id).limit(10))).all()
    return {"items": [{"username": u, "name": k.name, "xp": k.xp, "generation": k.generation,
                       "stage": kb.stage_for(k.xp)["title"], "mutations": len(k.mutations or [])}
                      for k, u in rows]}


@bp.get("/wallet")
@login_required
async def wallet():
    before = request.args.get("before", type=int)
    async with session_scope() as s:
        q = select(WoodTx).where(WoodTx.user_id == g.user.id)
        if before:
            q = q.where(WoodTx.id < before)
        rows = (await s.scalars(q.order_by(WoodTx.id.desc()).limit(50))).all()
        bal = await wood.balance(s, g.user.id)
    return {"balance": bal, "sign": wood.SIGN, "rules": wood.rules(), "prices": wood.PRICES,
            "items": [{"id": t.id, "delta": t.delta, "reason": t.reason, "title": wood.title_for(t.reason),
                       "balance_after": t.balance_after, "created_at": t.created_at.isoformat()} for t in rows],
            "next_before": rows[-1].id if len(rows) == 50 else None}
