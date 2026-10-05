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
from ..services import halloween, halloween_raid, kombucha as kb
from ..services.notifications import notify
from ..services.push import enqueue_push
from . import bp
from .utils import json_body

UTC = timezone.utc
RAID_TAP_COOLDOWN = timedelta(seconds=1)
RAID_STAT_DELTA = {"clean": 1.0, "happy": 1.0, "sweet": -1.0, "tea": -1.0}


def _raid_hp(raid: HalloweenRaid, at: datetime, regen_per_minute: int) -> int:
    elapsed = max(0.0, (at - raid.updated_at).total_seconds())
    regen_rate = max(0, regen_per_minute) / 60
    return min(raid.max_hp, raid.hp + int(elapsed * regen_rate))


async def _ensure_raid(s, initial_hp: int, *, lock: bool = True) -> HalloweenRaid:
    query = select(HalloweenRaid).where(HalloweenRaid.id == 1)
    if lock:
        query = query.with_for_update()
    raid = await s.scalar(query)
    if raid is not None:
        return raid
    await s.execute(insert(HalloweenRaid).values(
        id=1, hp=initial_hp, max_hp=initial_hp, phase=1, total_damage=0
    ).on_conflict_do_nothing(index_elements=["id"]))
    query = select(HalloweenRaid).where(HalloweenRaid.id == 1)
    if lock:
        query = query.with_for_update()
    return await s.scalar(query)


def _stage_damage(player: HalloweenRaidPlayer | None, phase: int) -> int:
    if not player:
        return 0
    try:
        return max(0, int((player.stage_damage or {}).get(str(phase), 0)))
    except (TypeError, ValueError):
        return 0


def _mushroom_out(k: Kombucha) -> dict:
    # Reuse the same visual/game state as the player's mushroom card so the raid shows
    # each actual jar (including stage, mutations, Halloween cosmetics and mood).
    view = kb.out(k)
    return {key: view[key] for key in (
        "id", "name", "alive", "frozen", "stats", "mood", "stage", "mutations",
        "mold", "halloween_hat", "halloween_hat_meta", "halloween_mutations", "halloween_web_until",
    )} | {"halloween_gone": False}


async def _raid_state(s, raid: HalloweenRaid, player: HalloweenRaidPlayer | None,
                      config: dict, at: datetime, user_id: int | None) -> dict:
    raid_config = halloween.normalize_raid_config(config.get("raid"))
    stage, stage_number = halloween.stage_for({"raid": raid_config}, raid.phase)
    hp = _raid_hp(raid, at, raid_config["regen_per_minute"])
    if user_id is None:
        available, party_ids = [], []
    else:
        rows = (await s.scalars(select(Kombucha).where(
            Kombucha.user_id == user_id, Kombucha.alive.is_(True), Kombucha.frozen.is_(False)
        ).order_by(Kombucha.id))).all()
        event_window = halloween.decay_window(config)
        for k in rows:
            kb.tick(k, at, halloween_window=event_window)
        available = [k for k in rows if k.alive and not k.frozen]
        available_ids = {k.id for k in available}
        saved = [kid for kid in (player.kombucha_ids or [])
                 if isinstance(kid, int) and not isinstance(kid, bool) and kid in available_ids] if player else []
        party_ids = saved or ([available[0].id] if available else [])
    standings = await halloween_raid.leaderboard(s, user_id, player)
    return {
        "active": True,
        "event_key": halloween_raid.event_key(config),
        "boss": raid_config["boss_name"],
        "stage_title": stage["title"],
        "stage_description": stage["description"],
        "stage_number": stage_number,
        "stage_count": len(raid_config["stages"]),
        "hp": hp,
        "max_hp": raid.max_hp,
        "phase": raid.phase,
        "total_damage": raid.total_damage,
        "my_damage": player.damage if player else 0,
        "my_rank": standings["my_rank"],
        "participants": standings["participants"],
        "leaderboard": standings["leaderboard"],
        "stage_damage": _stage_damage(player, raid.phase),
        "regen_per_minute": raid_config["regen_per_minute"],
        "stage_gifts": [gift for gift in raid_config["gifts"] if gift["stage"] == stage_number],
        "gifts_received": [entry for entry in (player.gifts_received or [])
                           if isinstance(entry, dict) and entry.get("reward_type") == "badge"] if player else [],
        "party_ids": party_ids,
        "available_mushrooms": [_mushroom_out(k) for k in available],
    }


