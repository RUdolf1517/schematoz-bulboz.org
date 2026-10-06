"""Грибные кооперативы (клубы): создание, вступление, роли, копилка, лента, лаборатория.

Экономика и правила:
* создание — 500 $₽ (трата, а не перевод: деньги сгорают, инфляция не разгоняется);
* вступление — открытое / по заявке / по инвайту; взнос в копилку от MIN_DEPOSIT;
* из копилки нельзя вывести себе никому: только траты на апгрейды/ивенты (лог видят все);
* выход → кулдаун 24 ч на вступление в другой клуб;
* клуб без активности 30 дней расформировывается, Танк уходит в «Музей кооперативов»;
* лидер неактивен 28 дней → главенство переходит к самому активному заму.

Перки участников растут со стадией Танка и уровнем клуба (PERK_XP/PERK_MUT/PERK_DECAY),
плюс временные препараты из лаборатории (обнулил комбучу своего гриба → через 12 ч перк на 24 ч).
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..extensions import get_redis
from ..models import (Club, ClubBankTx, ClubBannedUser, ClubDayStat, ClubInvite, ClubJoinRequest, ClubLabCraft,
                      ClubLabRun, ClubMember, ClubMembershipCooldown, ClubMuseumEntry, ClubPost, ClubReaction,
                      ClubReport, ClubTank, ClubTankMutation, Kombucha, User)
from . import club_tank as tank_svc
from . import club_tank_mutations as muts
from . import notifications
from . import wood

MSK = timezone(timedelta(hours=3))
CREATE_COST = 500
# Название клуба — как в ТЗ: ООО "Пример". Слово «ООО» и кавычки обязательны, юзер вписывает
# своё название вместо «Пример». Принимаем прямые и типографские кавычки, храним прямые.
NAME_CORE_RE = re.compile(r"^[\w \-.,'()ёЁ]{2,18}$", re.UNICODE)
NAME_RE = re.compile(r'^ООО\s*[«"„“‘\']\s*(?P<core>.+?)\s*[»"“”‘’\']$', re.IGNORECASE)
NAME_HINT = ('Название — только имя: 2–18 символов, буквы, цифры, пробел, дефис, точка. '
             '«ООО» и кавычки подставятся сами.')


def format_club_name(core: str) -> str:
    """Собрать каноничное название клуба: ООО "Имя"."""
    return f'ООО "{core.strip()}"'


TAG_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9]{2,5}$")
MIN_DEPOSIT = 50
MEMBERSHIP_COOLDOWN = timedelta(hours=24)
DISBAND_AFTER = timedelta(days=30)
LEADER_INACTIVE = timedelta(days=28)
MAX_DEPUTIES = 3
CAPACITY_STEPS = [(5, 0), (10, 400), (15, 900), (20, 1600), (30, 2600), (40, 4000)]   # (мест, цена $₽)
STREAK_FREEZE_COST = 300
WEEKLY_MUT_CRAFT_STAGE_MUTATIONS = 3        # сколько мутаций одной стадии нужно на крафт
LAB_DURATION = timedelta(hours=12)          # комбуча настаивается
LAB_EFFECT = timedelta(hours=24)            # сколько действует препарат
LAB_COOLDOWN = timedelta(hours=48)          # юзер может сливать комбучу раз в 48 ч
FEED_MAX = 280
IP_MEMBERS_LIMIT = 2                        # не больше 2 аккаунтов клуба с одного адреса
PERK_XP = (0.05, 0.25)                      # +5…25% опыта личному грибу за уход
PERK_MUT = (0.01, 0.03)                     # +1…3% шанса мутации в мини-играх
PERK_DECAY = (0.05, 0.15)                   # −5…15% скорости падения показателей
LEAGUES = [("bronze", "Бронза", 1), ("silver", "Серебро", 2), ("gold", "Золото", 3),
           ("platinum", "Платина", 4), ("diamond", "Алмаз", 5)]


def now() -> datetime:
    return datetime.now(timezone.utc)


def week_key(at: datetime | None = None) -> str:
    iso = (at or now()).astimezone(MSK).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _clean_name(raw: str) -> str:
    """Игрок вписывает только имя — «ООО "» и закрывающая кавычка добавляются сами.

    Если название случайно пришло целиком (ООО "Имя" или «Имя»), лишнее снимаем,
    чтобы не получить «ООО "ООО "Имя""». Итог всегда: ООО "Имя" (имя 2–18 символов).
    """
    name = re.sub(r"\s+", " ", str(raw or "")).strip()
    m = NAME_RE.match(name)
    if m is not None:
        name = m.group("core")
    name = name.strip().strip("«»\"'“”„‘’").strip()
    if not NAME_CORE_RE.match(name):
        raise ApiError(NAME_HINT, 400, "validation_error", field="name")
    return format_club_name(name)


def _clean_tag(raw: str) -> str:
    tag = str(raw or "").strip().strip("[]").upper()
    if not TAG_RE.match(tag):
        raise ApiError("Тег: 2–5 букв или цифр, например [ЧАЙ]", 400, "validation_error", field="tag")
    return tag


def _clean_color(raw: str | None, fallback: str) -> str:
    value = str(raw or "").strip()
    return value if re.match(r"^#[0-9a-fA-F]{6}$", value) else fallback


def _antibot_disabled() -> bool:
    """В e2e (ANTIBOT_DISABLED) жёсткие антиабуз-проверки по IP снимаются — там один браузер."""
    from .antibot import disabled
    return disabled()


def ip_key() -> str | None:
    """IP-адрес клиента так, как его видят антиспам и nginx (X-Forwarded-For)."""
    from flask import request
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if not ip:
        return None
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- создание, вступление, выход
async def create(s: AsyncSession, user: User, data: dict, *, free: bool = False) -> tuple[Club, ClubTank]:
    """Основать клуб. free=True (администраторы) — без списания 500 $₽.

    Флаг приходит только от API, который сам проверяет права; из тела запроса его брать нельзя.
    """
    free = bool(free)
    name, tag = _clean_name(data.get("name")), _clean_tag(data.get("tag"))
    if await s.scalar(select(Club.id).where(func.lower(Club.name) == name.lower())):
        raise ApiError("Такое название уже занято", 409, "name_taken", field="name")
    if await s.scalar(select(Club.id).where(func.lower(Club.tag) == tag.lower())):
        raise ApiError("Такой тег уже занят", 409, "tag_taken", field="tag")
    mine = await s.scalar(select(ClubMember.club_id).where(ClubMember.user_id == user.id))
    if mine is not None:
        raise ApiError("Ты уже в кооперативе — сначала выйди", 409, "already_in_club")
    cd = await s.get(ClubMembershipCooldown, user.id)
    if cd is not None and cd.until > now():
        raise ApiError("После выхода из клуба нужно выждать 24 часа", 429, "club_cooldown",
                       retry_after=int((cd.until - now()).total_seconds()))
    if not free:
        await wood.spend(s, user.id, CREATE_COST, "club_create", f"club:{user.id}:{now().timestamp()}")
    club = Club(name=name, tag=tag, emblem=str(data.get("emblem") or "🍄")[:16],
                color=_clean_color(data.get("color"), "#ff5a36"),
                color2=_clean_color(data.get("color2"), "#ff8a3d"),
                description=str(data.get("description") or "")[:280],
                join_mode=data.get("join_mode") if data.get("join_mode") in ("open", "request", "invite") else "open",
                min_level=max(1, min(int(data.get("min_level") or 1), 50)),
                leader_id=user.id, members=1, perks=perks({}, level=1, stage=1))
    s.add(club)
    await s.flush()
    s.add(ClubMember(club_id=club.id, user_id=user.id, role="leader"))
    tank = ClubTank(club_id=club.id)
    s.add(tank)
    _feed(s, club.id, user.id, "join", f"🏛 Кооператив {club.name} основан. Танк ждёт первых литров!")
    await s.flush()
    await _track_ip(s, club, user.id)
    return club, tank


async def get(s: AsyncSession, club_id: int, *, alive: bool = True) -> Club:
    club = await s.get(Club, club_id)
    if club is None or (alive and club.status == "disbanded"):
        raise ApiError("Кооператив не найден", 404, "club_not_found")
    return club


async def by_tag(s: AsyncSession, tag: str, include_disbanded: bool = False) -> Club:
    club = await s.scalar(select(Club).where(func.lower(Club.tag) == str(tag).lower()))
    if club is None or (club.status != "active" and not include_disbanded):
        raise ApiError("Кооператив не найден — возможно, он в Музее", 404, "club_not_found")
    return club


async def my_club(s: AsyncSession, user_id: int) -> tuple[Club | None, ClubMember | None]:
    member = await s.scalar(select(ClubMember).where(ClubMember.user_id == user_id))
    if member is None:
        return None, None
    club = await s.get(Club, member.club_id)
    if club is None or club.status == "disbanded":
        return None, None
    return club, member


async def join(s: AsyncSession, user: User, club: Club, invite_code: str | None = None,
               message: str | None = None, ip_hash: str | None = None) -> tuple[str, ClubMember | None]:
    """Вернёт ("joined", member) или ("requested", None)."""
    if club.status != "active":
        raise ApiError("Кооператив закрыт или расформирован", 409, "club_closed")
    mine = await s.scalar(select(ClubMember.club_id).where(ClubMember.user_id == user.id))
    if mine is not None:
        raise ApiError("Ты уже в кооперативе", 409, "already_in_club")
    cd = await s.get(ClubMembershipCooldown, user.id)
    if cd is not None and cd.until > now():
        raise ApiError("После выхода из клуба нужно выждать 24 часа", 429, "club_cooldown",
                       retry_after=int((cd.until - now()).total_seconds()))
    if await s.get(ClubBannedUser, (club.id, user.id)) is not None:
        raise ApiError("Тебя нет в списке приглашённых этого клуба", 403, "club_banned")
    if user.level < (club.min_level or 1):
        raise ApiError(f"Клуб принимает с уровня {club.min_level}", 403, "club_level_too_low")
    if club.members >= club.capacity:
        raise ApiError("В кооперативе нет свободных мест", 409, "club_full")
    invite = None
    if invite_code:
        invite = await s.scalar(select(ClubInvite).where(ClubInvite.code == invite_code, ClubInvite.club_id == club.id)
                                .with_for_update())
        if invite is None or (invite.expires_at and invite.expires_at < now()) or invite.uses >= invite.max_uses:
            raise ApiError("Приглашение недействительно", 409, "club_invite_bad")
    if club.join_mode == "invite" and invite is None:
        raise ApiError("В этот клуб только по приглашению", 403, "club_invite_only")
    await _check_ip(s, club, user.id, ip_hash)
    if club.join_mode == "request" and invite is None:
        existing = await s.scalar(select(ClubJoinRequest).where(
            ClubJoinRequest.club_id == club.id, ClubJoinRequest.user_id == user.id,
            ClubJoinRequest.status == "pending"))
        if existing is None:
            s.add(ClubJoinRequest(club_id=club.id, user_id=user.id, message=(message or "")[:140] or None))
        for uid in await _staff_ids(s, club.id):
            notifications.notify(s, uid, "club", club_id=club.id,
                                 username=user.username, tag=club.tag)
        return "requested", None
    return "joined", await _add_member(s, club, user, invite)


async def _add_member(s: AsyncSession, club: Club, user: User, invite: ClubInvite | None) -> ClubMember:
    club.members += 1
    club.last_active_at = now()
    member = ClubMember(club_id=club.id, user_id=user.id, role="member")
    s.add(member)
    if invite is not None:
        invite.uses += 1
    _feed(s, club.id, user.id, "join", f"🥳 @{user.username} вступил в кооператив!",
          username=user.username)
    for uid in await _staff_ids(s, club.id):
        notifications.notify(s, uid, "club", club_id=club.id, username=user.username)
    return member


async def leave(s: AsyncSession, user: User, club: Club, member: ClubMember) -> None:
    # Кулдаун на новый клуб ставится в любом случае — иначе им пользуются, чтобы прыгать по клубам.
    cd = await s.get(ClubMembershipCooldown, user.id) or ClubMembershipCooldown(user_id=user.id)
    cd.until, cd.from_club_id = now() + MEMBERSHIP_COOLDOWN, club.id
    s.add(cd)
    if member.role == "leader":
        heir = await _heir(s, club)
        if heir is None:
            await s.delete(member)
            await disband(s, club, reason="Лидер ушёл, замов не осталось")
            return
        await set_role(s, club, heir, "leader", actor=user, by_system=True)
    await s.delete(member)
    club.members = max(0, club.members - 1)
    club.last_active_at = now()
    _feed(s, club.id, user.id, "leave", f"👋 @{user.username} покинул кооператив.",
          username=user.username)


async def kick(s: AsyncSession, actor: ClubMember, target: ClubMember, club: Club, reason: str | None = None,
               ban: bool = False) -> None:
    if target.user_id == actor.user_id:
        raise ApiError("Себя можно только выйти", 400, "validation_error")
    if target.role == "leader":
        raise ApiError("Лидера нельзя исключить — сначала передай главенство", 403, "club_role")
    if actor.role == "member":
        raise ApiError("Исключать может лидер или зам", 403, "club_role")
    if actor.role == "deputy" and target.role == "deputy":
        raise ApiError("Зам не может исключить зама", 403, "club_role")
    await s.delete(target)
    club.members = max(0, club.members - 1)
    user = await s.get(User, target.user_id)
    if ban:
        s.add(ClubBannedUser(club_id=club.id, user_id=target.user_id, by_id=actor.user_id,
                             reason=(reason or "")[:140] or None))
    cd = await s.get(ClubMembershipCooldown, target.user_id) or ClubMembershipCooldown(user_id=target.user_id)
    cd.until, cd.from_club_id = now() + MEMBERSHIP_COOLDOWN, club.id
    s.add(cd)
    if user is not None:
        notifications.notify(s, user.id, "club", club_id=club.id, tag=club.tag,
                             reason=reason or "")
    _feed(s, club.id, actor.user_id, "kick",
          f"🚪 @{user.username if user else target.user_id} исключён из клуба.")


async def set_role(s: AsyncSession, club: Club, member: ClubMember, role: str, actor: User | None = None,
                   by_system: bool = False) -> None:
    if role not in ("leader", "deputy", "member"):
        raise ApiError("Неизвестная роль", 400, "validation_error")
    if role == "deputy":
        count = await s.scalar(select(func.count(ClubMember.user_id)).where(
            ClubMember.club_id == club.id, ClubMember.role == "deputy"))
        if (count or 0) >= MAX_DEPUTIES:
            raise ApiError(f"Замов не больше {MAX_DEPUTIES}", 409, "club_deputies_full")
    previous = member.role
    if role == "leader":
        old_leader = await s.scalar(select(ClubMember).where(ClubMember.club_id == club.id,
                                                             ClubMember.role == "leader"))
        if old_leader is not None and old_leader.user_id != member.user_id:
            old_leader.role = "deputy"
        club.leader_id = member.user_id
    member.role = role
    if not by_system:
        notifications.notify(s, member.user_id, "club", club_id=club.id, role=role)
        _feed(s, club.id, actor.id if actor else None, "role",
              f"⭐ @{(await s.get(User, member.user_id)).username} — теперь {role_title(role)}.")


async def decide_request(s: AsyncSession, actor: ClubMember, club: Club, request_id: int, approve: bool) -> None:
    if actor.role == "member":
        raise ApiError("Заявки разбирают лидер и замы", 403, "club_role")
    req = await s.get(ClubJoinRequest, request_id, with_for_update=True)
    if req is None or req.club_id != club.id or req.status != "pending":
        raise ApiError("Заявка не найдена", 404, "club_request_not_found")
    req.status, req.decided_at, req.decided_by = ("accepted" if approve else "rejected"), now(), actor.user_id
    user = await s.get(User, req.user_id)
    if approve and user is not None:
        if club.members >= club.capacity:
            raise ApiError("В кооперативе нет свободных мест", 409, "club_full")
        await _check_ip(s, club, user.id, None)
        await _add_member(s, club, user, None)
    elif user is not None:
        notifications.notify(s, user.id, "club", club_id=club.id, tag=club.tag)


async def invite(s: AsyncSession, actor: ClubMember, club: Club, max_uses: int = 1,
                 hours: int = 72) -> ClubInvite:
    if actor.role == "member":
        raise ApiError("Приглашать может лидер или зам", 403, "club_role")
    inv = ClubInvite(club_id=club.id, code=secrets.token_urlsafe(9), created_by=actor.user_id,
                     max_uses=max(1, min(int(max_uses), 50)), expires_at=now() + timedelta(hours=max(1, min(hours, 720))))
    s.add(inv)
    return inv


async def _staff_ids(s: AsyncSession, club_id: int) -> list[int]:
    """Лидер и замы — те, кому уходят уведомления о заявках и событиях клуба."""
    return list(await s.scalars(select(ClubMember.user_id).where(
        ClubMember.club_id == club_id, ClubMember.role.in_(("leader", "deputy")))))


async def _heir(s: AsyncSession, club: Club) -> ClubMember | None:
    """Самый активный зам (или участник), если лидер пропал."""
    rows = (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id,
                                                     ClubMember.role.in_(("deputy", "member")))
                            .order_by(ClubMember.contribution_total.desc(), ClubMember.joined_at))).all()
    return rows[0] if rows else None


async def auto_leader(s: AsyncSession, club: Club) -> bool:
    """Лидер неактивен 28 дней — главенство переходит к самому активному заму."""
    leader = await s.get(User, club.leader_id)
    last = (leader.last_seen_at if leader else None) or (leader.created_at if leader else None)
    if leader is not None and last and now() - last < LEADER_INACTIVE:
        return False
    member = await s.scalar(select(ClubMember).where(ClubMember.club_id == club.id,
                                                     ClubMember.role == "leader"))
    heir = await _heir(s, club)
    if member is None or heir is None:
        return False
    await set_role(s, club, heir, "leader", by_system=True)
    notifications.notify(s, heir.user_id, "club", club_id=club.id, tag=club.tag)
    _feed(s, club.id, None, "role", "👑 Главенство перешло к самому активному заму: лидер давно не заходил.")
    return True


# ---------------------------------------------------------------- копилка
async def deposit(s: AsyncSession, user: User, club: Club, amount: int) -> int:
    amount = int(amount)
    if amount < MIN_DEPOSIT:
        raise ApiError(f"Взнос — от {MIN_DEPOSIT} $₽", 400, "validation_error", field="amount")
    await wood.spend(s, user.id, amount, "club_deposit", f"club:{club.id}:{user.id}:{now().timestamp()}")
    return await _bank(s, club, user.id, amount, "deposit", f"{user.id}:{now().timestamp()}")


async def spend_from_bank(s: AsyncSession, actor: ClubMember, club: Club, amount: int, reason: str,
                          ref: str) -> int:
    """Тратит только лидер/зам; лог трат видят все. Вывести себе нельзя — только эти траты."""
    if actor.role == "member":
        raise ApiError("Копилкой распоряжаются лидер и замы", 403, "club_role")
    if reason not in ("upgrade", "streak_freeze", "raid", "perk", "war", "beauty"):
        raise ApiError("Недопустимая трата", 400, "validation_error")
    return await _bank(s, club, actor.user_id, -abs(int(amount)), reason, ref)


async def _bank(s: AsyncSession, club: Club, user_id: int | None, delta: int, reason: str, ref: str) -> int:
    row = await s.scalar(select(Club).where(Club.id == club.id).with_for_update())
    if delta < 0 and row.account + delta < 0:
        raise ApiError("В копилке не хватает $₽", 409, "club_bank_low")
    row.account += delta
    tx = ClubBankTx(club_id=club.id, user_id=user_id, delta=delta, reason=reason[:24],
                    ref=ref[:64], balance_after=row.account)
    s.add(tx)
    club.account = row.account
    _feed(s, club.id, user_id, "bank",
          f"💰 Копилка {'+' if delta > 0 else '−'}{abs(delta)} $₽ ({BANK_TITLES.get(reason, reason)}). "
          f"Остаток: {row.account} $₽.", delta=delta)
    return row.account


BANK_TITLES = {"deposit": "взнос", "upgrade": "апгрейд", "streak_freeze": "заморозка стрика",
               "raid": "рейд", "perk": "препарат", "war": "война", "beauty": "конкурс"}
ROLE_TITLES = {"leader": "глава", "deputy": "зам", "member": "грибник"}


def role_title(role: str) -> str:
    return ROLE_TITLES.get(role, role)


async def upgrade(s: AsyncSession, actor: ClubMember, club: Club, kind: str) -> dict:
    """Апгрейды: места (до 40) и уровень клуба (реген HP, перки, косметика)."""
    if actor.role == "member":
        raise ApiError("Апгрейды покупают лидер и замы", 403, "club_role")
    if kind == "capacity":
        nxt = next((cap for cap, price in CAPACITY_STEPS if cap > club.capacity), None)
        if nxt is None:
            raise ApiError("Максимум мест уже открыт", 409, "club_max_capacity")
        price = dict(CAPACITY_STEPS)[nxt]
        await spend_from_bank(s, actor, club, price, "upgrade", f"cap:{nxt}")
        club.capacity = nxt
        _feed(s, club.id, actor.user_id, "upgrade", f"🏗 Мест в кооперативе теперь {nxt}.")
        return {"capacity": nxt}
    if kind == "level":
        price = 250 * club.level
        await spend_from_bank(s, actor, club, price, "upgrade", f"lvl:{club.level + 1}")
        club.level += 1
        _feed(s, club.id, actor.user_id, "upgrade", f"⬆️ Уровень клуба {club.level}: Танк регенерирует быстрее.")
        return {"level": club.level}
    if kind == "streak_freeze":
        week = week_key()
        if (club.settings or {}).get("freeze_week") == week:
            raise ApiError("Заморозка стрика — раз в неделю", 429, "club_freeze_used")
        await spend_from_bank(s, actor, club, STREAK_FREEZE_COST, "streak_freeze", f"freeze:{week}")
        club.settings = {**(club.settings or {}), "freeze_week": week, "freeze_until": (now() + timedelta(days=1)).isoformat()}
        _feed(s, club.id, actor.user_id, "freeze", "🧊 Стрик клуба заморожен на сутки.")
        return {"freeze_until": club.settings["freeze_until"]}
    raise ApiError("Неизвестный апгрейд", 400, "validation_error")


# ---------------------------------------------------------------- перки, лаборатория, косметика
def perks(codes: dict, level: int, stage: int, lab: list[dict] | None = None) -> dict:
    """Пассивные бонусы: 5→25% опыта, 1→3% шанса мутаций, 5→15% замедления падения."""
    k = (stage - 1) / max(1, len(tank_svc.STAGES) - 1)
    out = {
        "xp_bonus": round(PERK_XP[0] + (PERK_XP[1] - PERK_XP[0]) * k, 3),
        "mut_chance": round(PERK_MUT[0] + (PERK_MUT[1] - PERK_MUT[0]) * k, 4),
        "decay_slow": round(PERK_DECAY[0] + (PERK_DECAY[1] - PERK_DECAY[0]) * k, 3),
        "level": level,
        "cosmetics": sorted({c for lvl, c in CLUB_COSMETICS if lvl <= level}),
    }
    for prep in lab or []:
        if prep.get("until") and datetime.fromisoformat(prep["until"]) > now():
            out[prep["kind"]] = round(out.get(prep["kind"], 0) + float(prep.get("value", 0)), 4)
    return out


CLUB_COSMETICS = [(1, "club_frame"), (2, "club_bg"), (3, "club_jar"), (4, "club_flag"), (5, "club_glow")]


async def refresh_perks(s: AsyncSession, club: Club, tank: ClubTank) -> dict:
    codes = await tank_svc.mutation_codes_async(s, club.id)
    club.perks = perks(codes, club.level, tank_svc.stage_for(tank.xp)["size"], (club.settings or {}).get("lab"))
    return club.perks


async def lab_drain(s: AsyncSession, user: User, club: Club, kombucha_id: int, kind: str) -> ClubLabRun:
    """Раз в 48 ч слить комбучу своего гриба (обнулить показатель) → через 12 ч препарат на 24 ч."""
    if kind not in ("xp_bonus", "mut_chance", "decay_slow"):
        raise ApiError("Неизвестный препарат", 400, "validation_error")
    last = await s.scalar(select(ClubLabRun).where(ClubLabRun.user_id == user.id)
                          .order_by(ClubLabRun.started_at.desc()))
    if last is not None and now() - last.started_at < LAB_COOLDOWN:
        raise ApiError("Комбучу можно сливать раз в 48 часов", 429, "lab_cooldown",
                       retry_after=int((last.started_at + LAB_COOLDOWN - now()).total_seconds()))
    k = await s.get(Kombucha, kombucha_id)
    if k is None or k.user_id != user.id:
        raise ApiError("Гриб не найден", 404, "kombucha_not_found")
    stat = min(tank_svc.STATS, key=lambda st: getattr(k, st))
    setattr(k, stat, 0.0)
    run = ClubLabRun(club_id=club.id, user_id=user.id, kombucha_id=k.id, stat=stat, kind=kind,
                     ready_at=now() + LAB_DURATION)
    s.add(run)
    await s.flush()
    club.last_active_at = now()
    return run


async def lab_collect(s: AsyncSession, club: Club, run_id: int, user_id: int) -> dict:
    run = await s.get(ClubLabRun, run_id)
    if run is None or run.club_id != club.id or run.user_id != user_id:
        raise ApiError("Препарат не найден", 404, "lab_run_not_found")
    if run.collected_at is not None:
        raise ApiError("Препарат уже собран", 409, "lab_collected")
    if run.ready_at > now():
        raise ApiError("Комбуча ещё настаивается", 429, "lab_not_ready",
                       retry_after=int((run.ready_at - now()).total_seconds()))
    run.collected_at = now()
    prep = {"kind": run.kind, "value": LAB_VALUE.get(run.kind, 0.05), "until": (now() + LAB_EFFECT).isoformat(),
            "by": user_id, "at": now().isoformat()}
    lab = [p for p in (club.settings or {}).get("lab", [])
           if p.get("until") and datetime.fromisoformat(p["until"]) > now()]
    club.settings = {**(club.settings or {}), "lab": [*lab, prep]}
    tank = await tank_svc.ensure_tank(s, club)
    await refresh_perks(s, club, tank)
    _feed(s, club.id, user_id, "lab", f"🧪 Препарат готов: +{int(prep['value'] * 100)}% "
                                     f"({LAB_TITLES[run.kind]}) на 24 часа для всех грибов клуба.")
    return prep


LAB_VALUE = {"xp_bonus": 0.10, "mut_chance": 0.01, "decay_slow": 0.05}
LAB_TITLES = {"xp_bonus": "опыт", "mut_chance": "шанс мутации", "decay_slow": "замедление падения"}


async def decay_slow_for(s: AsyncSession, user_id: int) -> float:
    """Насколько медленнее падают показатели личного гриба: перк клуба + препараты."""
    club, member = await my_club(s, user_id)
    if club is None:
        return 0.0
    return float((club.perks or {}).get("decay_slow", 0.0))


async def club_bonus_for(s: AsyncSession, user_id: int) -> dict:
    """Перки для личного гриба: опыт за уход и шанс мутаций."""
    club, member = await my_club(s, user_id)
    if club is None:
        return {"xp_bonus": 0.0, "mut_chance": 0.0, "decay_slow": 0.0, "club": None}
    perks_ = club.perks or {}
    return {**perks_, "club": {"id": club.id, "tag": club.tag, "name": club.name, "emblem": club.emblem,
                               "color": club.color, "color2": club.color2}}


# ---------------------------------------------------------------- лента, реакции, жалобы, доска
def _feed(s: AsyncSession, club_id: int, user_id: int | None, event: str, body: str, emoji: str = "📝",
          **data) -> ClubPost:
    post = ClubPost(club_id=club_id, user_id=user_id, kind="auto", event=event, body=body[:FEED_MAX],
                    emoji=emoji, data=data)
    s.add(post)
    return post


async def post(s: AsyncSession, member: ClubMember, club: Club, body: str) -> ClubPost:
    text = re.sub(r"\s+", " ", str(body or "")).strip()
    if not (1 <= len(text) <= FEED_MAX):
        raise ApiError(f"Пост: 1–{FEED_MAX} символов", 400, "validation_error", field="body")
    if await s.scalar(select(ClubPost.id).where(ClubPost.club_id == club.id, ClubPost.deleted_at.is_(None),
                                               ClubPost.kind == "user",
                                               ClubPost.created_at > now() - timedelta(seconds=60))):
        raise ApiError("Не так быстро: пост раз в минуту", 429, "club_post_rate")
    p = ClubPost(club_id=club.id, user_id=member.user_id, kind="user", body=text)
    s.add(p)
    club.last_active_at = now()
    return p


async def delete_post(s: AsyncSession, actor: ClubMember, club: Club, post_id: int) -> None:
    if actor.role == "member":
        raise ApiError("Посты удаляют лидер и замы", 403, "club_role")
    p = await s.get(ClubPost, post_id)
    if p is None or p.club_id != club.id:
        raise ApiError("Пост не найден", 404, "club_post_not_found")
    p.deleted_at, p.deleted_by = now(), actor.user_id


async def react(s: AsyncSession, member: ClubMember, club: Club, post_id: int, emoji: str) -> None:
    p = await s.get(ClubPost, post_id)
    if p is None or p.club_id != club.id or p.deleted_at is not None:
        raise ApiError("Пост не найден", 404, "club_post_not_found")
    emoji = str(emoji or "")[:16]
    if not emoji:
        raise ApiError("Пустая реакция", 400, "validation_error")
    existing = await s.scalar(select(ClubReaction).where(ClubReaction.post_id == post_id,
                                                         ClubReaction.user_id == member.user_id,
                                                         ClubReaction.emoji == emoji))
    if existing is not None:
        await s.delete(existing)                     # повторный тап снимает реакцию
    else:
        s.add(ClubReaction(post_id=post_id, user_id=member.user_id, emoji=emoji))


async def report(s: AsyncSession, club: Club, user_id: int, post_id: int, reason: str) -> ClubReport:
    r = ClubReport(club_id=club.id, post_id=post_id, user_id=user_id, reason=(reason or "")[:160])
    s.add(r)
    return r


async def board(s: AsyncSession, club: Club) -> list[dict]:
    rows = (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id)
                            .order_by(ClubMember.contribution_week.desc()).limit(20))).all()
    users = {u.id: u for u in (await s.scalars(select(User).where(
        User.id.in_([r.user_id for r in rows])))).all()} if rows else {}
    return [{"username": users[r.user_id].username if r.user_id in users else f"#{r.user_id}",
             "role": r.role, "week": r.contribution_week, "total": r.contribution_total} for r in rows]


async def call_help(s: AsyncSession, user: User, club: Club, tank: ClubTank) -> int:
    member = await s.get(ClubMember, (club.id, user.id))
    if member is None:
        raise ApiError("Ты не в клубе", 403, "club_role")
    if member.last_help_at and now() - member.last_help_at < timedelta(hours=6):
        raise ApiError("Звать на помощь — раз в 6 часов", 429, "club_help_cooldown",
                       retry_after=int((member.last_help_at + timedelta(hours=6) - now()).total_seconds()))
    member.last_help_at = now()
    _feed(s, club.id, user.id, "help", f"🆘 @{user.username} зовёт всех: Танку нужна помощь!")
    sent = 0
    for m in (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id))).all():
        if m.user_id != user.id:
            notifications.notify(s, m.user_id, "club", club_id=club.id, tag=club.tag,
                                 username=user.username)
            sent += 1
    return sent


async def add_contribution(s: AsyncSession, club: Club, user_id: int, amount: int) -> None:
    member = await s.get(ClubMember, (club.id, user_id))
    if member is None:
        return
    member.contribution_week += amount
    member.contribution_total += amount
    member.contrib_week_key = week_key()
    member.last_contribution_at = now()
    club.xp += amount
    club.last_active_at = now()


# ---------------------------------------------------------------- антиабуз
async def _track_ip(s: AsyncSession, club: Club, user_id: int) -> None:
    ip = ip_key()
    if ip is None:
        return
    try:
        r = get_redis()
        r.sadd(f"club:{club.id}:ip:{ip}", user_id)
        r.expire(f"club:{club.id}:ip:{ip}", int(DISBAND_AFTER.total_seconds()))
    except Exception:  # noqa: BLE001 — без Redis проверка просто не срабатывает
        pass


async def _ip_users(club_id: int, ip: str) -> set[int]:
    try:
        return {int(x) for x in get_redis().smembers(f"club:{club_id}:ip:{ip}")}
    except Exception:  # noqa: BLE001
        return set()


async def _check_ip(s: AsyncSession, club: Club, user_id: int, ip_hash: str | None) -> None:
    from .antibot import disabled
    ip = ip_hash or ip_key()
    if ip is None or disabled():
        return
    users = await _ip_users(club.id, ip)
    if user_id not in users and len(users) >= IP_MEMBERS_LIMIT:
        raise ApiError(f"С одного адреса в клуб — не больше {IP_MEMBERS_LIMIT} аккаунтов", 403,
                       "club_ip_limit")
    await _track_ip(s, club, user_id)


async def can_contribute(s: AsyncSession, user: User, club: Club, ip_hash: str | None = None) -> tuple[bool, str | None]:
    """Норма и вклад считаются только с «живых» аккаунтов (см. ТЗ, антиабуз)."""
    if not _antibot_disabled():
        created = user.created_at
        age = now() - (created if created.tzinfo else created.replace(tzinfo=timezone.utc))
        if age < timedelta(days=3):
            return False, "Аккаунт младше 3 дней — вклад клубу не засчитывается"
        if (user.streak_days or 0) < 1:
            return False, "Нужен личный стрик ухода ≥ 1 дня"
    ip = ip_hash or ip_key()
    if ip is not None and not _antibot_disabled():
        users = await _ip_users(club.id, ip)
        if user.id not in users and len(users) >= IP_MEMBERS_LIMIT:
            return False, f"С одного адреса в клуб — не больше {IP_MEMBERS_LIMIT} аккаунтов"
    await _track_ip(s, club, user.id)
    return True, None


async def active_members_count(club: Club) -> int:
    return max(1, club.members)


# ---------------------------------------------------------------- роспуск, музей, недельные итоги
async def disband(s: AsyncSession, club: Club, reason: str | None = None) -> None:
    if club.status == "disbanded":
        return
    tank = await tank_svc.ensure_tank(s, club)
    st = tank_svc.stage_for(tank.xp)
    s.add(ClubMuseumEntry(club_id=club.id, name=club.name, tag=club.tag, emblem=club.emblem, color=club.color,
                          color2=club.color2, stage=st["size"], tank_xp=tank.xp, members_total=club.members,
                          scars=tank.scars or [], reason=(reason or "")[:120], founded_at=club.created_at))
    club.status, club.disbanded_at, club.disband_reason = "disbanded", now(), (reason or "")[:120]
    # Имя и тег освобождаем: уникальные индексы не дадут основать новый клуб с тем же названием,
    # а в музее остаётся прежняя карточка (ClubMuseumEntry).
    club.name, club.tag = f"архив №{club.id}"[:24], f"М{club.id}"[:5]
    for m in (await s.scalars(select(ClubMember).where(ClubMember.club_id == club.id))).all():
        notifications.notify(s, m.user_id, "club", club_id=club.id, tag=club.tag,
                             reason=reason or "")
        await s.delete(m)
    club.members = 0


async def check_inactive(s: AsyncSession, club: Club) -> bool:
    if club.status == "active" and now() - (club.last_active_at or club.created_at) > DISBAND_AFTER:
        await disband(s, club, reason="30 дней без активности")
        return True
    return False


async def weekly_all(s: AsyncSession) -> dict:
    """Идемпотентный недельный пересчёт: стрики, лиги, войны, конкурс. Запуск — flask clubs-weekly."""
    from . import club_events, leagues
    week = week_key()
    out = {"week": week, "clubs": 0, "disbanded": 0, "leagues": 0, "wars": 0}
    clubs = (await s.scalars(select(Club).where(Club.status == "active"))).all()
    for club in clubs:
        tank = await tank_svc.ensure_tank(s, club)
        await tank_svc.tick(s, club, tank)
        await tank_svc.weekly(s, club, tank)
        await refresh_perks(s, club, tank)
        if await check_inactive(s, club):
            out["disbanded"] += 1
            continue
        out["clubs"] += 1
    out["leagues"] = await leagues.settle_week(s, week)
    out["wars"] = await club_events.settle_wars(s, week)
    await club_events.start_week(s, week)
    return out


async def museum(s: AsyncSession) -> list[dict]:
    rows = (await s.scalars(select(ClubMuseumEntry).order_by(ClubMuseumEntry.disbanded_at.desc()).limit(60))).all()
    return [{"club_id": r.club_id, "name": r.name, "tag": r.tag, "emblem": r.emblem, "color": r.color,
             "color2": r.color2, "stage": r.stage, "tank_xp": r.tank_xp, "members_total": r.members_total,
             "scars": r.scars, "reason": r.reason, "disbanded_at": r.disbanded_at.isoformat()} for r in rows]


async def public_out(s: AsyncSession, club: Club, viewer_id: int | None = None) -> dict:
    tank = await tank_svc.ensure_tank(s, club)
    data = await tank_svc.out(s, club, tank, viewer_id=viewer_id)
    members = await s.scalar(select(func.count(ClubMember.user_id)).where(ClubMember.club_id == club.id)) or 0
    return {"id": club.id, "name": club.name, "tag": club.tag, "emblem": club.emblem, "color": club.color,
            "color2": club.color2, "description": club.description, "join_mode": club.join_mode,
            "min_level": club.min_level, "members": members, "capacity": club.capacity, "level": club.level,
            "xp": club.xp, "account": club.account, "status": club.status, "perks": club.perks,
            "leader_id": club.leader_id, "created_at": club.created_at.isoformat(),
            "last_active_at": club.last_active_at.isoformat() if club.last_active_at else None,
            "tank": data}
