"""Гриб-Танк — общая 20-литровая банка кооператива.

Живёт по законам личного гриба, но масштабнее и «лениво»: показатели хранятся на момент
updated_at, шаги убывания (раз в 12 ч) досчитываются при чтении — кронов на каждый шаг нет.
Отличия от личного гриба:
* пятый показатель — «Здоровье» (HP): от времени не падает, регенерирует от апгрейдов и лечится;
* падение сильнее и растёт с числом участников (PARTY_SCALE);
* вклад одного игрока в каждый показатель ограничен суточным потолком (TANK_DAILY_PER_STAT);
* плесень лечится только командой из TANK_CURE_MEMBERS разных участников;
* закисший Танк не возрождается — клуб получает мемориал в музее;
* боевые мутации дают урон/защиту за счёт ухода (club_tank_mutations.py).
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import Club, ClubDayStat, ClubMember, ClubPost, ClubTank, ClubTankMutation, User
from . import club_tank_mutations as muts
from . import notifications

rng = random.Random()
MSK = timezone(timedelta(hours=3))

# ---------------------------------------------------------------- константы (формулы в одном месте)
PERIOD = timedelta(hours=12)          # ступенька убывания Танка
# Падение на ступеньку: быстрее личного гриба (у него 20/15/10/15 за 8 ч).
TANK_DROP = {"sweet": 40.0, "tea": 30.0, "clean": 20.0, "happy": 30.0}
PARTY_SCALE = 0.5                     # при 40 участниках показатели падают в 1.5 раза быстрее
TANK_CAPACITY_MAX = 40
LOW_STAT = 15.0
STAT_TITLES = {"sweet": "сахар", "tea": "заварка", "clean": "чистота", "happy": "настроение"}
DEATH_AFTER = timedelta(hours=24)     # сутки на нуле — Танк закисает навсегда
MOLD_BELOW = 20.0                     # чистота ниже — плесень злее
MOLD_CHANCE_DIRTY = 0.25
MOLD_CHANCE_CLEAN = 0.07
MOLD_CURE_MEMBERS = 3                 # сколько разных участников должны вылечить плесень
MOLD_CURE_WINDOW = timedelta(hours=24)
TANK_ACTIONS = {   # действие: (показатель, прирост, кулдаун, базовый опыт)
    "sugar": ("sweet", 12.0, timedelta(hours=4), 10),
    "tea": ("tea", 12.0, timedelta(hours=4), 10),
    "clean": ("clean", 18.0, timedelta(hours=8), 14),
    "pet": ("happy", 10.0, timedelta(minutes=30), 4),
}
TANK_DAILY_PER_STAT = 4               # вклад одного игрока в показатель в сутки
HP_REGEN_PER_HOUR = 0.4               # базовый реген; апгрейды и мутации ускоряют
HP_UPGRADE_REGEN = 0.1                # за каждый уровень клуба
STATS = ("sweet", "tea", "clean", "happy")
# «Спора» → «Гриб-мутант» за ~2 недели командой из 5 человек.
STAGES = [(0, 1, "Спора-Танк"), (200, 2, "Кадушка"), (600, 3, "Мистер-Чан"),
          (1200, 4, "Дон-Цистерна"), (2000, 5, "Резервуарчан"), (2800, 6, "Гриб-мутант")]

TALK = {
    "mold": ["Мы покрываемся плесенью. Все сюда. Мы не шутим.",
             "Нас много, а плесень одна. Почему мы проигрываем?",
             "Помогите. Мы обещаем не судить того, кто придёт последним."],
    "hunger": ["Нас {n}, а кормит {k}. Мы всё видим.",
               "Мы уже двадцатилитровые, а вы приносите по ложке.",
               "Сахар закончился. Мы грустим. Мы медленно грустим."],
    "lazy": ["В клубе {n} человек. Мы чувствуем, кто сегодня не приходил.",
             "Мы не осуждаем. Мы просто запоминаем."],
    "happy": ["Мы полны. Мы бурлим. Мы любим вас, все {n}.",
              "Лучший день за нашу недолгую споровую жизнь."],
    "raid": ["Плесень идёт. Мы держим оборону изо всех двадцати литров.",
             "Бейте её уходом. Мы примем любую помощь — даже гладить."],
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def stage_for(xp: int) -> dict:
    size, title, next_xp = 1, STAGES[0][2], None
    for i, (need, sz, name) in enumerate(STAGES):
        if xp >= need:
            size, title = sz, name
        elif next_xp is None:
            next_xp = need
    return {"size": size, "title": title, "next_xp": next_xp}


def party_scale(members: int) -> float:
    """Во сколько раз быстрее падают показатели при таком составе."""
    return round(1.0 + PARTY_SCALE * max(0, members - 1) / (TANK_CAPACITY_MAX - 1), 3)


async def mutation_codes_async(s: AsyncSession, club_id: int) -> set[str]:
    rows = await s.scalars(select(ClubTankMutation.code).where(ClubTankMutation.club_id == club_id))
    return set(rows)


async def hp_max_for(s: AsyncSession, club: Club, codes: set[str] | None = None) -> float:
    codes = codes if codes is not None else await mutation_codes_async(s, club.id)
    return max(50.0, 100.0 + 10 * (club.level - 1) + muts.hp_bonus(codes))


async def ensure_tank(s: AsyncSession, club: Club) -> ClubTank:
    tank = await s.get(ClubTank, club.id)
    if tank is None:
        tank = ClubTank(club_id=club.id)
        s.add(tank)
        await s.flush()
    return tank


async def tick(s: AsyncSession, club: Club, tank: ClubTank, at: datetime | None = None) -> None:
    """Досчитать ступеньки убывания, плесень, закисание и реген здоровья."""
    at = at or now()
    if not tank.alive:
        return
    steps = int((at - tank.updated_at) / PERIOD) if at > tank.updated_at else 0
    codes = await mutation_codes_async(s, club.id)
    decay_mult = (1 + muts.decay_bonus(codes)) * party_scale(club.members)
    from . import club_events
    world = await club_events.world_modifiers(s, at)          # мировые ивенты сушат/пачкают Танк
    regen = HP_REGEN_PER_HOUR + HP_UPGRADE_REGEN * (club.level - 1)
    hours = max(0.0, (at - tank.updated_at).total_seconds() / 3600)
    tank.hp = min(tank.hp_max, tank.hp + regen * hours)
    for i in range(steps):
        step_at = tank.updated_at + PERIOD * (i + 1)
        if tank.zero_since and step_at - tank.zero_since >= DEATH_AFTER:
            break
        if not tank.mold and rng.random() < _mold_chance(tank.clean) * (1 - muts.mold_resist(codes)):
            tank.mold = True
            tank.mold_cures = []
            _feed(s, club.id, None, "mold", "🦠 Плесень на Танке! Все на помощь!")
        drops = {key: TANK_DROP[key] * decay_mult * (2.0 if tank.mold and key in ("clean", "happy") else 1.0)
                 for key in STATS}
        club_events.apply_world(drops, world)
        for key, drop in drops.items():
            setattr(tank, key, max(getattr(tank, key) - drop, 0.0))
        if tank.zero_since is None and any(getattr(tank, key) <= 0 for key in STATS):
            tank.zero_since = step_at
    tank.updated_at = tank.updated_at + PERIOD * steps
    if tank.zero_since and at - tank.zero_since >= DEATH_AFTER:
        tank.alive = False
        tank.died_at = tank.zero_since + DEATH_AFTER
        _feed(s, club.id, None, "died", "💀 Танк закис. Клуб потерял свою банку — возродить её нельзя.")


def _mold_chance(clean: float) -> float:
    return MOLD_CHANCE_DIRTY if clean < MOLD_BELOW else MOLD_CHANCE_CLEAN


def _feed(s: AsyncSession, club_id: int, user_id: int | None, event: str, body: str, emoji: str = "📝",
          **data) -> ClubPost:
    post = ClubPost(club_id=club_id, user_id=user_id, kind="auto", event=event, body=body[:280], emoji=emoji,
                    data=data)
    s.add(post)
    return post


def _member_cds(tank: ClubTank, user_id: int) -> dict:
    """Личные кулдауны участника: tank.cooldowns = {"<user_id>": {"sugar": iso, ...}}."""
    return (tank.cooldowns or {}).get(str(user_id)) or {}


def _cd_left(tank: ClubTank, user_id: int, action: str, cd: timedelta, at: datetime) -> int:
    raw = _member_cds(tank, user_id).get(action)
    if not raw:
        return 0
    last = datetime.fromisoformat(raw)
    left = (last + cd - at).total_seconds()
    return max(0, int(left))


def _stamp_cd(tank: ClubTank, user_id: int, action: str, at: datetime) -> None:
    cds = {**(tank.cooldowns or {})}
    mine = {**(_member_cds(tank, user_id)), action: at.isoformat()}
    cds[str(user_id)] = mine
    tank.cooldowns = cds


async def _day(s: AsyncSession, club_id: int, at: datetime) -> ClubDayStat:
    day = at.astimezone(MSK).date()
    row = await s.scalar(select(ClubDayStat).where(ClubDayStat.club_id == club_id, ClubDayStat.day == day)
                         .with_for_update())
    if row is None:
        row = ClubDayStat(club_id=club_id, day=day)
        s.add(row)
        await s.flush()
    return row


def _day_key(at: datetime) -> str:
    return at.astimezone(MSK).date().isoformat()


async def norm_target(club: Club) -> int:
    """Норма дня: хотя бы ⅓ активных участников, но не меньше 3."""
    from . import clubs as clubs_svc
    active = await clubs_svc.active_members_count(club)
    return max(3, -(-active // 3))


async def contributors_today(s: AsyncSession, club_id: int, at: datetime) -> int:
    day = await s.scalar(select(ClubDayStat).where(ClubDayStat.club_id == club_id, ClubDayStat.day == at.astimezone(MSK).date()))
    return len(day.contributors or []) if day else 0


async def act(s: AsyncSession, user: User, club: Club, tank: ClubTank, action: str,
              ip_hash: str | None = None) -> dict:
    """Уход за Танком. Вклад ограничен суточным потолком на показатель, идут кулдауны участника."""
    if action not in TANK_ACTIONS:
        raise ApiError("Танк не понимает такого действия", 400, "validation_error")
    at = now()
    await tick(s, club, tank, at)
    if not tank.alive:
        raise ApiError("Танк закис и не возрождается", 409, "tank_dead")
    key, add, cd, base_xp = TANK_ACTIONS[action]
    old_xp = tank.xp
    left = _cd_left(tank, user.id, action, cd, at)
    if left:
        raise ApiError("Рано: Танк ещё не переварил", 429, "cooldown", retry_after=left)
    day = await _day(s, club.id, at)
    counts = (day.care_counts or {}).get(str(user.id)) or {}
    if counts.get(key, 0) >= TANK_DAILY_PER_STAT:
        raise ApiError(f"Твой вклад в «{key}» на сегодня исчерпан — позови клуб", 429, "club_cap",
                       retry_after=_seconds_to_msk_midnight(at))
    # Антиабуз: живые аккаунты (возраст ≥ 3 дней, личный стрик ≥ 1, не больше 2 аккаунтов на адрес).
    from . import clubs as clubs_svc
    allowed, why = await clubs_svc.can_contribute(s, user, club, ip_hash=ip_hash)
    if not allowed:
        raise ApiError(why or "Вклад с этого аккаунта не засчитывается", 403, "club_contribution_blocked")
    if action == "clean" and tank.mold:
        return await _cure(s, user, club, tank, at)
    setattr(tank, key, min(100.0, getattr(tank, key) + add))
    codes = await mutation_codes_async(s, club.id)
    xp = int(round(base_xp * (1 + muts.club_xp_bonus(codes) + float((club.perks or {}).get("xp_bonus", 0)))))
    tank.xp += xp
    tank.best_xp = max(tank.best_xp, tank.xp)
    tank.updated_at = at
    _stamp_cd(tank, user.id, action, at)
    counts[key] = counts.get(key, 0) + 1
    day.care_counts = {**(day.care_counts or {}), str(user.id): counts}
    if user.id not in (day.contributors or []):
        day.contributors = [*(day.contributors or []), user.id]
    await clubs_svc.add_contribution(s, club, user.id, xp)
    if tank.zero_since and all(getattr(tank, k) > 0 for k in STATS):
        tank.zero_since = None
    target = day.norm_target or await norm_target(club)
    day.norm_target = target
    day.norm_done = len(day.contributors) >= target
    club.last_active_at = at
    level_up = await stage_up(s, club, tank, old_xp)
    return {"ok": True, "action": action, "xp": xp, "hp": round(tank.hp),
            "stage": stage_for(tank.xp)["size"], "stage_up": level_up,
            "message": rng.choice(TALK["happy"]).format(n=club.members)}


async def _cure(s: AsyncSession, user: User, club: Club, tank: ClubTank, at: datetime) -> dict:
    """Плесень лечится N разными участниками; каждый — со своим кулдауном."""
    cures = [c for c in (tank.mold_cures or [])
             if at - datetime.fromisoformat(c["at"]) <= MOLD_CURE_WINDOW]
    if user.id not in {c["user_id"] for c in cures}:
        cures.append({"user_id": user.id, "at": at.isoformat()})
    tank.mold_cures = cures
    _stamp_cd(tank, user.id, "clean", at)
    if len({c["user_id"] for c in cures}) >= MOLD_CURE_MEMBERS:
        tank.mold = False
        tank.mold_cures = []
        _feed(s, club.id, user.id, "cured", f"🧪 Плесень побеждена: {MOLD_CURE_MEMBERS} участника провели ванну!")
        return {"ok": True, "action": "clean", "xp": 6, "cured": True,
                "message": "Плесень смыта общими силами 🧪"}
    left = MOLD_CURE_MEMBERS - len({c["user_id"] for c in cures})
    return {"ok": True, "action": "clean", "xp": 4, "cured": False, "need": left,
            "message": f"Ты начал ванну. Осталось участников: {left} 🧪"}


def _seconds_to_msk_midnight(at: datetime) -> int:
    local = at.astimezone(MSK)
    tomorrow = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=MSK)
    return int((tomorrow - local).total_seconds())


async def stage_up(s: AsyncSession, club: Club, tank: ClubTank, old_xp: int) -> bool:
    before, after = stage_for(old_xp)["size"], stage_for(tank.xp)["size"]
    if after > before:
        _feed(s, club.id, None, "stage", f"🎉 Танк вырос: теперь это «{stage_for(tank.xp)['title']}»!", stage=after)
        return True
    return False


async def out(s: AsyncSession, club: Club, tank: ClubTank, viewer_id: int | None = None) -> dict:
    at = now()
    if tank.updated_at < at:
        await tick(s, club, tank, at)
    codes = await mutation_codes_async(s, club.id)
    st = stage_for(tank.xp)
    hp_max = max(50.0, 100.0 + 10 * (club.level - 1) + muts.hp_bonus(codes))
    tank.hp_max = hp_max
    rows = (await s.scalars(select(ClubTankMutation).where(ClubTankMutation.club_id == club.id)
                            .order_by(ClubTankMutation.stage))).all()
    dies_in = None
    if tank.alive and tank.zero_since:
        dies_in = max(0, int((tank.zero_since + DEATH_AFTER - at).total_seconds()))
    norm = await norm_target(club)
    done = await contributors_today(s, club.id, at)
    world: tuple[str, ...] = ()
    try:
        from . import club_events
        world = tuple((await club_events.active_world(s, at)).get("active") or ())
    except Exception:   # noqa: BLE001 — фраза Танка не должна ломаться из-за настроек ивентов
        world = ()
    return {
        "club_id": club.id, "xp": tank.xp, "stage": st, "mold": tank.mold, "alive": tank.alive,
        "stats": {k: round(getattr(tank, k)) for k in STATS},
        "hp": round(tank.hp), "hp_max": round(hp_max),
        "mood": mood(tank),
        "phrase": phrase(club, tank, done, norm, world),
        "dies_in": dies_in, "next_drop_in": max(0, int((tank.updated_at + PERIOD - at).total_seconds())),
        "party_scale": party_scale(club.members), "daily_cap": TANK_DAILY_PER_STAT,
        "norm": {"done": done, "target": norm, "ok": done >= norm},
        "cure_need": max(0, MOLD_CURE_MEMBERS - len({c["user_id"] for c in (tank.mold_cures or [])})),
        "scars": tank.scars or [],
        "mutations": [{"code": r.code, "stage": r.stage, "title": muts.BY_CODE[r.code].title,
                       "emoji": muts.BY_CODE[r.code].emoji, "dmg": muts.BY_CODE[r.code].dmg,
                       "desc": muts.BY_CODE[r.code].desc, "upkeep": muts.BY_CODE[r.code].upkeep,
                       "color": muts.BY_CODE[r.code].color} for r in rows if r.code in muts.BY_CODE],
        "attack": muts.attack_damage(codes), "defense": round(muts.defense(codes), 2),
        "party": club.members,
        "cooldowns": {a: _cd_left(tank, viewer_id, a, TANK_ACTIONS[a][2], at) for a in TANK_ACTIONS}
        if viewer_id else {},
    }


def mood(tank: ClubTank) -> str:
    if not tank.alive:
        return "dead"
    if tank.mold:
        return "moldy"
    if any(getattr(tank, k) <= LOW_STAT for k in STATS):
        return "hungry"
    if tank.happy >= 80:
        return "happy"
    return "ok"


def _admin_phrase(club: Club, world: tuple[str, ...] = ()) -> str | None:
    """Цитаты из админки: категория «tank» и «event:<код>» для идущих мировых ивентов.

    Если админ добавил свои — они звучат вместо встроенного корпуса (в облачке Танка).
    Поддерживаются подстановки {n} (участников) и {k} (ухаживали сегодня).
    """
    from . import quotes

    lines: list[str] = []
    for code in world:
        lines.extend(quotes.custom_lines(f"event:{code}"))
    lines.extend(quotes.custom_lines("tank"))
    return rng.choice(lines) if lines else None


def phrase(club: Club, tank: ClubTank, contributors: int, norm: int, world: tuple[str, ...] = ()) -> str:
    """Танк говорит от лица «мы»: реагирует на лень, недокорм, плесень и хороший день."""
    words = _admin_phrase(club, world)
    if words is not None:
        try:
            return words.format(n=club.members, k=max(1, contributors))
        except (KeyError, IndexError, ValueError):
            return words
    if tank.mold:
        return rng.choice(TALK["mold"])
    if not tank.alive:
        return "Мы закисли. Мы были двадцатью литрами. Мы всё помним."
    if any(getattr(tank, k) <= LOW_STAT for k in STATS):
        return rng.choice(TALK["hunger"]).format(n=club.members, k=max(1, contributors))
    if contributors < norm:
        return rng.choice(TALK["lazy"]).format(n=club.members)
    return rng.choice(TALK["happy"]).format(n=club.members)


async def grant_badge_all(s: AsyncSession, club: Club, code: str, user_ids: list[int] | None = None) -> int:
    """Выдать клубный бейдж участникам. user_ids — снапшот состава на старте ивента:
    награду получают только те, кто был в клубе тогда (ТЗ: награды ивента — его стартовому составу)."""
    from .gamification import award
    if user_ids is None:
        user_ids = list(await s.scalars(select(ClubMember.user_id).where(ClubMember.club_id == club.id)))
    given = 0
    for uid in dict.fromkeys(user_ids):
        if await award(s, uid, code):
            given += 1
    return given


async def add_scar(s: AsyncSession, club: Club, tank: ClubTank, code: str, note: str) -> None:
    tank.scars = [*(tank.scars or []), {"code": code, "at": now().isoformat(), "note": note[:120]}]
    _feed(s, club.id, None, "scar", f"🩹 Новый шрам Танка: {note[:150]}", code=code)


async def notify_club(s: AsyncSession, club_id: int, kind: str, **payload) -> int:
    """Уведомить всех участников клуба (тихие часы — на стороне notifications/push)."""
    payload.setdefault("club_id", club_id)
    members = (await s.scalars(select(ClubMember.user_id).where(ClubMember.club_id == club_id))).all()
    sent = 0
    for uid in members:
        notifications.notify(s, uid, kind, **payload)
        sent += 1
    return sent


def public_out(data: dict) -> dict:
    return data


def club_stats(rows: list[ClubDayStat]) -> dict:
    streak = 0
    for row in sorted(rows, key=lambda r: r.day, reverse=True):
        if row.norm_done:
            streak += 1
        else:
            break
    return {"streak": streak, "days": len(rows)}


async def weekly(s: AsyncSession, club: Club, tank: ClubTank, at: datetime | None = None) -> dict:
    """Недельный итог: стрик, сброс недельного вклада. Остальное — leagues.py/club_events.py."""
    at = at or now()
    rows = (await s.scalars(select(ClubDayStat).where(ClubDayStat.club_id == club.id))).all()
    stats = club_stats(rows)
    week = _week_key(at)
    members = (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id))).all()
    board = [{"user_id": m.user_id, "week": m.contribution_week, "total": m.contribution_total} for m in members]
    board.sort(key=lambda x: x["week"], reverse=True)
    for m in members:
        m.contribution_week = 0
        m.contrib_week_key = week
    club.week_key = week
    return {"streak": stats["streak"], "board": board}


def _week_key(at: datetime) -> str:
    iso = at.astimezone(MSK).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
