"""API мини-игры «Чайный гриб», магазина и кошелька «Деревянных»."""
from __future__ import annotations

import re

from flask import g, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..services.captcha import captcha_required
from ..auth.rbac import login_required
from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import Kombucha, KombuchaCodex, MutationCounter, User, WoodTx
from ..services import kombucha as kb
from ..services import wood
from . import bp


@bp.before_request
async def _custom_quotes_cache():
    """Цитаты из админки живут в Redis; после рестарта кэш поднимается из БД при первом запросе к грибу."""
    if request.path.startswith("/api/kombucha"):
        from ..services import quotes
        try:
            await quotes.ensure_custom()
        except Exception:  # noqa: BLE001 — без кастомных цитат гриб всё равно говорит встроенными
            pass
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


async def _club_decay(s, user_id: int) -> float:
    """Перк клуба «показатели падают медленнее» (0, если игрок без кооператива)."""
    from ..services import clubs
    try:
        return await clubs.decay_slow_for(s, user_id)
    except Exception:  # noqa: BLE001 — перк не должен ломать чтение состояния
        return 0.0


async def _state(s, user: User) -> dict:
    items = await kb.list_for(s, user.id)
    from ..services import halloween
    event = await halloween.get_config(s)
    for k in items:
        await halloween.prepare_k(s, k, event)
    event_state = halloween.public_state(event, user)
    if event_state["active"]:
        await halloween.award_survivor(s, user.id)
    codex = (await s.execute(select(KombuchaCodex).where(KombuchaCodex.user_id == user.id)
                             .order_by(KombuchaCodex.found_at))).scalars().all()
    return {"items": [kb.out(k) for k in items], "jars": await kb.jars_info(s, user),
            "wood": await wood.balance(s, user.id), "prices": wood.PRICES, "halloween": event_state,
            "codex": [{"code": c.code, "found_at": c.found_at.isoformat(), "kombucha_name": c.kombucha_name}
                      for c in codex],
            "catalog": await _catalog(s)}


async def _catalog(s) -> list[dict]:
    """Каталог + сколько экземпляров каждой мутации уже выпало на сайте (тираж, как у подарков в TG)."""
    issued = dict((await s.execute(select(MutationCounter.code, MutationCounter.issued))).all())
    return [{**m, "issued": issued.get(m["code"], 0)} for m in kb.catalog()]


@bp.get("/kombucha")
@login_required
async def kombucha_get():
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        await kb.ensure_first(s, user)
        return await _state(s, user)


@bp.post("/kombucha/<int:kid>/<any(sugar, tea, clean, pet, talk, cure, daily):action>")
@login_required
async def kombucha_act(kid: int, action: str):
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.get_own(s, user.id, kid)
        before = kb.stage_for(k.xp)["title"]
        res = await kb.act(s, user, k, action)
        from ..services import halloween
        event = await halloween.get_config(s)
        res["halloween_mutation"] = await halloween.on_action(s, k, event)
        await s.flush()
        state = await _state(s, user)
        state.update(res, kombucha=kb.out(k), stage_up=kb.stage_for(k.xp)["title"] != before)
        return state


@bp.post("/kombucha/<int:kid>/meditate/start")
@login_required
@captcha_required()  # после 3 партий автокликера за сутки
async def kombucha_meditate_start(kid: int):
    from ..services import meditation
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        return meditation.start(g.user.id, k)


@bp.post("/kombucha/<int:kid>/meditate/finish")
@login_required
async def kombucha_meditate_finish(kid: int):
    from ..services import meditation
    data = json_body()
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.get_own(s, user.id, kid)
        res = await meditation.finish(s, user, k, str(data.get("token") or ""), data.get("taps"), data.get("meta"))
        from ..services import halloween
        event = await halloween.get_config(s)
        hmut = None if res.get("practice") else await halloween.on_action(s, k, event)
        await s.flush()
        return {"result": res, "kombucha": kb.out(k), "wood_balance": await wood.balance(s, user.id),
                "halloween_mutation": hmut}


