"""«Чайный гриб» — тамагочи в трёхлитровой банке. Режим «хардкор» (с 13-го захода):
- показатели падают сильнее, закисает после 48 ч на нуле, опыта до стадий нужно в разы больше;
- плесень: если банка грязная (чистота < 35), на каждой 8-часовой ступеньке может завестись плесень.
  С плесенью гриб не растёт и не мутирует, а чистота и настроение падают быстрее. Лечится «уксусной ванной»;
- если любой показатель ниже 15, опыт за уход режется вдвое;
- отросток — раз в неделю на последней стадии (и после каждого деления снова нужно 7 дней ухода);
- «Погладить» — гриб отвечает цитатой сомнительной личности, «Поговорить» — диалогом из философской книги.


Правила (всё считает сервер, фронт только рисует):
- 4 показателя 0..100: сахар, заварка, чистота, настроение. Падают ступенькой
  РАЗ В 8 ЧАСОВ (DROP), отсчёт от рождения гриба — уход не сдвигает таймер.
- Действия с кулдаунами дают показатель и опыт. Сахар от 90 — сахарная кома (гриб слипся).
- «Идеальный коридор» (опыт ×1): сахар 55–70, заварка 65–85, чистота ≥ 80, настроение ≥ 70.
  Хотя бы один показатель вне зоны — опыт ×0.5 (остальное не меняется).
- «Бонус дня»: раз в 20 часов опыт за мини-игры и $₽ за уход за сутки.
- Если любой показатель лежит на нуле 48 часов — гриб закисает. Можно перезавести
  (поколение +1) или реанимировать за $₽.
- Имя гриба уникально на весь сайт (без учёта регистра).
- Несколько банок: первая бесплатно, дополнительные банки покупаются за «Деревянные»;
  нового гриба в пустую банку можно купить за 1000 $₽ или дождаться бесплатного отростка.
- Отросток: если гриб дошёл до последней стадии и выполнил условия ухода, от него
  отрастает новый гриб в свободной банке либо ждёт, пока игрок выберет его.
- 20 мутаций: выпадают случайно при действиях, у каждой своя стадия и условие.
  Остаются на грибе навсегда + попадают в коллекцию юзера (kombucha_codex).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..errors import ApiError
from ..models import Kombucha, KombuchaCodex, KombuchaTrade, MutationCounter, User, WoodTx
from . import kombucha_achievements as kb_achievements
from . import kombucha_diary as diary
from . import quotes, wood
from .kombucha_mutations import MUT_BY_CODE, MUTATIONS, RARITY, RARITY_ORDER, Ctx, Mutation

MSK = timezone(timedelta(hours=3))
rng = random.Random()          # в тестах подменяется, чтобы мутации были детерминированы

STATS = ("sweet", "tea", "clean", "happy")
PERIOD = timedelta(hours=8)          # ступенька убывания — раз в 8 часов
DROP = {"sweet": 20.0, "tea": 15.0, "clean": 10.0, "happy": 15.0}  # за каждые 8 часов
DEATH_AFTER = timedelta(hours=48)   # 2 суток на нуле — время вернуться с выходных
MOLD_CLEAN_BELOW = 20.0      # ниже этой чистоты может завестись плесень
MOLD_CHANCE = 0.10          # в грязной банке
MOLD_CHANCE_CLEAN = 0.03    # и даже в чистой — споры летают везде           # шанс на каждой ступеньке
MOLD_EXTRA = {"clean": 10.0, "happy": 15.0}
LOW_STAT = 15.0              # если хоть что-то ниже — опыт за уход /2
STICKY_FROM = 90.0           # сахарная кома: сахар от 90 — перекорм, гриб слипается
# «Идеальный коридор»: пока ВСЕ показатели в своих зонах, опыт идёт ×1, иначе ×0.5.
# Только опыт: $₽, счастье и мутации от коридора не зависят.
CORRIDOR = {"sweet": (55.0, 70.0), "tea": (65.0, 85.0), "clean": (80.0, 100.0), "happy": (70.0, 100.0)}
XP_IN_CORRIDOR = 1.0
XP_OUT_CORRIDOR = 0.5

# действие: (показатель, прирост, кулдаун, опыт, фраза)
ACTIONS = {
    "sugar": ("sweet", 25, timedelta(hours=4), 8, "Хрум-хрум, сахарок 🍬"),
    "tea": ("tea", 25, timedelta(hours=4), 8, "Свежая заварка, как у бабушки ☕"),
    "clean": ("clean", 40, timedelta(hours=8), 12, "Банка сияет ✨"),
    "pet": ("happy", 8, timedelta(minutes=30), 2, "Гриб довольно булькает 🫧"),
    "talk": ("happy", 3, timedelta(minutes=30), 2, "Гриб задумался 🤔"),
    "cure": ("clean", 20, timedelta(hours=6), 0, "Уксусная ванна! Плесень побеждена 🧪"),
}
DAILY_COOLDOWN = timedelta(hours=20)
SPROUT_CARE_DAYS = 3
SPROUT_EVERY = timedelta(days=7)
SPROUT_MAX = 3              # один гриб делится не больше 3 раз за жизнь

STAGES = [  # (с какого опыта, название, размер 1..6)
    (0, "Спора", 1), (80, "Плёночка", 2), (250, "Блинчик", 3), (550, "Медуза", 4),
    (1000, "Гриб-гигант", 5), (1600, "Легенда трёхлитровой банки", 6),
]

NAMES = ["Гриша", "Бульбоз", "Кефирыч", "Чайнобой", "Медузий", "Шипучка", "Бражник", "Грибозавр",
         "Пузырь", "Заварыч", "Кисляк", "Блинчик", "Сахарок", "Бульк"]

TALK = {
    "happy": ["Жизнь — как заварка: главное, не пересластить.", "Я сегодня особенно газированный 😎",
              "Сыграй со мной в мини-игру — мне от этого тоже хорошо.", "Бульк. Это значит «спасибо»."],
    "hungry": ["Сахарку бы…", "Я не капризничаю, я ферментируюсь без сахара."],
    "thirsty": ["Заварки! Полцарства за заварку!", "Я почти компот. Долей чаю."],
    "dirty": ["Банка мутная, как объяснения у доски.", "Помой банку, пожалуйста. Мне неловко."],
    "sad": ["Со мной никто не разговаривает…", "Погладь, а?"],
    "sticky": ["Я слипся. Это был перебор с сахаром.", "Сахарная кома, не беспокоить."],
    "moldy": ["Я весь в плесени 🦠 Уксусную ванну, срочно!", "Кажется, у меня завелись соседи. Зелёные и пушистые."],
}


def phrase(k: Kombucha) -> str:
    """Реплика в облачке. В сахарной коме гриб только стонет, в остальное время цитирует
    сомнительных личностей — тот же набор, что и по кнопке «Погладить»."""
    m = mood(k)
    if m == "dead":
        return "…"
    if m == "sticky":
        return rng.choice(TALK["sticky"])
    return quotes.as_speech(quotes.dubious(remote=False))


# ---------------------------------------------------------------- мутации (каталог — kombucha_mutations.py)
def catalog() -> list[dict]:
    return [{"code": m.code, "title": m.title, "emoji": m.emoji, "hint": m.hint, "stage": m.stage,
             "stage_title": STAGES[m.stage - 1][1], "rarity": m.rarity, "rarity_title": RARITY[m.rarity][0],
             "color": m.color} for m in MUTATIONS]


def has_mut(k: Kombucha, code: str) -> bool:
    return any(x.get("code") == code for x in (k.mutations or []))


MAX_MUT_PER_STAGE = 3  # у одного гриба — не больше 3 мутаций каждой стадии (итого до 18)


def stage_mut_counts(k: Kombucha) -> dict[int, int]:
    out: dict[int, int] = {}
    for x in (k.mutations or []):
        m = MUT_BY_CODE.get(x.get("code"))
        if m:
            out[m.stage] = out.get(m.stage, 0) + 1
    return out


def roll_mutation(ctx: Ctx) -> Mutation | None:
    """Максимум одна новая мутация за действие. Кандидаты перемешаны, чтобы порядок
    в каталоге не давал преимущества; сначала бросаем редкие."""
    size = stage_for(ctx.k.xp)["size"]
    # на каждой стадии роста — только мутации этой стадии и не больше 3 штук
    if stage_mut_counts(ctx.k).get(size, 0) >= MAX_MUT_PER_STAGE:
        return None
    cands = [m for m in MUTATIONS if m.stage == size and not has_mut(ctx.k, m.code) and m.check(ctx)]
    rng.shuffle(cands)
    cands.sort(key=lambda m: RARITY_ORDER.index(m.rarity))
    for m in cands:
        if rng.random() < m.chance:
            return m
    return None


async def next_serial(s, code: str) -> int:
    """Порядковый номер экземпляра мутации на весь сайт (как у подарков в Telegram)."""
    return (await s.execute(
        insert(MutationCounter).values(code=code, issued=1)
        .on_conflict_do_update(index_elements=["code"], set_={"issued": MutationCounter.issued + 1})
        .returning(MutationCounter.issued))).scalar()


async def strip_mutations(s, rows: list[Kombucha], codes: list[str], wounded_days: int = 7) -> int:
    """Лаборатория кооператива: грибы отдают мутации, а на неделю получают дебаф «Раненый»
    (показатели падают вдвое быстрее — см. tick())."""
    want = {c for c in codes if c}
    taken = 0
    for k in rows:
        if k.frozen:
            continue
        kept, lost = [], 0
        for entry in (k.mutations or []):
            code = entry["code"] if isinstance(entry, dict) else str(entry)
            if code in want and lost < len(want):
                lost += 1
                taken += 1
            else:
                kept.append(entry)
        if lost:
            k.mutations = kept
            k.wounded_until = now() + timedelta(days=wounded_days)
    return taken


async def add_mutation(s, k: Kombucha, m: Mutation, at: datetime, inherited: bool = False) -> dict:
    """Повесить мутацию на гриб (с номером экземпляра) и в коллекцию юзера."""
    serial = await next_serial(s, m.code)
    entry = {"code": m.code, "at": at.isoformat(), "serial": serial}
    if inherited:
        entry["inherited"] = True
    k.mutations = [*(k.mutations or []), entry]
    new = (await s.execute(insert(KombuchaCodex).values(user_id=k.user_id, code=m.code, kombucha_name=k.name)
                           .on_conflict_do_nothing().returning(KombuchaCodex.code))).scalar() is not None
    if new:
        # уровень грибовода = 1 + открытые мутации / 5 (открывает рамки аватара и т.п.)
        n = await s.scalar(select(func.count()).select_from(KombuchaCodex).where(KombuchaCodex.user_id == k.user_id))
        await s.execute(update(User).where(User.id == k.user_id).values(level=min(50, 1 + (n or 0) // 5)))
    if new and not inherited:
        await wood.earn(s, k.user_id, "mutation", m.code)
    await kb_achievements.after_mutation(s, k.user_id, m)
    diary.log(s, k, "inherited" if inherited else "mutation", at=at, emoji=m.emoji, title=m.title,
              rarity=RARITY[m.rarity][0], serial=serial)
    if not inherited:
        from .notifications import notify_once
        from .push import enqueue_push
        alert_key = f"mutation:{k.id}:{serial}"
        body = f"Я мутировал: {m.emoji} «{m.title}». Не говори, что я не меняюсь."
        await notify_once(s, k.user_id, "kombucha", alert_key, text=body, kombucha_id=k.id, category="mutation")
        await enqueue_push(s, k.user_id, "mutation", "Появилась мутация 🧬", body, f"/g/{k.id}", alert_key)
    return {"code": m.code, "title": m.title, "emoji": m.emoji, "rarity": m.rarity,
            "rarity_title": RARITY[m.rarity][0], "serial": serial, "first_time": new}


def mut_out(x: dict) -> dict | None:
    m = MUT_BY_CODE.get(x.get("code"))
    if not m:
        return None
    return {"code": m.code, "title": m.title, "emoji": m.emoji, "rarity": m.rarity,
            "rarity_title": RARITY[m.rarity][0], "color": m.color, "stage": m.stage,
            "serial": x.get("serial"), "inherited": bool(x.get("inherited")), "at": x.get("at")}


# ---------------------------------------------------------------- время и состояние
def now() -> datetime:
    return datetime.now(timezone.utc)


def stage_for(xp: int) -> dict:
    cur, nxt = STAGES[0], None
    for i, st in enumerate(STAGES):
        if xp >= st[0]:
            cur = st
            nxt = STAGES[i + 1] if i + 1 < len(STAGES) else None
    return {"title": cur[1], "size": cur[2], "from_xp": cur[0], "next_xp": nxt[0] if nxt else None,
            "next_title": nxt[1] if nxt else None}


def tick(k: Kombucha, at: datetime | None = None, halloween_active: bool = False,
         halloween_window: tuple[datetime, datetime] | None = None, decay_slow: float = 0.0) -> None:
    """Применить ступеньки убывания и проверить, не закис ли гриб.
    В период Хэллоуина чистота и счастье падают вдвое быстрее.
    decay_slow — перк клуба: показатели падают на столько медленнее (0…0.15).
    «Раненый» (бизнес-войны клубов) — наоборот, ускоряет падение вдвое."""
    at = at or now()
    if not k.alive or k.frozen:
        return
    slow = 1.0 - max(0.0, min(0.6, decay_slow))
    wounded = bool(k.wounded_until and at < k.wounded_until)
    if wounded:
        slow *= 0.5
    steps = int((at - k.updated_at) / PERIOD) if at > k.updated_at else 0
    for i in range(steps):
        step_at = k.updated_at + PERIOD * (i + 1)
        if k.zero_since and step_at - k.zero_since >= DEATH_AFTER:
            break
        if not k.mold and rng.random() < (MOLD_CHANCE if k.clean < MOLD_CLEAN_BELOW else MOLD_CHANCE_CLEAN):
            k.mold = True
        event_step = halloween_active or bool(
            halloween_window and halloween_window[0] <= step_at < halloween_window[1])
        for s in STATS:
            drop = DROP[s] * slow * (2 if event_step and s in ("clean", "happy") else 1)
            setattr(k, s, max(getattr(k, s) - drop - (MOLD_EXTRA.get(s, 0.0) if k.mold else 0.0), 0.0))
        if k.zero_since is None and any(getattr(k, s) <= 0 for s in STATS):
            k.zero_since = step_at
    k.updated_at = k.updated_at + PERIOD * steps
    if k.zero_since and at - k.zero_since >= DEATH_AFTER:
        k.alive = False
        k.died_at = k.zero_since + DEATH_AFTER


def stat_in_corridor(key: str, value: float) -> bool:
    low, high = CORRIDOR[key]
    return low <= value <= high


def corridor_state(k: Kombucha) -> dict:
    """Коридор гриба: {"ok", "ranges", "off"} — off перечисляет показатели вне зоны."""
    off = [key for key in STATS if not stat_in_corridor(key, getattr(k, key))]
    return {"ok": not off, "off": off,
            "ranges": {key: [CORRIDOR[key][0], CORRIDOR[key][1]] for key in STATS}}


def in_corridor(k: Kombucha) -> bool:
    return corridor_state(k)["ok"]


def xp_mult(k: Kombucha) -> float:
    return XP_IN_CORRIDOR if in_corridor(k) else XP_OUT_CORRIDOR


def scaled_xp(base_xp: int | float, k: Kombucha) -> int:
    """Опыт с множителем коридора: округление вниз, минимум 1, если базовый опыт > 0."""
    if base_xp <= 0:
        return 0
    return max(1, int(base_xp * xp_mult(k)))


def apply_club_xp(xp: int, club_bonus: float) -> int:
    """Перк кооператива: +5…25% опыта личному грибу (и только опыта — не $₽ и не счастья)."""
    if xp <= 0 or club_bonus <= 0:
        return xp
    return max(1, int(xp * (1.0 + club_bonus)))


def mood(k: Kombucha) -> str:
    if not k.alive:
        return "dead"
    if k.mold:
        return "moldy"
    if k.sweet >= STICKY_FROM:
        return "sticky"
    low = min(STATS, key=lambda s: getattr(k, s))
    if getattr(k, low) < 25:
        return {"sweet": "hungry", "tea": "thirsty", "clean": "dirty", "happy": "sad"}[low]
    return "happy"


def next_drop_in(k: Kombucha, at: datetime | None = None) -> int:
    at = at or now()
    return max(int((k.updated_at + PERIOD - at).total_seconds()), 0)


# ---------------------------------------------------------------- имена
async def name_taken(s, name: str, exclude_id: int | None = None) -> bool:
    q = select(Kombucha.id).where(func.lower(Kombucha.name) == name.lower())
    if exclude_id:
        q = q.where(Kombucha.id != exclude_id)
    return (await s.scalar(q.limit(1))) is not None


async def free_name(s, base: str | None = None) -> str:
    base = (base or rng.choice(NAMES))[:24]
    if not await name_taken(s, base):
        return base
    for _ in range(50):
        cand = f"{base} {rng.randint(2, 9999)}"
        if not await name_taken(s, cand):
            return cand
    raise ApiError("Не удалось придумать имя, задай своё", 409, "name_taken")


async def ensure_name(s, name: str, exclude_id: int | None = None) -> str:
    if await name_taken(s, name, exclude_id):
        raise ApiError(f"Имя «{name}» уже занято другим грибом — придумай своё", 409, "name_taken",
                       field="name")
    return name


# ---------------------------------------------------------------- грибы и банки
def _new(user_id: int, name: str, parent: Kombucha | None = None) -> Kombucha:
    t = now()
    return Kombucha(user_id=user_id, name=name, xp=0, best_xp=0, generation=1, sweet=70.0, tea=70.0,
                    clean=90.0, happy=70.0, alive=True, cooldowns={}, mutations=[], care_days=0, pet_count=0,
                    sprouted=False, sprout_pending=False, parent_id=parent.id if parent else None,
                    born_at=t, updated_at=t, mold=False, owners=[])


async def halloween_decay_window(s) -> tuple[datetime, datetime] | None:
    from . import halloween
    return halloween.decay_window(await halloween.get_config(s))


async def list_for(s, user_id: int, lock: bool = False) -> list[Kombucha]:
    q = select(Kombucha).where(Kombucha.user_id == user_id).order_by(Kombucha.id)
    if lock:
        q = q.with_for_update()
    items = list((await s.scalars(q)).all())
    event_window = await halloween_decay_window(s)
    for k in items:
        tick(k, halloween_window=event_window)
    return items


async def ensure_first(s, user: User) -> list[Kombucha]:
    """Первый гриб выдаётся бесплатно при самом первом заходе в игру
    (флаг в users.profile, чтобы выброшенный гриб не возвращался сам)."""
    user_id = user.id
    items = await list_for(s, user_id, lock=True)
    if not items and not (user.profile or {}).get("kombucha_started"):
        user.profile = {**(user.profile or {}), "kombucha_started": True}
        first = _new(user_id, await free_name(s))
        s.add(first)
        await s.flush()
        diary.log(s, first, "born")
        await kb_achievements.after_plant(s, user_id)
        items = await list_for(s, user_id, lock=True)
    return items


async def get_own(s, user_id: int, kid: int) -> Kombucha:
    k = await s.get(Kombucha, kid, with_for_update=True)
    if k is None or k.user_id != user_id:
        raise ApiError("Гриб не найден", 404, "not_found")
    tick(k, halloween_window=await halloween_decay_window(s))
    return k


async def jars_info(s, user: User) -> dict:
    used = await s.scalar(select(func.count(Kombucha.id)).where(Kombucha.user_id == user.id,
                                                                  Kombucha.frozen.is_(False))) or 0
    return {"jars": user.jars, "used": used, "free": max(user.jars - used, 0), "max": wood.MAX_JARS}


async def plant(s, user: User, name: str | None = None, parent: Kombucha | None = None) -> Kombucha:
    info = await jars_info(s, user)
    if info["free"] <= 0:
        raise ApiError("Нет свободной банки — купи ещё одну в магазине", 409, "no_free_jar")
    if name:
        await ensure_name(s, name)
    else:
        name = await free_name(s, f"{parent.name[:20]} мл." if parent else None)
    k = _new(user.id, name, parent)
    s.add(k)
    await s.flush()
    if parent:
        diary.log(s, k, "sprout_born", parent=parent.name)
    else:
        diary.log(s, k, "born")
    if parent and parent.mutations:
        # наследственность: новый экземпляр одной случайной мутации родителя
        m = MUT_BY_CODE.get(rng.choice(parent.mutations).get("code"))
        if m:
            await add_mutation(s, k, m, now(), inherited=True)
    await kb_achievements.after_plant(s, user.id)
    return k


async def plant_pending_sprout(s, user: User, parent: Kombucha) -> Kombucha:
    """Plant one offspring that was held until the player had an empty jar."""
    if not parent.sprout_pending:
        raise ApiError("У этого гриба нет ожидающего отростка", 409, "no_pending_sprout")
    if (await jars_info(s, user))["free"] <= 0:
        raise ApiError("Нет свободной банки для отростка", 409, "no_free_jar")
    child = await plant(s, user, parent=parent)
    parent.sprout_pending = False
    return child


async def buy_jar(s, user: User) -> dict:
    if user.jars >= wood.MAX_JARS:
        raise ApiError(f"Больше {wood.MAX_JARS} банок на подоконник не влезет", 409, "max_jars")
    await wood.spend(s, user.id, wood.PRICES["jar"], "buy_jar", f"jar{user.jars + 1}")
    user.jars += 1
    await s.flush()
    if user.jars >= wood.MAX_JARS:
        await kb_achievements.award(s, user.id, "kb_jars")
    # Keep the new jar empty so the player can buy a mushroom or choose an offspring.
    return {"sprouts": []}


# ---------------------------------------------------------------- действия
def _cd_left(k: Kombucha, key: str, cd: timedelta, at: datetime) -> int:
    last = (k.cooldowns or {}).get(key)
    if not last:
        return 0
    return max(int((datetime.fromisoformat(last) + cd - at).total_seconds()), 0)


async def _tx_last_day(s, user_id: int, reasons: tuple[str, ...]) -> int:
    return await s.scalar(select(func.count(WoodTx.id)).where(
        WoodTx.user_id == user_id, WoodTx.reason.in_(reasons), WoodTx.created_at >= now() - timedelta(hours=24))) or 0


async def games_last_day(s, user_id: int) -> int:
    """Сколько мини-игр (с наградой) сыграно за сутки — для «Бонуса дня»."""
    return await _tx_last_day(s, user_id, ("minigame", "meditation"))


async def meditations_last_day(s, user_id: int) -> int:
    return await _tx_last_day(s, user_id, ("meditation",))


async def act(s, user: User, k: Kombucha, action: str) -> dict:
    """Выполнить действие. Возвращает {message, mutation?, sprout?, wood}."""
    at = now()
    if not k.alive:
        raise ApiError("Гриб закис 😢 Перезаведи или реанимируй", 409, "kombucha_dead")
    if k.frozen:
        raise ApiError("Гриб заморожен 🧊 Разморозь, чтобы ухаживать", 409, "kombucha_frozen")
    in_danger = k.zero_since is not None
    danger_since = k.zero_since
    old_xp = k.xp
    from . import clubs as clubs_svc
    club_bonus = float((await clubs_svc.club_bonus_for(s, user.id)).get("xp_bonus", 0.0))
    games_24h = med_24h = 0
    daily_wood = 0
    if action == "daily":
        left = _cd_left(k, "daily", DAILY_COOLDOWN, at)
        if left:
            raise ApiError("Бонус дня уже забран", 429, "cooldown", retry_after=left)
        games_24h = await games_last_day(s, user.id)
        med_24h = await meditations_last_day(s, user.id)
        care_24h = await _tx_last_day(s, user.id, ("kombucha_care",))
        n = min(games_24h, 6)
        k.happy = min(k.happy + 10, 100.0)
        # Коридор проверяем после применения действия (счастье уже поднято).
        gain = scaled_xp(0 if k.mold else 5 + 5 * n, k)
        gain = apply_club_xp(gain, club_bonus)
        xp = gain
        k.xp += gain
        daily_wood = await wood.earn(s, user.id, "daily_bonus", f"{k.id}:{at.date().isoformat()}", amount=5 + min(care_24h, 15))
        msg = (f"+{gain} опыта и +{daily_wood} $₽: за сутки {n} игр(ы), гриб гордится 🏆" if n
               else f"+{gain} опыта и +{daily_wood} $₽. Сыграй в игры гриба — завтра бонус будет больше 😉")
        if k.mold:
            msg = "С плесенью гриб не растёт 🦠 Сначала вылечи его уксусной ванной."
    elif action in ACTIONS:
        stat, add, cd, xp, msg = ACTIONS[action]
        if action == "cure" and not k.mold:
            raise ApiError("Гриб здоров, лечить нечего", 409, "not_moldy")
        left = _cd_left(k, action, cd, at)
        if left:
            raise ApiError("Рано, гриб ещё не соскучился", 429, "cooldown", retry_after=left)
        if action == "sugar" and k.sweet >= STICKY_FROM:
            k.happy = max(k.happy - 10, 0.0)
            msg, xp = "Перебор! Гриб слипся 🥴 (−настроение)", 0
        setattr(k, stat, min(getattr(k, stat) + add, 100.0))
        quote = None
        if action == "pet":
            k.pet_count += 1
            if k.pet_count in diary.PET_MILESTONES:
                diary.log(s, k, "pets", n=k.pet_count)
            quote = quotes.dubious()
            msg = rng.choice(TALK["sticky"]) if mood(k) == "sticky" else quotes.as_speech(quote)
        elif action == "talk":
            quote = quotes.philosophy()
            msg = quotes.as_speech(quote)
            k.talk_count = (k.talk_count or 0) + 1
            if k.talk_count >= 30:
                await kb_achievements.award(s, user.id, "kb_philo")
        elif action == "cure":
            k.mold = False
            diary.log(s, k, "cured")
            await kb_achievements.award(s, user.id, "kb_mold")
        if k.mold:
            xp = 0
        elif min(getattr(k, x) for x in STATS) < LOW_STAT:
            xp //= 2                      # штраф за запущенность — раньше коридора
        xp = scaled_xp(xp, k)             # и только потом множитель коридора
        xp = apply_club_xp(xp, club_bonus)  # и перк кооператива (+5…25% опыта личному грибу)
        k.xp += xp
    else:
        raise ApiError("Неизвестное действие", 400, "validation_error")

    k.cooldowns = {**(k.cooldowns or {}), action: at.isoformat()}
    k.best_xp = max(k.best_xp, k.xp)
    rescued = in_danger and all(getattr(k, st) > 0 for st in STATS)
    if rescued:
        k.zero_since = None
        diary.log(s, k, "rescued", hours=max(1, round((at - danger_since).total_seconds() / 3600)))
    diary.stage_check(s, k, old_xp)
    today = at.astimezone(MSK).date()
    if k.last_care_day != today:
        k.last_care_day = today
        k.care_days += 1
    earned = await wood.earn(s, user.id, "kombucha_care", f"{k.id}:{action}:{at.isoformat()}")
    from .gamification import on_care
    await on_care(s, user.id)

    res: dict = {"message": msg, "mutation": None, "sprout": None, "wood": earned,
                 "xp_gain": xp, "xp_mult": xp_mult(k), "club_bonus": club_bonus,
                 "quote": quote if action in ACTIONS else None}
    msk = at.astimezone(MSK)
    m = None if k.mold else roll_mutation(Ctx(action=action, k=k, hour=msk.hour, weekday=msk.weekday(), games_24h=games_24h,
                          med_24h=med_24h, was_in_danger=rescued, streak_days=user.streak_days))
    if m:
        res["mutation"] = await add_mutation(s, k, m, at)
    if stage_for(k.xp)["size"] == 6:
        await kb_achievements.award(s, user.id, "kb_legend")

    # отросток: легенда делится раз в 7 дней (до SPROUT_MAX раз), если 3 дня за ней ухаживали (счётчик обнуляется после деления)
    if can_sprout(k, at):
        k.sprouted = True
        k.last_sprout_at = at
        k.care_days = 0
        k.sprout_count = (k.sprout_count or 0) + 1
        await wood.earn(s, user.id, "sprout", f"{k.id}:{k.sprout_count}")
        if k.sprout_count >= SPROUT_MAX:
            await kb_achievements.award(s, user.id, "kb_split4")
        await kb_achievements.award(s, user.id, "kb_split")
        if (await jars_info(s, user))["free"] > 0:
            child = await plant(s, user, parent=k)
            diary.log(s, k, "sprout", child=child.name)
            res["sprout"] = {"planted": True, "name": child.name}
        else:
            k.sprout_pending = True
            diary.log(s, k, "sprout", child="малыша (ждёт свободную банку)")
            res["sprout"] = {"planted": False}
    return res


def can_sprout(k: Kombucha, at: datetime | None = None) -> bool:
    at = at or now()
    return (k.alive and not k.frozen and not k.mold and not k.sprout_pending
            and (k.sprout_count or 0) < SPROUT_MAX
            and stage_for(k.xp)["size"] == 6 and k.care_days >= SPROUT_CARE_DAYS
            and (k.last_sprout_at is None or at - k.last_sprout_at >= SPROUT_EVERY))


def sprout_progress(k: Kombucha, at: datetime | None = None) -> dict:
    at = at or now()
    wait = 0
    if k.last_sprout_at:
        wait = max(int((k.last_sprout_at + SPROUT_EVERY - at).total_seconds()), 0)
    return {"care_days": min(k.care_days, SPROUT_CARE_DAYS), "need_days": SPROUT_CARE_DAYS,
            "legend": stage_for(k.xp)["size"] == 6, "next_in": wait, "count": k.sprout_count or 0, "max": SPROUT_MAX,
            "healthy": not k.mold}


async def restart(s, k: Kombucha, name: str | None = None) -> None:
    if k.alive:
        raise ApiError("Гриб жив, его не надо перезаводить", 409, "kombucha_alive")
    if name:
        k.name = await ensure_name(s, name, exclude_id=k.id)
    diary.flush_death(s, k)
    at = now()
    k.generation += 1
    k.xp = 0
    k.sweet, k.tea, k.clean, k.happy = 70.0, 70.0, 90.0, 70.0
    k.alive, k.zero_since, k.died_at, k.cooldowns = True, None, None, {}
    k.care_days, k.last_care_day, k.pet_count, k.sprouted, k.sprout_pending = 0, None, 0, False, False
    k.mold, k.last_sprout_at, k.sprout_count = False, None, 0
    k.mutations = []  # в коллекции юзера мутации остаются навсегда
    k.born_at = k.updated_at = at
    diary.log(s, k, "restart", gen=k.generation)


async def revive(s, user: User, k: Kombucha) -> None:
    """Реанимация за $₽: опыт и мутации сохраняются, показатели — на 50."""
    if k.alive:
        raise ApiError("Гриб и так жив", 409, "kombucha_alive")
    await wood.spend(s, user.id, wood.PRICES["revive"], "revive", f"{k.id}:{k.died_at.isoformat()}")
    await kb_achievements.award(s, user.id, "kb_revive")
    diary.flush_death(s, k)
    diary.log(s, k, "revived", price=wood.PRICES["revive"])
    at = now()
    k.sweet = k.tea = k.clean = k.happy = 50.0
    k.alive, k.zero_since, k.died_at, k.mold = True, None, None, False
    k.updated_at = at


def out(k: Kombucha) -> dict:
    at = now()
    cds = {a: _cd_left(k, a, cd, at) for a, (_, _, cd, _, _) in ACTIONS.items()}
    cds["daily"] = _cd_left(k, "daily", DAILY_COOLDOWN, at)
    m = mood(k)
    danger = None
    if k.alive and k.zero_since:
        danger = max(int((k.zero_since + DEATH_AFTER - at).total_seconds()), 0)
    muts = [mo for mo in (mut_out(x) for x in (k.mutations or [])) if mo]
    muts.sort(key=lambda x: RARITY_ORDER.index(x["rarity"]))
    from .halloween import active_mutations
    muts.extend(active_mutations(k, at))
    st = stage_for(k.xp)
    return {
        "id": k.id, "name": k.name, "xp": k.xp, "best_xp": k.best_xp, "generation": k.generation, "alive": k.alive,
        "stats": {s: round(getattr(k, s)) for s in STATS}, "mood": m, "corridor": corridor_state(k),
        "phrase": phrase(k),
        "stage": st, "cooldowns": cds, "dies_in": danger, "next_drop_in": next_drop_in(k, at) if k.alive else None,
        "age_days": (at - k.born_at).days, "born_at": k.born_at.isoformat(),
        "died_at": k.died_at.isoformat() if k.died_at else None,
        "mutations": muts, "mut_per_stage": MAX_MUT_PER_STAGE,
        "mut_slots": {str(st): n for st, n in sorted(stage_mut_counts(k).items())}, "care_days": k.care_days, "sprouted": k.sprouted, "sprout_pending": k.sprout_pending,
        "sprout_progress": sprout_progress(k, at), "mold": bool(k.mold),
        "halloween_hat": k.halloween_hat,
        "halloween_hat_meta": k.halloween_hat_meta,
        "halloween_mutations": active_mutations(k, at),
        "halloween_gone": bool(k.halloween_gone and k.halloween_gone_day == at.astimezone(MSK).date()),
        "halloween_web_until": k.halloween_web_until.isoformat() if k.halloween_web_until and k.halloween_web_until > at else None,
        "owners": [{"username": o.get("username"), "at": o.get("at"), "how": o.get("how")} for o in (k.owners or [])],
        "is_sprout": k.parent_id is not None,
        "frozen": k.frozen, "frozen_at": k.frozen_at.isoformat() if k.frozen_at else None,
        "price": k.price,
    }


def public_out(k: Kombucha, owner: str | None = None) -> dict:
    """Для профиля/рынка: без кулдаунов и таймеров."""
    o = out(k)
    for key in ("cooldowns", "next_drop_in", "dies_in", "phrase", "sprout_progress"):
        o.pop(key, None)
    if owner:
        o["owner"] = owner
    return o


# ---------------------------------------------------------------- заморозка, продажа, обмен
async def freeze(s, user: User, k: Kombucha) -> None:
    if not k.alive:
        raise ApiError("Закисший гриб не заморозить", 409, "kombucha_dead")
    if k.frozen:
        raise ApiError("Гриб уже заморожен", 409, "kombucha_frozen")
    k.frozen, k.frozen_at = True, now()
    diary.log(s, k, "frozen")
    await kb_achievements.award(s, user.id, "kb_freeze")


async def unfreeze(s, user: User, k: Kombucha) -> None:
    if not k.frozen:
        raise ApiError("Гриб не заморожен", 409, "kombucha_not_frozen")
    if k.price is not None:
        raise ApiError("Сначала сними гриб с продажи", 409, "kombucha_listed")
    if (await jars_info(s, user))["free"] <= 0:
        raise ApiError("Нет свободной банки, чтобы разморозить", 409, "no_free_jar")
    # время в морозилке не считается: сдвигаем якорь ступенек и «время на нуле»
    pause = now() - k.frozen_at
    k.updated_at += pause
    if k.zero_since:
        k.zero_since += pause
    k.frozen, k.frozen_at = False, None
    diary.log(s, k, "unfrozen")


async def transfer(s, k: Kombucha, to_user_id: int, how: str = "trade", price: int | None = None) -> None:
    """Сменить владельца. Гриб остаётся замороженным (на полке нового владельца).
    История владельцев копится в owners — как «провенанс» у подарков в Telegram."""
    names = dict((await s.execute(select(User.id, User.username).where(User.id.in_([k.user_id, to_user_id])))).all())
    hist = list(k.owners or [])
    if not hist:
        hist.append({"username": names.get(k.user_id), "at": k.born_at.isoformat(), "how": "grown"})
    entry = {"username": names.get(to_user_id), "at": now().isoformat(), "how": how}
    if price is not None:
        entry["price"] = price
    k.owners = [*hist, entry][-50:]
    diary.log(s, k, "moved", to=names.get(to_user_id) or "?",
              how=f" за {price} $₽" if price is not None else (" по обмену" if how == "trade" else ""))
    k.user_id = to_user_id
    k.price = None
    k.listed_at = None
    await s.execute(update(KombuchaTrade).where(
        KombuchaTrade.status == "pending",
        (KombuchaTrade.give_id == k.id) | (KombuchaTrade.want_id == k.id)).values(status="cancelled"))
