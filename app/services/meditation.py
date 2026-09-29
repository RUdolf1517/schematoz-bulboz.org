"""«Медитация гриба» — ритм-тапалка.

Гриб «булькает» в ритме, игрок тапает в такт. Всё, что влияет на награду, считает сервер:

1. start — сервер генерирует ритм (темп и доли) и кладёт сессию в Redis на 2 минуты.
   Клиенту уходит только расписание ударов; время старта сервер запоминает сам.
2. finish — клиент присылает моменты тапов (мс от старта). Сервер:
   * проверяет, что реально прошло не меньше длины трека (нельзя «сыграть» мгновенно);
   * одна сессия = одна награда (сессия удаляется атомарно);
   * сдвигает тапы на медианную задержку (задержка сети/экрана — до ±150 мс);
   * сопоставляет каждый удар с ближайшим свободным тапом:
     ±80 мс — «идеально» (2 очка), ±160 мс — «хорошо» (1), иначе мимо;
   * лишние тапы (спам по экрану) штрафуют точность.
3. Награда по точности: $₽ (лимит 5 медитаций в день), счастье, немного опыта
   и шанс мутации текущей стадии (с 75% точности; лимит 3 мутации на стадию действует).

Между медитациями одного гриба — пауза 5 минут.
"""
from __future__ import annotations

import json
import random
import secrets
import time

from ..errors import ApiError
from ..extensions import get_redis
from . import kombucha as kb
from . import wood
from .kombucha_mutations import MUTATIONS

SESSION_TTL = 120
COOLDOWN = 300
LEAD_MS = 2500           # отсчёт перед первым ударом
BEATS = 24
PERFECT_MS, GOOD_MS = 80, 160
MAX_SHIFT_MS = 150
MUT_FROM_ACC = 0.75
RARITY_WEIGHT = {"common": 60, "rare": 25, "epic": 11, "legendary": 4}
TEMPOS = [(60, "Дыхание дзен"), (66, "Спокойный чайник"), (72, "Тихое брожение"), (80, "Бодрый улун"), (88, "Газированный")]

rng = random.Random()


def _now_ms() -> int:
    return int(time.time() * 1000)


def make_track(seed: int) -> dict:
    """Ритм: темп + 24 удара. В основном ровные доли, иногда пауза или «двойной бульк» (полдоли)."""
    r = random.Random(seed)
    bpm, title = r.choice(TEMPOS)
    beat = 60000 / bpm
    t, beats = float(LEAD_MS), []
    while len(beats) < BEATS:
        beats.append(round(t))
        roll = r.random()
        if roll < 0.15 and len(beats) > 4:
            t += beat / 2          # двойной бульк
        elif roll < 0.25 and len(beats) > 4:
            t += beat * 2          # пауза — не торопись
        else:
            t += beat
    return {"bpm": bpm, "title": title, "beats": beats, "length": beats[-1] + 600}


def start(user_id: int, k) -> dict:
    if not k.alive or k.frozen:
        raise ApiError("Медитировать может только живой и незамороженный гриб", 400, "kb_unavailable")
    r = get_redis()
    left = r.ttl(f"med:cd:{k.id}")
    if left and left > 0:
        raise ApiError(f"Гриб ещё отдыхает после медитации: {left // 60} мин {left % 60} с", 429, "kb_cooldown",
                       retry_after=left)
    token = secrets.token_urlsafe(16)
    seed = rng.getrandbits(32)
    track = make_track(seed)
    r.set(f"med:{token}", json.dumps({"uid": user_id, "kid": k.id, "seed": seed, "t0": _now_ms()}), ex=SESSION_TTL)
    return {"token": token, **track, "perfect_ms": PERFECT_MS, "good_ms": GOOD_MS}


