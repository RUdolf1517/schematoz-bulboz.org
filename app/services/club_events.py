"""Клубные события: рейд «Великая плесень», мировые ивенты и бизнес-войны.

* Рейд — раз в месяц на 48 ч. Урон боссу наносят уход за личными грибами и мини-игры участников
  (дневной потолок на человека). Победа → редкая мутация Танку и бейдж «Плеснебой» стартовому
  составу клуба; поражение → шрам. Бизнес-война: победа → бейдж «Гроза конкурентов», поражение → шрам.
* Мировые ивенты («Нашествие мушек», «Сахарный кризис», «Чайная ночь», сезонный Хэллоуин)
  включает админ: они меняют скорость падения показателей и требования к уходу.
  Во время Хэллоуина Танк может встать в атакующую группу, но теряет здоровье — урон зависит от мутаций.
* Бизнес-войны — неделя, автоподбор клубов похожего уровня (одна лига). Состав атаки выбирает
  глава (SEO): 5 грибов последней стадии от участников + Танк. Обычные грибы бьют по 1 HP и получают
  дебаф «Раненый», Танк — от 5 урона, зависит от мутаций.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import (Club, ClubEventProgress, ClubMember, ClubPost, ClubTank, ClubTankMutation, ClubWar, Kombucha,
                      Setting, User)
from . import club_tank as tank_svc
from . import club_tank_mutations as muts
from . import notifications

MSK = timezone(timedelta(hours=3))
rng = random.Random()

RAID_HOURS = 48
RAID_BOSS_BASE = 120          # + 90 за каждого участника
RAID_BOSS_PER_MEMBER = 90
RAID_DAILY_CAP = 150          # потолок урона в день на человека
RAID_DAMAGE_CARE = 3          # урон за уход за личным грибом
RAID_DAMAGE_GAME = 5          # урон за мини-игру
RAID_MUT_CHANCE = 0.5         # шанс редкой мутации Танку за победу
WORLD_DECAY = {"flies": {"clean": 1.4}, "sugar_crisis": {"sweet": 1.5}, "tea_night": {"happy": 1.3}}
WAR_PICK_MAX = 5
WAR_TANK_MIN_DAMAGE = 5
WAR_WOUND_DAYS = 3            # дебаф «Раненый» после войны
WORLD_EVENTS = ("flies", "sugar_crisis", "tea_night", "halloween")
WORLD_TITLES = {"flies": "Нашествие мушек", "sugar_crisis": "Сахарный кризис",
                "tea_night": "Чайная ночь", "halloween": "Хэллоуин"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def week_key(at: datetime | None = None) -> str:
    iso = (at or now()).astimezone(MSK).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _feed(s: AsyncSession, club_id: int, user_id: int | None, event: str, body: str, emoji: str = "📝", **data):
    s.add(ClubPost(club_id=club_id, user_id=user_id, kind="auto", event=event, body=body[:280], emoji=emoji,
                   data=data))


# ---------------------------------------------------------------- мировые ивенты (админка)
DEFAULT_WORLD = {"enabled": False, "events": {}, "raid": {"enabled": False, "start_at": None, "end_at": None}}


async def config(s: AsyncSession) -> dict:
    row = await s.get(Setting, "world_events")
    value = dict(DEFAULT_WORLD)
    if row and isinstance(row.value, dict):
        value.update(row.value)
    return value


def validate_config(data: dict) -> dict:
    out = {**DEFAULT_WORLD, **(data or {})}
    events = {}
    for code, cfg in (out.get("events") or {}).items():
        if code not in WORLD_EVENTS:
            raise ApiError(f"Неизвестный ивент: {code}", 400, "validation_error", field="events")
        events[code] = {"enabled": bool(cfg.get("enabled")), "start_at": cfg.get("start_at"), "end_at": cfg.get("end_at"),
                        "mult": float(cfg.get("mult") or 1.0)}
    out["events"] = events
    raid = out.get("raid") or {}
    out["raid"] = {"enabled": bool(raid.get("enabled")), "start_at": raid.get("start_at"), "end_at": raid.get("end_at")}
    return out


async def active_world(s: AsyncSession, at: datetime | None = None) -> dict:
    """Какие мировые ивенты идут прямо сейчас и как они множат падение показателей Танка."""
    at = at or now()
    cfg = await config(s)
    mult: dict[str, float] = {}
    active: list[str] = []
    for code, ev in (cfg.get("events") or {}).items():
        if not ev.get("enabled"):
            continue
        start, end = ev.get("start_at"), ev.get("end_at")
        if start and end:
            try:
                if not (datetime.fromisoformat(start) <= at <= datetime.fromisoformat(end)):
                    continue
            except ValueError:
                continue
        active.append(code)
        for stat, m in WORLD_DECAY.get(code, {}).items():
            mult[stat] = max(mult.get(stat, 1.0), m * float(ev.get("mult") or 1.0))
    return {"active": active, "mult": mult}


async def world_modifiers(s: AsyncSession, at: datetime | None = None) -> dict[str, float]:
    return (await active_world(s, at))["mult"]


def apply_world(stats: dict[str, float], mult: dict[str, float]) -> dict[str, float]:
    """Множители мировых ивентов: «Сахарный кризис» сушит сахар, «мушки» пачкают банку и т.д."""
    for stat, m in (mult or {}).items():
        if stat in stats:
            stats[stat] = round(stats[stat] * m, 3)
    return stats


# ---------------------------------------------------------------- рейд «Великая плесень»
async def start_raid(s: AsyncSession, club: Club, at: datetime | None = None, force: bool = False) -> ClubEventProgress:
    at = at or now()
    ref = at.strftime("%Y-%m")
    existing = await s.scalar(select(ClubEventProgress).where(ClubEventProgress.club_id == club.id,
                                                              ClubEventProgress.kind == "raid",
                                                              ClubEventProgress.ref == ref))
    if existing is not None and not force:
        return existing
    hp = RAID_BOSS_BASE + RAID_BOSS_PER_MEMBER * max(1, club.members)
    # Снапшот состава на старте: награды получают те, кто был в клубе в начале ивента.
    starters = list(await s.scalars(select(ClubMember.user_id).where(ClubMember.club_id == club.id)))
    raid = ClubEventProgress(club_id=club.id, kind="raid", ref=ref, hp=hp, hp_max=hp, state="running",
                             ends_at=at + timedelta(hours=RAID_HOURS),
                             data={"damage": {}, "members": [int(u) for u in starters]})
    s.add(raid)
    _feed(s, club.id, None, "raid", f"🦠 Рейд «Великая плесень»! У босса {hp} HP — бейте уходом и играми.", hp=hp)
    await tank_svc.notify_club(s, club.id, "club", tag=club.tag, hp=hp)
    return raid


async def raid_state(s: AsyncSession, club: Club) -> dict | None:
    raid = await s.scalar(select(ClubEventProgress).where(ClubEventProgress.club_id == club.id,
                                                          ClubEventProgress.kind == "raid")
                          .order_by(ClubEventProgress.id.desc()))
    if raid is None:
        return None
    return {"id": raid.id, "hp": raid.hp, "hp_max": raid.hp_max, "state": raid.state,
            "ends_at": raid.ends_at.isoformat() if raid.ends_at else None,
            "damage": (raid.data or {}).get("damage", {})}


async def raid_damage(s: AsyncSession, user: User, club: Club, amount: int, ref: str) -> None:
    """Урон по боссу от ухода/игры. Дневной потолок на человека — RAID_DAILY_CAP."""
    raid = await s.scalar(select(ClubEventProgress).where(ClubEventProgress.club_id == club.id,
                                                          ClubEventProgress.kind == "raid",
                                                          ClubEventProgress.state == "running")
                          .order_by(ClubEventProgress.id.desc()).with_for_update())
    if raid is None:
        return
    at = now()
    if raid.ends_at and at > raid.ends_at:
        await _finish_raid(s, club, raid)
        return
    data = dict(raid.data or {})
    damage = dict(data.get("damage") or {})
    today = at.astimezone(MSK).date().isoformat()
    per_user = dict(damage.get("by_user") or {})
    if per_user.get(str(user.id), {}).get("day") != today:
        per_user[str(user.id)] = {"day": today, "total": 0}
    left = RAID_DAILY_CAP - per_user[str(user.id)]["total"]
    if left <= 0:
        return
    dealt = min(int(amount), left)
    per_user[str(user.id)]["total"] += dealt
    damage["by_user"] = per_user
    damage["total"] = damage.get("total", 0) + dealt
    data["damage"] = damage
    raid.data = data
    raid.hp = max(0, raid.hp - dealt)
    if raid.hp <= 0:
        await _finish_raid(s, club, raid, won=True)


async def _finish_raid(s: AsyncSession, club: Club, raid: ClubEventProgress, won: bool | None = None) -> None:
    if raid.state != "running":
        return
    won = (raid.hp <= 0) if won is None else won
    raid.state, raid.resolved_at = ("won" if won else "lost"), now()
    tank = await tank_svc.ensure_tank(s, club)
    if won:
        _feed(s, club.id, None, "raid", "🏆 Великая плесень побеждена! Танк получает редкую мутацию, "
                                        "стартовому составу — бейдж «Плеснебой».", won=True)
        stage = tank_svc.stage_for(tank.xp)["size"]
        have = {r.stage for r in (await s.scalars(select(ClubTankMutation).where(
            ClubTankMutation.club_id == club.id))).all()}
        pool = [m for m in muts.for_stage(stage) if m.stage not in have]
        if pool and rng.random() <= RAID_MUT_CHANCE + 0.5:      # победа — почти всегда награда
            pick = rng.choice(pool)
            s.add(ClubTankMutation(club_id=club.id, code=pick.code, stage=pick.stage))
        starters = [int(u) for u in ((raid.data or {}).get("members") or [])]
        await tank_svc.grant_badge_all(s, club, "club_raid_win", starters or None)
        for uid in (starters or [m.user_id for m in (await s.scalars(select(ClubMember).where(
                ClubMember.club_id == club.id))).all()]):
            notifications.notify(s, uid, "club", club_id=club.id, tag=club.tag)
    else:
        await tank_svc.add_scar(s, club, tank, "mold", "Рейд «Великая плесень»: босс оставил след")
        _feed(s, club.id, None, "raid", "💀 Рейд проигран. На Танке остался шрам.", won=False)
    await s.flush()


async def tick_raids(s: AsyncSession, at: datetime | None = None) -> int:
    """Идемпотентно: закрыть истёкшие рейды и, если включено в админке, начать месячный."""
    at = at or now()
    closed = 0
    running = (await s.scalars(select(ClubEventProgress).where(ClubEventProgress.kind == "raid",
                                                               ClubEventProgress.state == "running"))).all()
    for raid in running:
        if raid.ends_at and at > raid.ends_at:
            club = await s.get(Club, raid.club_id)
            if club is not None:
                await _finish_raid(s, club, raid)
                closed += 1
    cfg = await config(s)
    if cfg["raid"].get("enabled"):
        for club in (await s.scalars(select(Club).where(Club.status == "active"))).all():
            current = await s.scalar(select(ClubEventProgress).where(ClubEventProgress.club_id == club.id,
                                                                     ClubEventProgress.kind == "raid",
                                                                     ClubEventProgress.state == "running"))
            if current is None:
                await start_raid(s, club, at)
    return closed


# ---------------------------------------------------------------- Хэллоуин: Танк в атаке
async def halloween_tank_attack(s: AsyncSession, club: Club, tank: ClubTank) -> dict:
    """Танк бьёт по праздничной нечисти, теряя здоровье; урон зависит от боевых мутаций."""
    if not tank.alive:
        raise ApiError("Танк закис и не может атаковать", 409, "tank_dead")
    codes = await tank_svc.mutation_codes_async(s, club.id)
    dmg = muts.attack_damage(codes) * 2
    taken = max(1, dmg // 6)
    tank.hp = max(1.0, tank.hp - taken)
    tank.updated_at = now()
    return {"damage": dmg, "taken": taken, "hp": round(tank.hp), "mutations": sorted(codes)}


# ---------------------------------------------------------------- бизнес-войны
async def start_week(s: AsyncSession, week: str | None = None) -> int:
    """Автоподбор пар: клубы одной лиги, ближайшие по очкам. Идемпотентно на неделю."""
    from . import leagues
    week = week or week_key()
    await leagues.ensure_leagues(s)
    if await s.scalar(select(ClubWar.id).where(ClubWar.week_key == week)):
        return 0
    clubs = (await s.scalars(select(Club).where(Club.status == "active").order_by(Club.xp.desc()))).all()
    if len(clubs) < 2:
        return 0
    memberships = {m.club_id: m.league_code for m in (await s.scalars(
        select(leagues.LeagueMembership).where(leagues.LeagueMembership.week_key == week))).all()}
    by_league: dict[str, list[Club]] = {}
    for club in clubs:
        by_league.setdefault(memberships.get(club.id, "bronze"), []).append(club)
    made = 0
    for code, group in by_league.items():
        # пары «соседи по очкам»: 1-й со 2-м, 3-й с 4-м и т.д.
        for i in range(0, len(group) - 1, 2):
            a, b = group[i], group[i + 1]
            war = ClubWar(week_key=week, league_code=code, club_a_id=a.id, club_b_id=b.id,
                          ends_at=now() + timedelta(days=7))
            # Снапшот состава на старте войны — бейдж получат только участники того момента.
            snapshot = {}
            for club in (a, b):
                snapshot[str(club.id)] = [int(u) for u in await s.scalars(select(ClubMember.user_id).where(
                    ClubMember.club_id == club.id))]
            war.picks = {"__members__": snapshot}
            s.add(war)
            made += 1
            for club in (a, b):
                _feed(s, club.id, None, "war", f"⚔️ Бизнес-война недели: мы против «{b.name if club.id == a.id else a.name}»!", enemy_tag=b.tag if club.id == a.id else a.tag)
                for m in (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id))).all():
                    notifications.notify(s, m.user_id, "club", club_id=club.id,
                                         enemy_tag=b.tag if club.id == a.id else a.tag)
    await s.flush()
    return made


async def current_war(s: AsyncSession, club: Club) -> ClubWar | None:
    return await s.scalar(select(ClubWar).where(
        ClubWar.week_key == week_key(),
        ((ClubWar.club_a_id == club.id) | (ClubWar.club_b_id == club.id))))


async def pick_team(s: AsyncSession, actor: ClubMember, club: Club, mushroom_ids: list[int],
                    include_tank: bool = True) -> ClubWar:
    """Глава (SEO) выбирает атакующую группу: до 5 грибов последней стадии + Танк."""
    if actor.role != "leader":
        raise ApiError("Состав выбирает глава кооператива", 403, "club_role")
    war = await current_war(s, club)
    if war is None:
        raise ApiError("На этой неделе войны нет", 404, "club_war_not_found")
    ids = list(dict.fromkeys(int(x) for x in (mushroom_ids or [])))[:WAR_PICK_MAX]
    if ids:
        rows = (await s.scalars(select(Kombucha).where(Kombucha.id.in_(ids)))).all()
        members = {m.user_id for m in (await s.scalars(select(ClubMember).where(
            ClubMember.club_id == club.id))).all()}
        if len(rows) != len(ids):
            raise ApiError("Такого гриба нет", 404, "club_war_mushroom_missing")
        for k in rows:
            if k.user_id not in members:
                raise ApiError("Гриб не из нашего клуба", 403, "club_war_foreign")
            if tank_svc.stage_for(k.xp)["size"] < 6:
                raise ApiError(f"«{k.name}» ещё не дорос до последней стадии", 409, "club_war_stage")
    data = dict(war.picks or {})
    data[str(club.id)] = {"mushrooms": ids, "tank": bool(include_tank), "at": now().isoformat()}
    war.picks = data
    return war


async def settle_wars(s: AsyncSession, week: str) -> int:
    """Итог недели: взаимный урон, дебаф «Раненый» обычным грибам, шрам проигравшему клубу."""
    wars = (await s.scalars(select(ClubWar).where(ClubWar.week_key == week, ClubWar.state == "picking"))).all()
    done = 0
    for war in wars:
        a, b = await s.get(Club, war.club_a_id), await s.get(Club, war.club_b_id)
        if a is None or b is None:
            continue
        score_a = await _war_damage(s, a, war)
        score_b = await _war_damage(s, b, war)
        war.score_a, war.score_b = score_a, score_b
        war.winner_id = a.id if score_a >= score_b else b.id
        war.state, war.resolved_at = "resolved", now()
        winner = b if war.winner_id == a.id else a
        loser = a if war.winner_id == b.id else b
        snapshot = ((war.picks or {}).get("__members__") or {}).get(str(winner.id)) or []
        await tank_svc.grant_badge_all(s, winner, "club_war_win", snapshot or None)
        tank = await tank_svc.ensure_tank(s, loser)
        await tank_svc.add_scar(s, loser, tank, "war", f"Война недели {week}: поражение")
        _feed(s, a.id, None, "war", f"⚔️ Итог войны: {score_a} : {score_b} — "
                                   f"{'победа' if war.winner_id == a.id else 'поражение'}.")
        _feed(s, b.id, None, "war", f"⚔️ Итог войны: {score_b} : {score_a} — "
                                   f"{'победа' if war.winner_id == b.id else 'поражение'}.")
        done += 1
    return done


async def _war_damage(s: AsyncSession, club: Club, war: ClubWar) -> int:
    """Урон атакующей группы: танк (от 5, зависит от мутаций) + по 1 за обычный гриб."""
    pick = (war.picks or {}).get(str(club.id)) or {}
    tank = await tank_svc.ensure_tank(s, club)
    codes = await tank_svc.mutation_codes_async(s, club.id)
    score = max(WAR_TANK_MIN_DAMAGE, muts.attack_damage(codes)) if pick.get("tank", True) and tank.alive else 0
    ids = pick.get("mushrooms") or []
    if ids:
        rows = (await s.scalars(select(Kombucha).where(Kombucha.id.in_(ids)))).all()
        for k in rows:
            # Обычный гриб бьёт врага всего на 1 HP, а сам выходит из боя с дебафом «Раненый».
            k.hp = max(10.0, (k.hp if k.hp is not None else 100.0) - 25.0)
            k.wounded_until = now() + timedelta(days=WAR_WOUND_DAYS)
            score += 1
            _feed(s, club.id, k.user_id, "war", f"🩸 «{k.name}» сражался в войне и получил дебаф «Раненый».")
    tank.hp = max(1.0, tank.hp - 10) if pick.get("tank", True) else tank.hp
    return score


async def war_state(s: AsyncSession, club: Club) -> dict | None:
    war = await current_war(s, club)
    if war is None:
        return None
    enemy_id = war.club_b_id if war.club_a_id == club.id else war.club_a_id
    enemy = await s.get(Club, enemy_id)
    mine = (war.picks or {}).get(str(club.id)) or {}
    return {"id": war.id, "week": war.week_key, "state": war.state,
            "enemy": {"tag": enemy.tag, "name": enemy.name, "emblem": enemy.emblem} if enemy else None,
            "picked": {"mushrooms": mine.get("mushrooms", []), "tank": mine.get("tank", False)},
            "score_ours": war.score_a if war.club_a_id == club.id else war.score_b,
            "score_theirs": war.score_b if war.club_a_id == club.id else war.score_a,
            "winner": war.winner_id}
