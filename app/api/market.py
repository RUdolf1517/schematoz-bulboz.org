"""Заморозка, полка, рынок и обмен грибами.

Правила:
* продавать и менять можно только замороженные грибы — живой гриб в процессе ухода не «уезжает» посреди кулдауна;
* после сделки гриб остаётся замороженным на полке нового хозяина, разморозить — если есть свободная банка;
* комиссия рынка 5% сгорает (борьба с инфляцией $₽).
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import g, request
from sqlalchemy import or_, select

from ..auth.rbac import login_required
from ..db import session_scope
from ..errors import ApiError
from ..models import Kombucha, KombuchaTrade, User
from ..services import kombucha as kb
from ..services import kombucha_achievements as ach
from ..services import wood
from ..services.notifications import notify
from . import bp
from .utils import json_body

MAX_PENDING_TRADES = 10


@bp.post("/kombucha/<int:kid>/<any(freeze, unfreeze):op>")
@login_required
async def kombucha_freeze(kid: int, op: str):
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await kb.get_own(s, user.id, kid)
        kb.tick(k)
        if op == "freeze":
            await kb.freeze(s, user, k)
        else:
            await kb.unfreeze(s, user, k)
        await s.flush()
        return {"kombucha": kb.out(k), "jars": await kb.jars_info(s, user)}


@bp.post("/kombucha/<int:kid>/list")
@login_required
async def kombucha_list(kid: int):
    data = json_body()
    price = data.get("price")
    if not isinstance(price, int) or isinstance(price, bool) or not wood.MIN_PRICE <= price <= wood.MAX_PRICE:
        raise ApiError(f"Цена: целое от {wood.MIN_PRICE} до {wood.MAX_PRICE} {wood.SIGN}", 400,
                       "validation_error", field="price")
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        if not k.alive or not k.frozen:
            raise ApiError("Продавать можно только живой замороженный гриб 🧊", 409, "kombucha_not_frozen")
        k.price, k.listed_at = price, datetime.now(timezone.utc)
        return {"kombucha": kb.out(k)}


@bp.delete("/kombucha/<int:kid>/list")
@login_required
async def kombucha_unlist(kid: int):
    async with session_scope() as s:
        k = await kb.get_own(s, g.user.id, kid)
        k.price = k.listed_at = None
        return {"kombucha": kb.out(k)}


@bp.get("/market")
async def market():
    """Витрина. sort: new | cheap | rare. rarity: фильтр по самой редкой мутации."""
    sort = request.args.get("sort", "new")
    rarity = request.args.get("rarity")
    async with session_scope() as s:
        q = (select(Kombucha, User.username).join(User, User.id == Kombucha.user_id)
             .where(Kombucha.price.is_not(None), Kombucha.frozen.is_(True), Kombucha.alive.is_(True)))
        q = q.order_by(Kombucha.price.asc() if sort == "cheap" else Kombucha.listed_at.desc()).limit(200)
        rows = (await s.execute(q)).all()
    items = [kb.public_out(k, u) for k, u in rows]
    rank = {r: i for i, r in enumerate(kb.RARITY_ORDER)}
    for it in items:
        it["top_rarity"] = it["mutations"][0]["rarity"] if it["mutations"] else None
    if rarity:
        items = [i for i in items if i["top_rarity"] == rarity]
    if sort == "rare":
        items.sort(key=lambda i: (rank.get(i["top_rarity"], 99), -len(i["mutations"]), i["price"]))
    return {"items": items[:100], "fee": wood.MARKET_FEE, "sign": wood.SIGN}


@bp.post("/market/<int:kid>/buy")
@login_required
async def market_buy(kid: int):
    data = json_body()
    async with session_scope() as s:
        buyer = await s.get(User, g.user.id, with_for_update=True)
        k = await s.get(Kombucha, kid, with_for_update=True)
        if k is None or k.price is None or not k.frozen or not k.alive:
            raise ApiError("Гриб уже не продаётся", 404, "not_listed")
        if k.user_id == buyer.id:
            raise ApiError("Это твой гриб 🙃", 409, "own_kombucha")
        # защита от «продавец поднял цену, пока ты жал кнопку»
        if data.get("price") is not None and data.get("price") != k.price:
            raise ApiError("Цена изменилась", 409, "price_changed", price=k.price)
        price, seller_id = k.price, k.user_id
        await wood.spend(s, buyer.id, price, "buy_kombucha", k.id)
        got = price - int(price * wood.MARKET_FEE)
        # sale не имеет суточного лимита, ref уникален на сделку
        await wood.earn(s, seller_id, "sale", f"{k.id}:{datetime.now(timezone.utc).timestamp()}", amount=got)
        await kb.transfer(s, k, buyer.id, "sale", price)
        await ach.award(s, seller_id, "kb_sale")
        await ach.award(s, buyer.id, "kb_buy")
        notify(s, seller_id, "sale", username=buyer.username, kombucha_name=k.name, amount=got)
        await s.flush()
        return {"kombucha": kb.out(k), "wood": await wood.balance(s, buyer.id), "paid": price}


# ---------------------------------------------------------------- обмен
def _trade_out(t: KombuchaTrade, users: dict, kombs: dict) -> dict:
    return {"id": t.id, "status": t.status, "created_at": t.created_at.isoformat(),
            "from": users.get(t.from_user_id), "to": users.get(t.to_user_id),
            "give": kombs.get(t.give_id), "want": kombs.get(t.want_id) if t.want_id else None,
            "gift": t.want_id is None, "message": t.message}


@bp.get("/trades")
@login_required
async def trades_list():
    uid = g.user.id
    async with session_scope() as s:
        rows = (await s.scalars(select(KombuchaTrade).where(
            or_(KombuchaTrade.from_user_id == uid, KombuchaTrade.to_user_id == uid))
            .order_by(KombuchaTrade.id.desc()).limit(100))).all()
        uids = {t.from_user_id for t in rows} | {t.to_user_id for t in rows}
        kids = {t.give_id for t in rows} | {t.want_id for t in rows if t.want_id}
        users = {u.id: u.username for u in (await s.scalars(select(User).where(User.id.in_(uids)))).all()} if uids else {}
        kombs = {k.id: kb.public_out(k, users.get(k.user_id))
                 for k in (await s.scalars(select(Kombucha).where(Kombucha.id.in_(kids)))).all()} if kids else {}
    items = [_trade_out(t, users, kombs) for t in rows]
    return {"incoming": [i for i, t in zip(items, rows) if t.to_user_id == uid],
            "outgoing": [i for i, t in zip(items, rows) if t.from_user_id == uid]}


def _tradable(k: Kombucha | None, owner_id: int, what: str) -> Kombucha:
    if k is None or k.user_id != owner_id:
        raise ApiError(f"{what}: гриб не найден", 404, "not_found")
    if not k.alive or not k.frozen:
        raise ApiError(f"{what}: меняться можно только живыми замороженными грибами 🧊", 409, "kombucha_not_frozen")
    return k


@bp.post("/trades")
@login_required
async def trade_create():
    """{to_username, give_id, want_id|null}. want_id=null — подарок."""
    data = json_body()
    uname = str(data.get("to_username") or "").strip().lstrip("@").lower()
    give_id, want_id = data.get("give_id"), data.get("want_id")
    message = str(data.get("message") or "").strip()[:140] or None
    if not isinstance(give_id, int) or (want_id is not None and not isinstance(want_id, int)):
        raise ApiError("give_id и want_id — числа", 400, "validation_error")
    async with session_scope() as s:
        to = await s.scalar(select(User).where(User.username == uname))
        if to is None:
            raise ApiError("Нет такого пользователя", 404, "not_found", field="to_username")
        if to.id == g.user.id:
            raise ApiError("Сам с собой не меняются", 409, "self_trade")
        _tradable(await s.get(Kombucha, give_id), g.user.id, "Твой")
        if want_id is not None:
            _tradable(await s.get(Kombucha, want_id), to.id, "Чужой")
        from sqlalchemy import func
        n = await s.scalar(select(func.count()).select_from(KombuchaTrade).where(
            KombuchaTrade.from_user_id == g.user.id, KombuchaTrade.status == "pending"))
        if n >= MAX_PENDING_TRADES:
            raise ApiError(f"Не больше {MAX_PENDING_TRADES} активных предложений", 429, "too_many_trades")
        t = KombuchaTrade(from_user_id=g.user.id, to_user_id=to.id, give_id=give_id, want_id=want_id,
                          message=message)
        s.add(t)
        await s.flush()
        notify(s, to.id, "trade", trade_id=t.id, username=g.user.username, gift=want_id is None)
        return {"trade": {"id": t.id, "status": "pending"}}, 201


@bp.post("/trades/<int:tid>/<any(accept, decline, cancel):op>")
@login_required
async def trade_decide(tid: int, op: str):
    uid = g.user.id
    async with session_scope() as s:
        t = await s.get(KombuchaTrade, tid, with_for_update=True)
        if t is None or uid not in (t.from_user_id, t.to_user_id):
            raise ApiError("Предложение не найдено", 404, "not_found")
        if t.status != "pending":
            raise ApiError("Предложение уже закрыто", 409, "trade_closed", trade_status=t.status)
        if op == "cancel" and uid != t.from_user_id or op in ("accept", "decline") and uid != t.to_user_id:
            raise ApiError("Не твоё предложение", 403, "forbidden")
        t.decided_at = datetime.now(timezone.utc)
        if op != "accept":
            t.status = "declined" if op == "decline" else "cancelled"
            return {"trade": {"id": t.id, "status": t.status}}
        # блокируем оба гриба в порядке id, чтобы не словить дедлок со встречной сделкой
        ids = sorted(x for x in (t.give_id, t.want_id) if x)
        locked = {k.id: k for k in (await s.scalars(
            select(Kombucha).where(Kombucha.id.in_(ids)).order_by(Kombucha.id).with_for_update())).all()}
        give = _tradable(locked.get(t.give_id), t.from_user_id, "Предлагаемый")
        want = _tradable(locked.get(t.want_id), t.to_user_id, "Запрошенный") if t.want_id else None
        await kb.transfer(s, give, t.to_user_id, "trade" if want else "gift")
        if want:
            await kb.transfer(s, want, t.from_user_id, "trade")
        if not want:
            await ach.award(s, t.from_user_id, "kb_gift")
        t.status = "accepted"
        await ach.award(s, t.from_user_id, "kb_trade")
        await ach.award(s, t.to_user_id, "kb_trade")
        notify(s, t.from_user_id, "trade", trade_id=t.id, username=g.user.username, accepted=True)
        return {"trade": {"id": t.id, "status": "accepted"}}


@bp.get("/users/<username>/shelf")
async def shelf(username: str):
    """Полка: замороженные грибы пользователя (витрина в профиле)."""
    async with session_scope() as s:
        u = await s.scalar(select(User).where(User.username == username.lower()))
        if u is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        rows = (await s.scalars(select(Kombucha).where(Kombucha.user_id == u.id, Kombucha.frozen.is_(True))
                                .order_by(Kombucha.frozen_at.desc()))).all()
        from ..auth.sessions import current_user_id
        if "shelf" in ((u.profile or {}).get("hidden_sections") or []) and current_user_id() != u.id:
            rows = []
    return {"items": [kb.public_out(k, u.username) for k in rows]}


@bp.get("/kombucha/<int:kid>/card")
async def kombucha_card(kid: int):
    """Публичная карточка гриба — как страница подарка в Telegram: мутации с номерами, тираж, история владельцев."""
    from ..models import MutationCounter
    async with session_scope() as s:
        row = (await s.execute(select(Kombucha, User.username).join(User, User.id == Kombucha.user_id)
                               .where(Kombucha.id == kid))).first()
        if row is None:
            raise ApiError("Гриб не найден", 404, "not_found")
        k, owner = row
        codes = [m.get("code") for m in (k.mutations or [])]
        issued = dict((await s.execute(select(MutationCounter.code, MutationCounter.issued)
                                       .where(MutationCounter.code.in_(codes or [""])))).all())
    o = kb.public_out(k, owner)
    for m in o["mutations"]:
        m["issued"] = issued.get(m["code"], 0)
    o["owners"] = [{"username": x.get("username"), "at": x.get("at"), "how": x.get("how"), "price": x.get("price")}
                   for x in (k.owners or [])]
    return {"kombucha": o}