async def _award_stage_gifts(s, raid_config: dict, stage_number: int, phase: int,
                             at: datetime, season_key: str) -> None:
    """Grant configured personal raid badges as soon as contributors reach the threshold."""
    badges = [gift for gift in raid_config["gifts"] if gift["stage"] == stage_number]
    if not badges:
        return
    players = (await s.scalars(select(HalloweenRaidPlayer).with_for_update())).all()
    for participant in players:
        damage = _stage_damage(participant, phase)
        if not damage:
            continue
        received = list(participant.gifts_received or [])
        received_keys = {
            (str(item.get("event_key") or season_key), str(item.get("id") or ""))
            for item in received if isinstance(item, dict) and item.get("reward_type") == "badge"
        }
        for badge in badges:
            reward_key = (season_key, badge["id"])
            if damage < badge["required_damage"] or reward_key in received_keys:
                continue
            recipient = await s.get(User, participant.user_id, with_for_update=True)
            if recipient is None:
                continue
            badge_code = halloween.reward_code(season_key, badge["id"])
            entry = {**badge, "event_key": season_key, "received_at": at.isoformat(),
                     "phase": phase, "damage": damage, "badge_code": badge_code}
            from ..services.gamification import award_custom_raid_badge
            await award_custom_raid_badge(s, recipient.id, badge_code, badge["title"],
                                          badge["emoji"], badge["description"], at)
            received.append(entry)
            received_keys.add(reward_key)
            body = f"{badge['emoji']} Получен бейдж «{badge['title']}» за вклад в рейд."
            key = f"halloween_raid_badge:{badge_code}:{participant.user_id}"
            await enqueue_push(s, participant.user_id, "halloween", "Новое достижение рейда 🏅",
                               body, "/events", key)
        participant.gifts_received = received


@bp.get("/events/state")
async def event_state():
    at = datetime.now(UTC)
    uid = current_user_id()
    async with session_scope() as s:
        config = await halloween.get_config(s)
        user = await s.get(User, uid) if uid else None
        state = halloween.public_state(config, user, at)
        player = await s.get(HalloweenRaidPlayer, uid) if uid else None
        state["raid_gifts"] = [entry for entry in (player.gifts_received or [])
                               if isinstance(entry, dict) and entry.get("reward_type") == "badge"] if player else []
        if state["active"]:
            if user:
                await halloween.award_survivor(s, user.id)
        else:
            state["raid_summary"] = await halloween_raid.inactive_summary(s, config, at)
    return state


@bp.get("/events/halloween/raid")
async def halloween_raid_state():
    """Public read-only state of the one shared raid boss during the active event."""
    at = datetime.now(UTC)
    uid = current_user_id()
    async with session_scope() as s:
        config = await halloween.get_config(s)
        if not halloween.active(config, at):
            return {"active": False, "summary": await halloween_raid.inactive_summary(s, config, at)}
        raid_config = halloween.normalize_raid_config(config.get("raid"))
        initial_stage, _ = halloween.stage_for({"raid": raid_config}, 1)
        raid = await _ensure_raid(s, initial_stage["max_hp"], lock=False)
        player = await s.get(HalloweenRaidPlayer, uid) if uid else None
        return await _raid_state(s, raid, player, config, at, uid)


@bp.get("/events/halloween/archive")
async def halloween_raid_archive():
    """Public immutable history, medals, and all-time records for completed raids."""
    async with session_scope() as s:
        return await halloween_raid.archive_index(s)


