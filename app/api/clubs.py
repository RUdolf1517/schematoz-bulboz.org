"""API грибных кооперативов и Гриб-Танка.

Права внутри клуба — свой декоратор `club_role_required("leader", "deputy")`:
он поднимает клуб и участие из БД и кладёт их в g, чтобы вьюха не искала их заново.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import g, request
from sqlalchemy import func, select

from ..auth.rbac import get_user_perms, login_required
from ..auth.sessions import current_user_id
from ..db import session_scope
from ..errors import ApiError
from ..models import Club, ClubMember, ClubPost, ClubReaction, ClubJoinRequest, ClubInvite, ClubMembershipCooldown
from ..services import club_events, club_tank, clubs, leagues
from ..services.antispam import hit_rate
from ..services.captcha import captcha_required
from . import bp
from .utils import json_body

MSK = timezone(timedelta(hours=3))


def club_role_required(*roles: str):
    """Доступ только участнику клуба (и, если указано, с одной из ролей)."""
    def deco(view):
        async def wrapper(tag: str, *args, **kwargs):
            async with session_scope() as s:
                club = await clubs.by_tag(s, tag)
                member = await s.get(ClubMember, (club.id, g.user.id))
                if member is None:
                    raise ApiError("Ты не в этом кооперативе", 403, "club_role")
                if roles and member.role not in roles:
                    raise ApiError("Недостаточно прав в клубе", 403, "club_role")
                g.club, g.club_member = club, member
                return await view(s, club, member, *args, **kwargs)
        wrapper.__name__ = getattr(view, "__name__", "wrapper")
        return login_required(wrapper)
    return deco


async def _club_payload(s, club: Club, viewer_id: int | None = None) -> dict:
    data = await clubs.public_out(s, club, viewer_id=viewer_id)
    tank = await club_tank.ensure_tank(s, club)
    data["tank"]["raid"] = await club_events.raid_state(s, club)
    data["tank"]["war"] = await club_events.war_state(s, club)
    data["tank"]["league"] = await leagues.board(s, club)
    return data


# ---------------------------------------------------------------- список, создание, моё
@bp.get("/clubs")
async def clubs_list():
    q = (request.args.get("q") or "").strip().lower()
    async with session_scope() as s:
        stmt = select(Club).where(Club.status == "active")
        if q:
            stmt = stmt.where(func.lower(Club.name).like(f"%{q}%") | func.lower(Club.tag).like(f"%{q}%"))
        rows = (await s.scalars(stmt.order_by(Club.xp.desc()).limit(50))).all()
        items = []
        for club in rows:
            tank = await club_tank.ensure_tank(s, club)
            items.append({"id": club.id, "name": club.name, "tag": club.tag, "emblem": club.emblem,
                          "color": club.color, "color2": club.color2, "members": club.members,
                          "capacity": club.capacity, "join_mode": club.join_mode, "level": club.level,
                          "stage": club_tank.stage_for(tank.xp)["size"],
                          "stage_title": club_tank.stage_for(tank.xp)["title"],
                          "min_level": club.min_level})
        return {"items": items, "museum": (await clubs.museum(s))[:12],
                "mine": await _mine_block(s, current_user_id())}


async def _mine_block(s, user_id: int | None) -> dict | None:
    if user_id is None:
        return None
    club, member = await clubs.my_club(s, user_id)
    if club is None:
        cd = await s.get(ClubMembershipCooldown, user_id)
        return {"club": None, "cooldown_until": cd.until.isoformat() if cd and cd.until > datetime.now(timezone.utc) else None}
    tank = await club_tank.ensure_tank(s, club)
    st = club_tank.stage_for(tank.xp)
    return {"club": {"id": club.id, "name": club.name, "tag": club.tag, "emblem": club.emblem,
                     "color": club.color, "color2": club.color2, "role": member.role,
                     "account": club.account, "level": club.level, "members": club.members},
            "tank": {"stage": st["size"], "stage_title": st["title"], "mood": club_tank.mood(tank),
                     "hp": round(tank.hp), "mold": tank.mold},
            "perks": clubs.perks({}, club.level, st["size"], clubs.active_preps(club)),
            "cooldown_until": None}


@bp.get("/clubs/mine")
@login_required
async def clubs_mine():
    async with session_scope() as s:
        return await _mine_block(s, g.user.id)


@bp.post("/clubs")
@login_required
@captcha_required()
async def clubs_create():
    data = json_body()
    # Администраторы основывают кооперативы бесплатно (право clubs.manage).
    free = "clubs.manage" in await get_user_perms(g.user.id)
    async with session_scope() as s:
        club, tank = await clubs.create(s, g.user, data, free=free)
        return {"club": await clubs.public_out(s, club), "free": free}, 201


@bp.get("/clubs/museum")
async def clubs_museum():
    async with session_scope() as s:
        return {"items": await clubs.museum(s)}


@bp.get("/clubs/<tag>")
async def club_get(tag: str):
    async with session_scope() as s:
        club = await clubs.by_tag(s, tag)
        uid = current_user_id()
        data = await _club_payload(s, club, viewer_id=uid)
        mine = await s.get(ClubMember, (club.id, uid)) if uid else None
        data["me"] = {"member": bool(mine), "role": mine.role if mine else None}
        data["board"] = await clubs.board(s, club) if (club.settings or {}).get("show_board", True) else []
        data["beauty"] = await leagues.beauty_board(s)
        return data


@bp.post("/clubs/dev/grant")
@login_required
async def clubs_dev_grant():
    """Демо-пополнение кошелька для e2e/превью: в проде (без DEMO_MODE) роут отвечает 404."""
    from flask import current_app

    if not current_app.config.get("DEMO_MODE"):
        raise ApiError("Не найдено", 404, "not_found")
    from ..services import wood

    data = json_body()
    amount = max(1, min(int(data.get("amount") or 1000), 10000))
    async with session_scope() as s:
        await wood.demo_grant(s, g.user.id, amount, f"e2e:{datetime.now(timezone.utc).timestamp()}")
        return {"ok": True, "wood": await wood.balance(s, g.user.id), "amount": amount}


@bp.post("/clubs/dev/reset")
@login_required
async def clubs_dev_reset():
    """Только DEMO_MODE: снять участие в клубе и кулдаун выхода — чтобы e2e можно было гонять повторно."""
    from flask import current_app

    if not current_app.config.get("DEMO_MODE"):
        raise ApiError("Не найдено", 404, "not_found")
    async with session_scope() as s:
        member = await s.scalar(select(ClubMember).where(ClubMember.user_id == g.user.id))
        if member is not None:
            await s.delete(member)
        cd = await s.get(ClubMembershipCooldown, g.user.id)
        if cd is not None:
            await s.delete(cd)
        return {"ok": True}


# ---------------------------------------------------------------- вступление/выход/роли
@bp.post("/clubs/<tag>/join")
@login_required
@captcha_required()
async def club_join(tag: str):
    data = json_body()
    async with session_scope() as s:
        club = await clubs.by_tag(s, tag)
        state, member = await clubs.join(s, g.user, club, invite_code=data.get("invite"),
                                         message=data.get("message"), ip_hash=clubs.ip_key())
        if state == "requested":
            return {"state": "requested"}
        return {"state": "joined", "club": await clubs.public_out(s, club, viewer_id=g.user.id)}, 201


@bp.post("/clubs/<tag>/leave")
@club_role_required()
async def club_leave(s, club, member):
    await clubs.leave(s, g.user, club, member)
    return {"ok": True}


@bp.get("/clubs/<tag>/requests")
@club_role_required("leader", "deputy")
async def club_requests(s, club, member):
    rows = (await s.scalars(select(ClubJoinRequest).where(ClubJoinRequest.club_id == club.id,
                                                        ClubJoinRequest.status == "pending")
                            .order_by(ClubJoinRequest.created_at))).all()
    from ..models import User
    users = {u.id: u.username for u in (await s.scalars(select(User).where(
        User.id.in_([r.user_id for r in rows] or [0])))).all()}
    return {"items": [{"id": r.id, "user_id": r.user_id, "username": users.get(r.user_id, "?"),
                       "message": r.message, "created_at": r.created_at.isoformat()} for r in rows]}


@bp.post("/clubs/<tag>/requests/<int:rid>")
@club_role_required("leader", "deputy")
async def club_request_decide(s, club, member, rid: int):
    approve = bool(json_body().get("approve"))
    await clubs.decide_request(s, member, club, rid, approve)
    return {"ok": True, "approved": approve}


@bp.post("/clubs/<tag>/invites")
@club_role_required("leader", "deputy")
async def club_invite(s, club, member):
    data = json_body()
    inv = await clubs.invite(s, member, club, max_uses=int(data.get("max_uses") or 1),
                             hours=int(data.get("hours") or 72))
    return {"code": inv.code, "url": f"/c/{club.tag}?invite={inv.code}", "max_uses": inv.max_uses}, 201


@bp.patch("/clubs/<tag>/members/<int:uid>")
@club_role_required("leader")
async def club_set_role(s, club, member, uid: int):
    role = json_body().get("role")
    target = await s.get(ClubMember, (club.id, uid))
    if target is None:
        raise ApiError("Участник не найден", 404, "club_member_not_found")
    await clubs.set_role(s, club, target, role, actor=g.user)
    return {"ok": True, "role": role}


@bp.delete("/clubs/<tag>/members/<int:uid>")
@club_role_required("leader", "deputy")
async def club_kick(s, club, member, uid: int):
    target = await s.get(ClubMember, (club.id, uid))
    if target is None:
        raise ApiError("Участник не найден", 404, "club_member_not_found")
    await clubs.kick(s, member, target, club, reason=request.args.get("reason"),
                     ban=request.args.get("ban") == "1")
    return {"ok": True}


# ---------------------------------------------------------------- Танк
@bp.post("/clubs/<tag>/tank/<action>")
@captcha_required()
@club_role_required()
async def tank_action(s, club, member, action: str):
    json_body()
    if hit_rate("club_care", f"u:{g.user.id}", 30, 60):
        raise ApiError("Танк устал: слишком много действий подряд", 429, "rate_limited")
    tank = await club_tank.ensure_tank(s, club)
    res = await club_tank.act(s, g.user, club, tank, action, ip_hash=clubs.ip_key())
    await clubs.refresh_perks(s, club, tank)
    res["tank"] = await club_tank.out(s, club, tank, viewer_id=g.user.id)
    res["club"] = await clubs.public_out(s, club)
    if action in ("sugar", "tea", "clean", "pet"):
        await club_events.raid_damage(s, g.user, club, club_events.RAID_DAMAGE_CARE, f"care:{action}")
    return res


@bp.post("/clubs/<tag>/tank/help")
@club_role_required()
async def tank_help(s, club, member):
    tank = await club_tank.ensure_tank(s, club)
    sent = await clubs.call_help(s, g.user, club, tank)
    return {"ok": True, "sent": sent}


@bp.post("/clubs/<tag>/tank/halloween")
@club_role_required()
async def tank_halloween(s, club, member):
    tank = await club_tank.ensure_tank(s, club)
    return await club_events.halloween_tank_attack(s, club, tank)


# ---------------------------------------------------------------- копилка и апгрейды
@bp.get("/clubs/<tag>/bank")
@club_role_required()
async def club_bank(s, club, member):
    from ..models import ClubBankTx, User
    rows = (await s.scalars(select(ClubBankTx).where(ClubBankTx.club_id == club.id)
                            .order_by(ClubBankTx.id.desc()).limit(50))).all()
    users = {u.id: u.username for u in (await s.scalars(select(User).where(
        User.id.in_([r.user_id for r in rows if r.user_id])))).all()}
    return {"account": club.account, "min_deposit": clubs.MIN_DEPOSIT,
            "capacity": club.capacity, "level": club.level,
            "upgrades": [{"kind": "capacity", "title": f"Мест до {cap}", "price": price,
                          "available": cap > club.capacity}
                         for cap, price in clubs.CAPACITY_STEPS if cap > 5] +
                        [{"kind": "level", "title": f"Уровень клуба {club.level + 1}", "price": 250 * club.level,
                          "available": True},
                         {"kind": "streak_freeze", "title": "Заморозка стрика (раз в неделю)",
                          "price": clubs.STREAK_FREEZE_COST,
                          "available": (club.settings or {}).get("freeze_week") != clubs.week_key()}],
            "items": [{"id": r.id, "user": users.get(r.user_id), "delta": r.delta, "reason": r.reason,
                       "reason_title": clubs.BANK_TITLES.get(r.reason, r.reason),
                       "balance_after": r.balance_after, "at": r.created_at.isoformat()} for r in rows]}


@bp.post("/clubs/<tag>/bank")
@club_role_required()
async def club_deposit(s, club, member):
    amount = int(json_body().get("amount") or 0)
    account = await clubs.deposit(s, g.user, club, amount)
    return {"account": account}


@bp.post("/clubs/<tag>/upgrades")
@club_role_required("leader", "deputy")
async def club_upgrade(s, club, member):
    kind = json_body().get("kind")
    return await clubs.upgrade(s, member, club, kind)


# ---------------------------------------------------------------- лента
@bp.get("/clubs/<tag>/feed")
@club_role_required()
async def club_feed(s, club, member):
    from ..models import User
    rows = (await s.scalars(select(ClubPost).where(ClubPost.club_id == club.id, ClubPost.deleted_at.is_(None))
                            .order_by(ClubPost.id.desc()).limit(50))).all()
    reactions = (await s.execute(select(ClubReaction.post_id, ClubReaction.emoji, func.count(ClubReaction.id))
                                 .where(ClubReaction.post_id.in_([r.id for r in rows] or [0]))
                                 .group_by(ClubReaction.post_id, ClubReaction.emoji))).all()
    users = {u.id: u.username for u in (await s.scalars(select(User).where(
        User.id.in_([r.user_id for r in rows if r.user_id])))).all()}
    by_post: dict[int, dict[str, int]] = {}
    for pid, emoji, n in reactions:
        by_post.setdefault(pid, {})[emoji] = n
    return {"items": [{"id": r.id, "user_id": r.user_id, "username": users.get(r.user_id),
                       "kind": r.kind, "event": r.event, "body": r.body, "emoji": r.emoji,
                       "at": r.created_at.isoformat(), "reactions": by_post.get(r.id, {}),
                       "can_delete": member.role in ("leader", "deputy") or r.user_id == member.user_id}
                      for r in rows],
            "show_board": (club.settings or {}).get("show_board", True)}


@bp.post("/clubs/<tag>/feed")
@captcha_required()
@club_role_required()
async def club_post(s, club, member):
    p = await clubs.post(s, member, club, json_body().get("body"))
    return {"ok": True, "id": p.id}, 201


@bp.delete("/clubs/<tag>/feed/<int:pid>")
@club_role_required()
async def club_post_delete(s, club, member, pid: int):
    await clubs.delete_post(s, member, club, pid)
    return {"ok": True}


@bp.post("/clubs/<tag>/feed/<int:pid>/react")
@club_role_required()
async def club_post_react(s, club, member, pid: int):
    await clubs.react(s, member, club, pid, json_body().get("emoji"))
    return {"ok": True}


@bp.post("/clubs/<tag>/feed/<int:pid>/report")
@club_role_required()
async def club_post_report(s, club, member, pid: int):
    r = await clubs.report(s, club, g.user.id, pid, json_body().get("reason"))
    return {"ok": True, "id": r.id}, 201


@bp.post("/clubs/<tag>/settings")
@club_role_required("leader", "deputy")
async def club_settings(s, club, member):
    data = json_body()
    if "show_board" in data:
        club.settings = {**(club.settings or {}), "show_board": bool(data["show_board"])}
    if "description" in data:
        club.description = str(data["description"])[:280]
    if "join_mode" in data and data["join_mode"] in ("open", "request", "invite"):
        club.join_mode = data["join_mode"]
    if "min_level" in data:
        club.min_level = max(1, min(int(data["min_level"] or 1), 50))
    return {"ok": True}


# ---------------------------------------------------------------- лаборатория
@bp.post("/clubs/<tag>/lab/drain")
@captcha_required()
@club_role_required()
async def club_lab_drain(s, club, member):
    data = json_body()
    run = await clubs.lab_drain(s, g.user, club, int(data.get("kombucha_id") or 0), data.get("kind"))
    return {"ok": True, "id": run.id, "ready_at": run.ready_at.isoformat(), "stat": run.stat,
            "kind": run.kind}


@bp.post("/clubs/<tag>/lab/collect/<int:run_id>")
@club_role_required()
async def club_lab_collect(s, club, member, run_id: int):
    prep = await clubs.lab_collect(s, club, run_id, g.user.id)
    return {"ok": True, "prep": prep}


@bp.post("/clubs/<tag>/lab/craft")
@captcha_required()
@club_role_required()
async def club_lab_craft(s, club, member):
    data = json_body()
    code = await clubs_craft(s, club, g.user, data.get("mushroom_ids") or [], data.get("stage"))
    return {"ok": True, "code": code}, 201


async def clubs_craft(s, club: Club, user, mushroom_ids: list[int], stage: int | None) -> str:
    """Крафт боевой мутации Танка: 3 гриба клуба отдают мутации одной стадии."""
    from ..models import Kombucha, ClubLabCraft, ClubTankMutation
    from ..services import club_tank_mutations as muts
    ids = list(dict.fromkeys(int(x) for x in mushroom_ids))[:3]
    if len(ids) < 3:
        raise ApiError("Нужно выложить три гриба", 400, "validation_error", field="mushroom_ids")
    members = {m.user_id for m in (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id))).all()}
    rows = (await s.scalars(select(Kombucha).where(Kombucha.id.in_(ids)))).all()
    if len(rows) < 3:
        raise ApiError("Грибы не найдены", 404, "kombucha_not_found")
    for k in rows:
        if k.user_id not in members:
            raise ApiError("Гриб не из нашего клуба", 403, "club_foreign")
        if k.frozen:
            raise ApiError("Замороженный гриб в лабораторию не берут", 409, "club_frozen")
    codes = [m["code"] if isinstance(m, dict) else m for k in rows for m in (k.mutations or [])]
    stages = {muts.BY_CODE[c].stage for c in codes if c in muts.BY_CODE}
    picked_stage = int(stage) if stage else (sorted(stages)[-1] if stages else 1)
    have = {r.stage for r in (await s.scalars(select(ClubTankMutation).where(
        ClubTankMutation.club_id == club.id))).all()}
    if picked_stage in have:
        raise ApiError("Мутация этого уровня уже разработана", 409, "club_mut_exists")
    pool = [m for m in muts.for_stage(picked_stage)]
    if not pool:
        raise ApiError("Неизвестная стадия мутации", 400, "validation_error", field="stage")
    pick = pool[len(codes) % len(pool)]
    whole: list[str] = []
    for k in rows:
        for m in (k.mutations or []):
            whole.append(m["code"] if isinstance(m, dict) else str(m))
    from ..services import kombucha as kb
    await kb.strip_mutations(s, rows, whole)
    s.add(ClubTankMutation(club_id=club.id, code=pick.code, stage=pick.stage, crafted_by=user.id))
    s.add(ClubLabCraft(club_id=club.id, user_id=user.id, code=pick.code, mushroom_ids=ids))
    clubs._feed(s, club.id, user.id, "lab", f"🧬 Лаборатория собрала мутацию «{pick.title}» (стадия {pick.stage})!")
    tank = await club_tank.ensure_tank(s, club)
    await clubs.refresh_perks(s, club, tank)
    return pick.code


# ---------------------------------------------------------------- события, войны, лига, конкурс
@bp.get("/clubs/<tag>/events")
@club_role_required()
async def club_events_state(s, club, member):
    return {"raid": await club_events.raid_state(s, club),
            "world": await club_events.active_world(s),
            "war": await club_events.war_state(s, club)}


@bp.post("/clubs/<tag>/events/raid/start")
@club_role_required("leader", "deputy")
async def club_raid_start(s, club, member):
    raid = await club_events.start_raid(s, club, force=True)
    return {"ok": True, "id": raid.id, "hp": raid.hp,
            "ends_at": raid.ends_at.isoformat() if raid.ends_at else None}


@bp.post("/clubs/<tag>/war/team")
@club_role_required("leader")
async def club_war_team(s, club, member):
    data = json_body()
    war = await club_events.pick_team(s, member, club, data.get("mushroom_ids") or [],
                                      include_tank=bool(data.get("include_tank", True)))
    return {"ok": True, "war_id": war.id}


@bp.get("/clubs/<tag>/league")
@club_role_required()
async def club_league(s, club, member):
    return await leagues.board(s, club)


@bp.get("/clubs/<tag>/beauty")
@club_role_required()
async def club_beauty(s, club, member):
    return {"items": await leagues.beauty_board(s), "week": leagues.week_key()}


@bp.post("/clubs/<tag>/beauty")
@club_role_required()
async def club_beauty_vote(s, club, member):
    target = int(json_body().get("club_id") or 0)
    await leagues.vote_beauty(s, g.user.id, club, target)
    return {"ok": True, "target": target}
