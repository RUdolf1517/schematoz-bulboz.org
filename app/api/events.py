"""Halloween event state, daily trick-or-treat and the shared boss raid."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from flask import g
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..auth.rbac import require_any_perm, require_perm
from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import HalloweenRaid, HalloweenRaidPlayer, HalloweenTreat, Kombucha, User
from ..services import halloween, kombucha as kb
from ..services.notifications import notify, notify_once
from ..services.push import enqueue_push
from . import bp
from .utils import json_body

UTC = timezone.utc
RAID_MAX_HP = 10000
RAID_REGEN_PER_SECOND = 0.1  # 6 HP/minute; player taps do at least 1 damage each.
RAID_TAP_COOLDOWN = timedelta(milliseconds=250)


def _raid_hp(raid: HalloweenRaid, at: datetime) -> int:
    elapsed = max(0.0, (at - raid.updated_at).total_seconds())
    return min(raid.max_hp, raid.hp + int(elapsed * RAID_REGEN_PER_SECOND))


async def _ensure_raid(s, *, lock: bool = True) -> HalloweenRaid:
    query = select(HalloweenRaid).where(HalloweenRaid.id == 1)
    if lock:
        query = query.with_for_update()
    raid = await s.scalar(query)
    if raid is not None:
        return raid
    await s.execute(insert(HalloweenRaid).values(id=1, hp=RAID_MAX_HP, max_hp=RAID_MAX_HP, phase=1, total_damage=0)
                    .on_conflict_do_nothing(index_elements=["id"]))
    query = select(HalloweenRaid).where(HalloweenRaid.id == 1)
    if lock:
        query = query.with_for_update()
    return await s.scalar(query)


@bp.get("/events/state")
async def event_state():
    uid = current_user_id()
    async with session_scope() as s:
        config = await halloween.get_config(s)
        user = await s.get(User, uid) if uid else None
        state = halloween.public_state(config, user)
        if state["active"] and user:
            await halloween.award_survivor(s, user.id)
    return state


@bp.get("/events/halloween/raid")
async def halloween_raid_state():
    """Public read-only state of the one shared raid boss during the active event."""
    at = datetime.now(UTC)
    uid = current_user_id()
    async with session_scope() as s:
        config = await halloween.get_config(s)
        is_active = halloween.active(config, at)
        if not is_active:
            return {"active": False}
        raid = await _ensure_raid(s, lock=False)
        player = await s.get(HalloweenRaidPlayer, uid) if uid else None
        return {"boss": "Тыквенная плесень", "hp": _raid_hp(raid, at), "max_hp": raid.max_hp,
                "phase": raid.phase, "total_damage": raid.total_damage,
                "my_damage": player.damage if player else 0, "regen_per_minute": 6, "active": is_active}


@bp.post("/events/halloween/raid/tap")
@require_any_perm("kombucha.play", "role.assign")
async def halloween_raid_tap():
    at = datetime.now(UTC)
    async with session_scope() as s:
        config = await halloween.get_config(s)
        if not halloween.active(config, at):
            raise ApiError("Хэллоуинский рейд сейчас закрыт", 409, "event_inactive")
        await s.get(User, g.user.id, with_for_update=True)
        await s.execute(insert(HalloweenRaidPlayer).values(user_id=g.user.id, damage=0)
                        .on_conflict_do_nothing(index_elements=["user_id"]))
        player = await s.scalar(select(HalloweenRaidPlayer).where(
            HalloweenRaidPlayer.user_id == g.user.id).with_for_update())
        if player.last_tap_at and at - player.last_tap_at < RAID_TAP_COOLDOWN:
            raise ApiError("Дай плесени долю секунды", 429, "raid_too_fast", retry_after=0.25)
        raid = await _ensure_raid(s)
        if raid.hp < raid.max_hp:
            elapsed = max(0.0, (at - raid.updated_at).total_seconds())
            regen = int(elapsed * RAID_REGEN_PER_SECOND)
            if regen:
                raid.hp = min(raid.max_hp, raid.hp + regen)
                raid.updated_at += timedelta(seconds=regen / RAID_REGEN_PER_SECOND)
            if raid.hp == raid.max_hp:
                raid.updated_at = at
        else:
            raid.updated_at = at
        raid.hp = max(0, raid.hp - 1)
        raid.total_damage += 1
        player.damage += 1
        player.last_tap_at = at
        defeated = raid.hp <= 0
        if defeated:
            raid.phase += 1
            raid.hp = raid.max_hp
            raid.updated_at = at
        await halloween.award_survivor(s, g.user.id)
        return {"boss": "Тыквенная плесень", "hp": raid.hp, "max_hp": raid.max_hp,
                "phase": raid.phase, "total_damage": raid.total_damage,
                "my_damage": player.damage, "defeated": defeated,
                "message": "Плесень рассыпалась… и тут же выросла новая!" if defeated else None}


@bp.post("/events/halloween/treat/<int:kid>")
@require_perm("kombucha.play")
async def halloween_treat(kid: int):
    at = datetime.now(UTC)
    async with session_scope() as s:
        config = await halloween.get_config(s)
        if not halloween.active(config, at):
            raise ApiError("Сладости или гадости доступны только во время Хэллоуина", 409, "event_inactive")
        actor = await s.get(User, g.user.id, with_for_update=True)
        target = await s.get(Kombucha, kid, with_for_update=True)
        if target is None or not target.alive:
            raise ApiError("Гриб не найден или уже закис", 404, "not_found")
        if target.user_id == actor.id:
            raise ApiError("Своему грибу сладость не выпросить — иди к другу", 409, "own_kombucha")
        owner = await s.get(User, target.user_id)
        if owner is None or "garden" in ((owner.profile or {}).get("hidden_sections") or []):
            raise ApiError("Этот подоконник закрыт", 404, "not_found")
        day = halloween.day_for(at)
        result = await s.execute(
            insert(HalloweenTreat).values(actor_user_id=actor.id, kombucha_id=target.id,
                                          owner_user_id=owner.id, day=day, reward="pending")
            .on_conflict_do_nothing(index_elements=["actor_user_id", "kombucha_id", "day"])
            .returning(HalloweenTreat.id)
        )
        treat_id = result.scalar()
        if not treat_id:
            raise ApiError("Этому грибу ты уже нажимал(а) сегодня", 409, "treat_already_used")

        owned = await halloween.inventory(actor)
        missing_hats = [code for code in halloween.HATS if code not in owned]
        roll = random.random()
        message = ""
        reward, code = "trick", None
        if roll < 0.45:
            target.halloween_web_until = at + timedelta(hours=2)
            reward = "web"
            message = f"Пакость! На банке «{target.name}» появилась паутина на пару часов 🕸️"
            from ..services.kombucha_diary import log
            log(s, target, "haunted", at=at)
        elif missing_hats and roll < 0.75:
            code = random.choice(missing_hats)
            actor.profile = {**(actor.profile or {}), "halloween_hats": [*owned, code]}
            reward = "hat"
            message = f"Сладость! Выпала шапка «{halloween.HATS[code]['title']}» {halloween.HATS[code]['emoji']}"
        else:
            own_mushroom = await s.scalar(select(Kombucha).where(
                Kombucha.user_id == actor.id, Kombucha.alive.is_(True), Kombucha.frozen.is_(False)
            ).order_by(Kombucha.id).with_for_update())
            if own_mushroom:
                mut = halloween.add_temp_mutation(s, own_mushroom, at=at, force=True)
                await halloween.alert_temp_mutation(s, own_mushroom, mut)
                reward, code = "mutation", mut["code"]
                message = f"Сладость! {mut['emoji']} Временная мутация «{mut['title']}» — на три дня"
            elif missing_hats:
                code = random.choice(missing_hats)
                actor.profile = {**(actor.profile or {}), "halloween_hats": [*owned, code]}
                reward = "hat"
                message = f"Сладость! Выпала шапка «{halloween.HATS[code]['title']}» {halloween.HATS[code]['emoji']}"
            else:
                reward = "trick"
                target.halloween_web_until = at + timedelta(hours=2)
                message = "Все шапки уже твои — банке досталась паутинка 🕸️"
        await s.execute(
            HalloweenTreat.__table__.update().where(HalloweenTreat.id == treat_id)
            .values(reward=reward, reward_code=code)
        )
        notify(s, actor.id, "halloween", text=message, kombucha_id=target.id)
        notify(s, owner.id, "halloween", text=f"@{actor.username} сыграл(а) с грибом «{target.name}»: {message}",
               kombucha_id=target.id)
        await enqueue_push(s, owner.id, "halloween", "Сладость или гадость 🎃",
                           f"@{actor.username} постучал(а) по банке «{target.name}».",
                           f"/g/{target.id}", f"treat:{treat_id}")
        await halloween.award_survivor(s, actor.id)
        return {"reward": reward, "code": code, "message": message,
                "owned_hats": await halloween.inventory(actor), "treat_id": treat_id}


@bp.post("/events/halloween/hat/<int:kid>")
@require_perm("kombucha.play")
async def halloween_equip_hat(kid: int):
    data = json_body()
    code = data.get("code")
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await s.get(Kombucha, kid, with_for_update=True)
        if k is None or k.user_id != user.id:
            raise ApiError("Гриб не найден", 404, "not_found")
        if code is not None:
            if code not in halloween.HATS or code not in await halloween.inventory(user):
                raise ApiError("Этой шапки пока нет в коллекции", 400, "hat_not_owned")
        k.halloween_hat = code
        await s.flush()
        return {"kombucha": kb.out(k), "owned_hats": await halloween.inventory(user)}