@bp.post("/events/halloween/raid/tap")
@require_any_perm("kombucha.play", "role.assign")
async def halloween_raid_tap():
    at = datetime.now(UTC)
    data = json_body()
    async with session_scope() as s:
        config = await halloween.get_config(s, lock=True)
        if not halloween.active(config, at):
            raise ApiError("Хэллоуинский рейд сейчас закрыт", 409, "event_inactive")
        await halloween_raid.ensure_event_meta(s, config, lock=True)
        user = await s.get(User, g.user.id, with_for_update=True)
        await s.execute(insert(HalloweenRaidPlayer).values(
            user_id=user.id, damage=0, kombucha_ids=[], stage_damage={}, gifts_received=[]
        ).on_conflict_do_nothing(index_elements=["user_id"]))
        player = await s.scalar(select(HalloweenRaidPlayer).where(
            HalloweenRaidPlayer.user_id == user.id).with_for_update())
        if player.last_tap_at and at - player.last_tap_at < RAID_TAP_COOLDOWN:
            left = max(0.05, (RAID_TAP_COOLDOWN - (at - player.last_tap_at)).total_seconds())
            raise ApiError("Подожди секунду, грибам нужно перевести дух", 429,
                           "raid_too_fast", retry_after=left)

        raw_ids = data.get("kombucha_ids", player.kombucha_ids or [])
        if not raw_ids:
            first = await s.scalar(select(Kombucha.id).where(
                Kombucha.user_id == user.id, Kombucha.alive.is_(True), Kombucha.frozen.is_(False)
            ).order_by(Kombucha.id).limit(1))
            raw_ids = [first] if first else []
        if (not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 3
                or any(isinstance(kid, bool) or not isinstance(kid, int) for kid in raw_ids)
                or len(set(raw_ids)) != len(raw_ids)):
            raise ApiError("Выставь от одного до трёх разных грибов", 400, "invalid_raid_team")
        fighters = (await s.scalars(select(Kombucha).where(
            Kombucha.user_id == user.id, Kombucha.id.in_(raw_ids),
            Kombucha.alive.is_(True), Kombucha.frozen.is_(False)
        ).order_by(Kombucha.id).with_for_update())).all()
        if len(fighters) != len(raw_ids):
            raise ApiError("В команду можно поставить только своих живых и незамороженных грибов",
                           409, "invalid_raid_team")
        event_window = halloween.decay_window(config)
        for k in fighters:
            kb.tick(k, at, halloween_window=event_window)
            if not k.alive:
                raise ApiError(f"Гриб «{k.name}» уже закис — замени его в команде", 409, "raid_mushroom_dead")

        raid_config = halloween.normalize_raid_config(config.get("raid"))
        initial_stage, _ = halloween.stage_for({"raid": raid_config}, 1)
        raid = await _ensure_raid(s, initial_stage["max_hp"])
        stage, stage_number = halloween.stage_for({"raid": raid_config}, raid.phase)
        configured_hp = stage["max_hp"]
        if raid.max_hp != configured_hp:
            old_max = max(raid.max_hp, 1)
            raid.hp = max(1, min(configured_hp, round(raid.hp * configured_hp / old_max)))
            raid.max_hp = configured_hp
            raid.updated_at = at

        regen_rate = raid_config["regen_per_minute"] / 60
        if raid.hp < raid.max_hp and regen_rate > 0:
            elapsed = max(0.0, (at - raid.updated_at).total_seconds())
            regen = int(elapsed * regen_rate)
            if regen:
                raid.hp = min(raid.max_hp, raid.hp + regen)
                raid.updated_at += timedelta(seconds=regen / regen_rate)
            if raid.hp == raid.max_hp:
                raid.updated_at = at
        else:
            raid.updated_at = at

        phase = raid.phase
        damage = len(fighters)
        for k in fighters:
            for stat, delta in RAID_STAT_DELTA.items():
                setattr(k, stat, max(0.0, min(100.0, getattr(k, stat) + delta)))
            if all(getattr(k, stat) > 0 for stat in kb.STATS):
                k.zero_since = None
            elif k.zero_since is None:
                k.zero_since = at
        player.kombucha_ids = list(raw_ids)
        first_contribution = player.damage <= 0
        stage_damage = dict(player.stage_damage or {})
        stage_damage[str(phase)] = _stage_damage(player, phase) + damage
        player.stage_damage = stage_damage
        player.damage += damage
        if first_contribution:
            from ..services.gamification import award
            await award(s, user.id, "raid_contributor")
        player.last_tap_at = at
        raid.hp = max(0, raid.hp - damage)
        raid.total_damage += damage
        defeated = raid.hp <= 0
        message = None
        await _award_stage_gifts(s, raid_config, stage_number, phase, at, halloween_raid.event_key(config))
        if defeated:
            raid.phase += 1
            next_stage, _ = halloween.stage_for({"raid": raid_config}, raid.phase)
            raid.max_hp = next_stage["max_hp"]
            raid.hp = raid.max_hp
            raid.updated_at = at
            message = f"Стадия «{stage['title']}» пала — но впереди новая!"
        await halloween.award_survivor(s, user.id)
        result = await _raid_state(s, raid, player, config, at, user.id)
        result.update({"defeated": defeated, "damage_dealt": damage, "message": message,
                       "fighters": [_mushroom_out(k) for k in fighters]})
        return result


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
@require_any_perm("kombucha.play", "role.assign")
async def halloween_equip_hat(kid: int):
    data = json_body()
    code = data.get("code")
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        k = await s.get(Kombucha, kid, with_for_update=True)
        if k is None or k.user_id != user.id:
            raise ApiError("Гриб не найден", 404, "not_found")
        if code is not None and not isinstance(code, str):
            raise ApiError("Код шапки должен быть строкой", 400, "hat_not_owned")
        hat = halloween.hat_catalog(user).get(code) if code is not None else None
        if code is not None and (hat is None or code not in await halloween.inventory(user)):
            raise ApiError("Этой шапки пока нет в коллекции", 400, "hat_not_owned")
        k.halloween_hat = code
        k.halloween_hat_meta = ({"code": code, "title": hat["title"], "emoji": hat["emoji"],
                                 "description": hat.get("description", "")}
                                if hat else None)
        await s.flush()
        return {"kombucha": kb.out(k), "owned_hats": await halloween.inventory(user)}
