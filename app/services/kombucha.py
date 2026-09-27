"""«Чайный гриб» — тамагочи в трёхлитровой банке. Режим «хардкор» (с 13-го захода):
- показатели падают сильнее, закисает после 12 ч на нуле, опыта до стадий нужно в разы больше;
- плесень: если банка грязная (чистота < 35), на каждой 12-часовой ступеньке может завестись плесень.
  С плесенью гриб не растёт и не мутирует, а чистота и настроение падают быстрее. Лечится «уксусной ванной»;
- если любой показатель ниже 30, опыт за уход режется вдвое;
- отросток — раз в неделю на последней стадии (и после каждого деления снова нужно 7 дней ухода);
- «Погладить» — гриб отвечает цитатой сомнительной личности, «Поговорить» — диалогом из философской книги.


Правила (всё считает сервер, фронт только рисует):
- 4 показателя 0..100: сахар, заварка, чистота, настроение. Падают ступенькой
  РАЗ В 12 ЧАСОВ (DROP), отсчёт от рождения гриба — уход не сдвигает таймер.
- Действия с кулдаунами дают показатель и опыт. Пересластил (сахар > 90) — гриб слипся.
- «Схема дня»: раз в 20 часов бонус опыта за твои ответы на сайте за сутки.
- Если любой показатель лежит на нуле 24 часа — гриб закисает. Можно перезавести
  (поколение +1) или реанимировать за $₽.
- Имя гриба уникально на весь сайт (без учёта регистра).
- Несколько банок: одна бесплатно, остальные покупаются за «Деревянные».
- Отросток: если гриб дошёл до последней стадии и за ним ухаживали 7+ разных дней,
  от него отрастает новый гриб (в свободную банку, либо ждёт, пока купишь).
- 20 мутаций: выпадают случайно при действиях, у каждой своя стадия и условие.
  Остаются на грибе навсегда + попадают в коллекцию юзера (kombucha_codex).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..errors import ApiError
from ..models import Answer, ContentStatus, DebateVote, Kombucha, KombuchaCodex, KombuchaTrade, MutationCounter, User
from . import kombucha_achievements as kb_achievements
from . import quotes, wood
from .kombucha_mutations import MUT_BY_CODE, MUTATIONS, RARITY, RARITY_ORDER, Ctx, Mutation

MSK = timezone(timedelta(hours=3))
rng = random.Random()          # в тестах подменяется, чтобы мутации были детерминированы

STATS = ("sweet", "tea", "clean", "happy")
PERIOD = timedelta(hours=12)
DROP = {"sweet": 35.0, "tea": 30.0, "clean": 20.0, "happy": 30.0}  # за каждые 12 часов
DEATH_AFTER = timedelta(hours=12)
MOLD_CLEAN_BELOW = 35.0      # ниже этой чистоты может завестись плесень
MOLD_CHANCE = 0.4            # шанс на каждой ступеньке
MOLD_EXTRA = {"clean": 10.0, "happy": 15.0}
LOW_STAT = 30.0              # если хоть что-то ниже — опыт за уход /2
STICKY_ABOVE = 85.0

# действие: (показатель, прирост, кулдаун, опыт, фраза)
ACTIONS = {
    "sugar": ("sweet", 15, timedelta(hours=6), 5, "Хрум-хрум, сахарок 🍬"),
    "tea": ("tea", 15, timedelta(hours=6), 5, "Свежая заварка, как у бабушки ☕"),
    "clean": ("clean", 25, timedelta(hours=12), 8, "Банка сияет ✨"),
    "pet": ("happy", 5, timedelta(hours=1), 1, "Гриб довольно булькает 🫧"),
    "talk": ("happy", 3, timedelta(minutes=30), 2, "Гриб задумался 🤔"),
    "cure": ("clean", 10, timedelta(hours=24), 0, "Уксусная ванна! Плесень побеждена 🧪"),
}
DAILY_COOLDOWN = timedelta(hours=20)
SPROUT_CARE_DAYS = 7
SPROUT_EVERY = timedelta(days=7)

STAGES = [  # (с какого опыта, название, размер 1..6)
    (0, "Спора", 1), (150, "Плёночка", 2), (500, "Блинчик", 3), (1200, "Медуза", 4),
    (2500, "Гриб-гигант", 5), (4000, "Легенда трёхлитровой банки", 6),
]

NAMES = ["Гриша", "Бульбоз", "Кефирыч", "Чайнобой", "Медузий", "Шипучка", "Бражник", "Грибозавр",
         "Пузырь", "Заварыч", "Кисляк", "Блинчик", "Сахарок", "Бульк"]

TALK = {
    "happy": ["Жизнь — как заварка: главное, не пересластить.", "Я сегодня особенно газированный 😎",
              "Ответь на вопрос в ленте — мне от этого тоже хорошо.", "Бульк. Это значит «спасибо»."],
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


def roll_mutation(ctx: Ctx) -> Mutation | None:
    """Максимум одна новая мутация за действие. Кандидаты перемешаны, чтобы порядок
    в каталоге не давал преимущества; сначала бросаем редкие."""
    size = stage_for(ctx.k.xp)["size"]
    cands = [m for m in MUTATIONS if m.stage <= size and not has_mut(ctx.k, m.code) and m.check(ctx)]
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


async def add_mutation(s, k: Kombucha, m: Mutation, at: datetime, inherited: bool = False) -> dict:
    """Повесить мутацию на гриб (с номером экземпляра) и в коллекцию юзера."""
    serial = await next_serial(s, m.code)
    entry = {"code": m.code, "at": at.isoformat(), "serial": serial}
    if inherited:
        entry["inherited"] = True
    k.mutations = [*(k.mutations or []), entry]
    new = (await s.execute(insert(KombuchaCodex).values(user_id=k.user_id, code=m.code, kombucha_name=k.name)
                           .on_conflict_do_nothing().returning(KombuchaCodex.code))).scalar() is not None
    if new and not inherited:
        await wood.earn(s, k.user_id, "mutation", m.code)
    await kb_achievements.after_mutation(s, k.user_id, m)
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


def tick(k: Kombucha, at: datetime | None = None) -> None:
    """Применить все прошедшие 12-часовые ступеньки убывания и проверить, не закис ли гриб.
    updated_at — якорь ступенек: сдвигается только на целое число периодов."""
    at = at or now()
    if not k.alive or k.frozen:
        return
    steps = int((at - k.updated_at) / PERIOD) if at > k.updated_at else 0
    for i in range(steps):
        step_at = k.updated_at + PERIOD * (i + 1)
        if k.zero_since and step_at - k.zero_since >= DEATH_AFTER:
            break
        if not k.mold and k.clean < MOLD_CLEAN_BELOW and rng.random() < MOLD_CHANCE:
            k.mold = True
        for s in STATS:
            setattr(k, s, max(getattr(k, s) - DROP[s] - (MOLD_EXTRA.get(s, 0.0) if k.mold else 0.0), 0.0))
        if k.zero_since is None and any(getattr(k, s) <= 0 for s in STATS):
            k.zero_since = step_at
    k.updated_at = k.updated_at + PERIOD * steps
    if k.zero_since and at - k.zero_since >= DEATH_AFTER:
        k.alive = False
        k.died_at = k.zero_since + DEATH_AFTER


def mood(k: Kombucha) -> str:
    if not k.alive:
        return "dead"
    if k.mold:
        return "moldy"
    if k.sweet > 95:
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


async def list_for(s, user_id: int, lock: bool = False) -> list[Kombucha]:
    q = select(Kombucha).where(Kombucha.user_id == user_id).order_by(Kombucha.id)
    if lock:
        q = q.with_for_update()
    items = list((await s.scalars(q)).all())
    for k in items:
        tick(k)
    return items


async def ensure_first(s, user: User) -> list[Kombucha]:
    """Первый гриб выдаётся бесплатно при самом первом заходе в игру
    (флаг в users.profile, чтобы выброшенный гриб не возвращался сам)."""
    user_id = user.id
    items = await list_for(s, user_id, lock=True)
    if not items and not (user.profile or {}).get("kombucha_started"):
        user.profile = {**(user.profile or {}), "kombucha_started": True}
        s.add(_new(user_id, await free_name(s)))
        await s.flush()
        await kb_achievements.after_plant(s, user_id)
        items = await list_for(s, user_id, lock=True)
    return items


async def get_own(s, user_id: int, kid: int) -> Kombucha:
    k = await s.get(Kombucha, kid, with_for_update=True)
    if k is None or k.user_id != user_id:
        raise ApiError("Гриб не найден", 404, "not_found")
    tick(k)
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
    if parent and parent.mutations:
        # наследственность: новый экземпляр одной случайной мутации родителя
        m = MUT_BY_CODE.get(rng.choice(parent.mutations).get("code"))
        if m:
            await add_mutation(s, k, m, now(), inherited=True)
    await kb_achievements.after_plant(s, user.id)
    return k


async def place_pending_sprouts(s, user: User) -> list[Kombucha]:
    """После покупки банки — сначала сажаем отростки, которые ждали."""
    planted = []
    parents = (await s.scalars(select(Kombucha).where(Kombucha.user_id == user.id, Kombucha.sprout_pending.is_(True))
                               .order_by(Kombucha.id).with_for_update())).all()
    for p in parents:
        if (await jars_info(s, user))["free"] <= 0:
            break
        planted.append(await plant(s, user, parent=p))
        p.sprout_pending = False
    return planted


async def buy_jar(s, user: User) -> dict:
    if user.jars >= wood.MAX_JARS:
        raise ApiError(f"Больше {wood.MAX_JARS} банок на подоконник не влезет", 409, "max_jars")
    await wood.spend(s, user.id, wood.PRICES["jar"], "buy_jar", f"jar{user.jars + 1}")
    user.jars += 1
    await s.flush()
    if user.jars >= wood.MAX_JARS:
        await kb_achievements.award(s, user.id, "kb_jars")
    return {"sprouts": [k.name for k in await place_pending_sprouts(s, user)]}


# ---------------------------------------------------------------- действия
def _cd_left(k: Kombucha, key: str, cd: timedelta, at: datetime) -> int:
    last = (k.cooldowns or {}).get(key)
    if not last:
        return 0
    return max(int((datetime.fromisoformat(last) + cd - at).total_seconds()), 0)


async def answers_last_day(s, user_id: int) -> int:
    return await s.scalar(select(func.count(Answer.id)).where(
        Answer.author_id == user_id, Answer.status == ContentStatus.ACTIVE,
        Answer.created_at >= now() - timedelta(hours=24))) or 0


async def debate_votes_last_day(s, user_id: int) -> int:
    return await s.scalar(select(func.count()).select_from(DebateVote).where(
        DebateVote.user_id == user_id, DebateVote.created_at >= now() - timedelta(hours=24))) or 0


async def act(s, user: User, k: Kombucha, action: str) -> dict:
    """Выполнить действие. Возвращает {message, mutation?, sprout?, wood}."""
    at = now()
    if not k.alive:
        raise ApiError("Гриб закис 😢 Перезаведи или реанимируй", 409, "kombucha_dead")
    if k.frozen:
        raise ApiError("Гриб заморожен 🧊 Разморозь, чтобы ухаживать", 409, "kombucha_frozen")
    in_danger = k.zero_since is not None
    answers_24h = debate_24h = 0
    if action == "daily":
        left = _cd_left(k, "daily", DAILY_COOLDOWN, at)
        if left:
            raise ApiError("Схема дня уже забрана", 429, "cooldown", retry_after=left)
        answers_24h = await answers_last_day(s, user.id)
        debate_24h = await debate_votes_last_day(s, user.id)
        n = min(answers_24h, 6)
        gain = 5 + 5 * n
        if k.mold:
            gain = 0
        k.xp += gain
        k.happy = min(k.happy + 10, 100.0)
        msg = (f"+{gain} опыта: ты дал {n} ответ(ов) за сутки, гриб гордится 🏆" if n
               else f"+{gain} опыта. Ответь на вопросы в ленте, завтра бонус будет больше 😉")
        if k.mold:
            msg = "С плесенью гриб не растёт 🦠 Сначала вылечи его уксусной ванной."
    elif action in ACTIONS:
        stat, add, cd, xp, msg = ACTIONS[action]
        if action == "cure" and not k.mold:
            raise ApiError("Гриб здоров, лечить нечего", 409, "not_moldy")
        left = _cd_left(k, action, cd, at)
        if left:
            raise ApiError("Рано, гриб ещё не соскучился", 429, "cooldown", retry_after=left)
        if action == "sugar" and k.sweet > STICKY_ABOVE:
            k.happy = max(k.happy - 10, 0.0)
            msg, xp = "Перебор! Гриб слипся 🥴 (−настроение)", 0
        setattr(k, stat, min(getattr(k, stat) + add, 100.0))
        quote = None
        if action == "pet":
            k.pet_count += 1
            quote = quotes.dubious()
            msg = rng.choice(TALK["sticky"]) if mood(k) == "sticky" else quotes.as_speech(quote)
        elif action == "talk":
            quote = quotes.philosophy()
            msg = quote["intro"] + " " + quotes.as_text(quote)
            k.talk_count = (k.talk_count or 0) + 1
            if k.talk_count >= 30:
                await kb_achievements.award(s, user.id, "kb_philo")
        elif action == "cure":
            k.mold = False
            await kb_achievements.award(s, user.id, "kb_mold")
        if k.mold:
            xp = 0
        elif min(getattr(k, x) for x in STATS) < LOW_STAT:
            xp //= 2
        k.xp += xp
    else:
        raise ApiError("Неизвестное действие", 400, "validation_error")

    k.cooldowns = {**(k.cooldowns or {}), action: at.isoformat()}
    k.best_xp = max(k.best_xp, k.xp)
    rescued = in_danger and all(getattr(k, st) > 0 for st in STATS)
    if rescued:
        k.zero_since = None
    today = at.astimezone(MSK).date()
    if k.last_care_day != today:
        k.last_care_day = today
        k.care_days += 1
    earned = await wood.earn(s, user.id, "kombucha_care", f"{k.id}:{action}:{at.isoformat()}")

    res: dict = {"message": msg, "mutation": None, "sprout": None, "wood": earned,
                 "quote": quote if action in ACTIONS else None}
    msk = at.astimezone(MSK)
    m = None if k.mold else roll_mutation(Ctx(action=action, k=k, hour=msk.hour, weekday=msk.weekday(), answers_24h=answers_24h,
                          debate_24h=debate_24h, was_in_danger=rescued, streak_days=user.streak_days))
    if m:
        res["mutation"] = await add_mutation(s, k, m, at)
    if stage_for(k.xp)["size"] == 6:
        await kb_achievements.award(s, user.id, "kb_legend")

    # отросток: легенда делится раз в неделю, если 7 дней за ней ухаживали (счётчик обнуляется после деления)
    if can_sprout(k, at):
        k.sprouted = True
        k.last_sprout_at = at
        k.care_days = 0
        k.sprout_count = (k.sprout_count or 0) + 1
        await wood.earn(s, user.id, "sprout", f"{k.id}:{k.sprout_count}")
        if k.sprout_count >= 4:
            await kb_achievements.award(s, user.id, "kb_split4")
        await kb_achievements.award(s, user.id, "kb_split")
        if (await jars_info(s, user))["free"] > 0:
            child = await plant(s, user, parent=k)
            res["sprout"] = {"planted": True, "name": child.name}
        else:
            k.sprout_pending = True
            res["sprout"] = {"planted": False}
    return res


def can_sprout(k: Kombucha, at: datetime | None = None) -> bool:
    at = at or now()
    return (k.alive and not k.frozen and not k.mold and not k.sprout_pending
            and stage_for(k.xp)["size"] == 6 and k.care_days >= SPROUT_CARE_DAYS
            and (k.last_sprout_at is None or at - k.last_sprout_at >= SPROUT_EVERY))


def sprout_progress(k: Kombucha, at: datetime | None = None) -> dict:
    at = at or now()
    wait = 0
    if k.last_sprout_at:
        wait = max(int((k.last_sprout_at + SPROUT_EVERY - at).total_seconds()), 0)
    return {"care_days": min(k.care_days, SPROUT_CARE_DAYS), "need_days": SPROUT_CARE_DAYS,
            "legend": stage_for(k.xp)["size"] == 6, "next_in": wait, "count": k.sprout_count or 0,
            "healthy": not k.mold}


async def restart(s, k: Kombucha, name: str | None = None) -> None:
    if k.alive:
        raise ApiError("Гриб жив, его не надо перезаводить", 409, "kombucha_alive")
    if name:
        k.name = await ensure_name(s, name, exclude_id=k.id)
    at = now()
    k.generation += 1
    k.xp = 0
    k.sweet, k.tea, k.clean, k.happy = 70.0, 70.0, 90.0, 70.0
    k.alive, k.zero_since, k.died_at, k.cooldowns = True, None, None, {}
    k.care_days, k.last_care_day, k.pet_count, k.sprouted, k.sprout_pending = 0, None, 0, False, False
    k.mold, k.last_sprout_at, k.sprout_count = False, None, 0
    k.mutations = []  # в коллекции юзера мутации остаются навсегда
    k.born_at = k.updated_at = at


async def revive(s, user: User, k: Kombucha) -> None:
    """Реанимация за $₽: опыт и мутации сохраняются, показатели — на 50."""
    if k.alive:
        raise ApiError("Гриб и так жив", 409, "kombucha_alive")
    await wood.spend(s, user.id, wood.PRICES["revive"], "revive", f"{k.id}:{k.died_at.isoformat()}")
    await kb_achievements.award(s, user.id, "kb_revive")
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
    st = stage_for(k.xp)
    return {
        "id": k.id, "name": k.name, "xp": k.xp, "best_xp": k.best_xp, "generation": k.generation, "alive": k.alive,
        "stats": {s: round(getattr(k, s)) for s in STATS}, "mood": m,
        "phrase": phrase(k),
        "stage": st, "cooldowns": cds, "dies_in": danger, "next_drop_in": next_drop_in(k, at) if k.alive else None,
        "age_days": (at - k.born_at).days, "born_at": k.born_at.isoformat(),
        "died_at": k.died_at.isoformat() if k.died_at else None,
        "mutations": muts, "care_days": k.care_days, "sprouted": k.sprouted, "sprout_pending": k.sprout_pending,
        "sprout_progress": sprout_progress(k, at), "mold": bool(k.mold),
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
    k.user_id = to_user_id
    k.price = None
    k.listed_at = None
    await s.execute(update(KombuchaTrade).where(
        KombuchaTrade.status == "pending",
        (KombuchaTrade.give_id == k.id) | (KombuchaTrade.want_id == k.id)).values(status="cancelled"))