@bp.get("/kombucha/games")
@login_required
async def kombucha_games():
    from ..services import halloween, minigames
    from ..db import session_scope
    async with session_scope() as s:
        is_halloween = halloween.active(await halloween.get_config(s))
    items = minigames.catalog()
    if is_halloween:
        for item in items:
            if item["code"] == "flies":
                item["title"] = "Хэллоуинские мушки"
                item["emoji"] = "🦇"
                item["about"] = "Гоняй летучих мышей и ночных мушек от банки!"
    return {"items": items, "halloween": is_halloween}


@bp.post("/kombucha/<int:kid>/game/<any(pour, memory, sugar, flies):game>/start")
@login_required
@captcha_required()  # после 3 партий автокликера за сутки
async def kombucha_game_start(kid: int, game: str):
    from ..services import minigames
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        return minigames.start(g.user.id, k, game)


@bp.post("/kombucha/<int:kid>/game/memory/step")
@login_required
async def kombucha_game_memory_step(kid: int):
    from ..services import minigames
    data = json_body()
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        return minigames.memory_step(g.user.id, k, str(data.get("token") or ""), data.get("input"))


@bp.post("/kombucha/<int:kid>/game/<any(pour, memory, sugar, flies):game>/finish")
@login_required
async def kombucha_game_finish(kid: int, game: str):
    from ..services import minigames
    data = json_body()
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.get_own(s, user.id, kid)
        res = await minigames.finish(s, user, k, game, str(data.get("token") or ""), data)
        from ..services import halloween
        event = await halloween.get_config(s)
        hmut = None if res.get("practice") else await halloween.on_action(s, k, event)
        await s.flush()
        return {"result": res, "kombucha": kb.out(k), "wood_balance": await wood.balance(s, user.id),
                "halloween_mutation": hmut}


@bp.patch("/kombucha/<int:kid>")
@login_required
async def kombucha_rename(kid: int):
    name = _name(json_body(), required=True)
    try:
        async with session_scope() as s:
            k = await kb.get_own(s, g.user.id, kid)
            old = k.name
            k.name = await kb.ensure_name(s, name, exclude_id=k.id)
            if old != k.name:
                kb.diary.log(s, k, "renamed", old=old, new=k.name)
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
        balance = await wood.spend(s, user.id, wood.PRICES["mushroom"], "buy_new_kombucha", f"kombucha:{k.id}")
        return {"kombucha": kb.out(k), "wood": balance}, 201


@bp.post("/kombucha/sprout/<int:kid>/plant")
@login_required
async def kombucha_plant_sprout(kid: int):
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        parent = await kb.get_own(s, user.id, kid)
        child = await kb.plant_pending_sprout(s, user, parent)
        return {"kombucha": kb.out(child), "parent": kb.out(parent),
                "jars": await kb.jars_info(s, user), "wood": await wood.balance(s, user.id)}, 201


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
        event_window = await kb.halloween_decay_window(s)
        slows = {}
        for k, _ in rows:
            slows[k.user_id] = slows.get(k.user_id, None)
            if slows[k.user_id] is None:
                slows[k.user_id] = await _club_decay(s, k.user_id)
            kb.tick(k, halloween_window=event_window, decay_slow=slows[k.user_id])
    return {"items": [{"id": k.id, "username": u, "name": k.name, "xp": k.xp, "generation": k.generation,
                       "stage": kb.stage_for(k.xp)["title"], "mutations": len(k.mutations or []),
                       "kombucha": kb.public_out(k, u)}
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


# ---------------------------------------------------------------- дневник гриба (публичный — им делятся ссылкой /g/<id>)
@bp.get("/kombucha/<int:kid>/diary")
async def kombucha_diary(kid: int):
    before = request.args.get("before", type=int)
    async with session_scope() as s:
        k = await s.get(Kombucha, kid)
        if k is None:
            raise ApiError("Гриб не найден", 404, "not_found")
        kb.tick(k, halloween_window=await kb.halloween_decay_window(s),
                decay_slow=await _club_decay(s, user.id))
        owner = (await s.execute(select(User.username).where(User.id == k.user_id))).scalar()
        d = await kb.diary.read(s, k, before)
        return {"kombucha": kb.public_out(k, owner), "mine": current_user_id() == k.user_id, **d}