def score(beats: list[int], taps: list[int]) -> dict:
    """Сопоставить удары и тапы. Возвращает точность 0..1 и разбивку."""
    taps = sorted(t for t in taps if isinstance(t, (int, float)))[: len(beats) * 3]
    # медианная задержка по тапам, близким к ударам — компенсация лага экрана/сети
    near = []
    for b in beats:
        d = min((t - b for t in taps), key=abs, default=None)
        if d is not None and abs(d) <= 250:
            near.append(d)
    shift = 0
    if near:
        near.sort()
        shift = max(-MAX_SHIFT_MS, min(MAX_SHIFT_MS, near[len(near) // 2]))
    free = [t - shift for t in taps]
    perfect = good = 0
    for b in beats:
        if not free:
            break
        i = min(range(len(free)), key=lambda j: abs(free[j] - b))
        d = abs(free[i] - b)
        if d <= PERFECT_MS:
            perfect += 1
        elif d <= GOOD_MS:
            good += 1
        else:
            continue
        free.pop(i)
    extra = len(free)                                   # тапы мимо тактов
    miss = len(beats) - perfect - good
    pts = perfect * 2 + good - extra * 0.5
    acc = max(0.0, min(1.0, pts / (2 * len(beats))))
    return {"accuracy": round(acc, 3), "perfect": perfect, "good": good, "miss": miss, "extra": extra, "shift_ms": shift}


def _roll_mutation(k, acc: float):
    if acc < MUT_FROM_ACC:
        return None
    size = kb.stage_for(k.xp)["size"]
    if kb.stage_mut_counts(k).get(size, 0) >= kb.MAX_MUT_PER_STAGE:
        return None
    chance = 0.03 + 0.12 * (acc - MUT_FROM_ACC) / (1 - MUT_FROM_ACC)     # 3% … 15%
    if rng.random() >= chance:
        return None
    pool = [m for m in MUTATIONS if m.stage == size and not kb.has_mut(k, m.code)]
    if not pool:
        return None
    return rng.choices(pool, weights=[RARITY_WEIGHT[m.rarity] for m in pool])[0]


async def finish(s, user, k, token: str, taps) -> dict:
    r = get_redis()
    raw = r.getdel(f"med:{token}") if hasattr(r, "getdel") else None
    if raw is None and not hasattr(r, "getdel"):
        raw = r.get(f"med:{token}")
        r.delete(f"med:{token}")
    if not raw:
        raise ApiError("Сессия медитации не найдена или уже завершена", 400, "med_session")
    sess = json.loads(raw)
    if sess["uid"] != user.id or sess["kid"] != k.id:
        raise ApiError("Это чужая медитация", 403, "forbidden")
    track = make_track(sess["seed"])
    if _now_ms() - sess["t0"] < track["length"] - 400:
        raise ApiError("Слишком быстро — медитацию нужно пройти до конца", 400, "med_too_fast")
    if not isinstance(taps, list) or len(taps) > BEATS * 4:
        raise ApiError("Некорректные тапы", 400, "validation_error")
    res = score(track["beats"], taps)
    acc = res["accuracy"]
    r.set(f"med:cd:{k.id}", 1, ex=COOLDOWN)

    kb.tick(k)
    happy = round(25 * acc)
    xp = round(12 * acc)
    k.happy = min(100.0, k.happy + happy)
    if not k.mold:
        k.xp += xp
        k.best_xp = max(k.best_xp, k.xp)
    earned = await wood.earn(s, user.id, "meditation", token, amount=round(10 * acc))
    m = _roll_mutation(k, acc)
    mut = await kb.add_mutation(s, k, m, kb.now()) if m else None
    if acc >= 0.95:
        from . import kombucha_achievements as ach
        await ach.award(s, user.id, "kb_zen")
    return {**res, "happy": happy, "xp": xp if not k.mold else 0, "wood": earned, "mutation": mut,
            "cooldown": COOLDOWN, "grade": grade(acc)}


def grade(acc: float) -> str:
    if acc >= 0.95:
        return "Просветление 🪷"
    if acc >= 0.8:
        return "Гармония 🧘"
    if acc >= 0.6:
        return "Лёгкое брожение 🫧"
    if acc >= 0.3:
        return "Суета сует 🌀"
    return "Гриб в недоумении 🍄"
