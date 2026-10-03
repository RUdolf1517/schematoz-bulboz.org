"""Мини-игры гриба: «Налей и не пролей», «Память гриба», «Сахар или соль», «Отгони мушек».

Общий принцип (как у «Медитации»): игру генерирует сервер из seed, сессия лежит в Redis,
результат пересчитывает сервер по присланным действиям игрока — клиент не присылает «очки».

* pour    — 6 раундов: держишь палец — льётся чай, отпускаешь — стоп. Уровень и положение метки считает
            сервер по длительности нажатия. С каждым раундом помех больше: банка трясётся (метка ездит),
            струя дёргается, чай пенится, гаснет свет, метка прячется, допуск сужается.
* memory  — Simon Says на 4 банках. Сервер раскрывает цепочку по одному шагу: следующий элемент
            клиент получает только после правильного повтора текущей (подсмотреть всю цепочку нельзя).
* sugar   — сверху падают предметы, тапать только сахар. Тап засчитывается, только если в этот момент
            предмет действительно был на экране (окно появления — у сервера).
* flies   — мушки летят к банке, тапни до посадки. 3 севшие — конец. Сервер сам проигрывает партию
            по тапам и знает, когда она закончилась.

Общая защита: нельзя закончить быстрее, чем физически длится игра; одна сессия — одна награда;
лимит действий; кулдаун 3 минуты на игру для гриба.

Награда по точности 0..1: $₽ (общий лимит — 10 игр в день на все четыре игры, до 8 $₽ за игру),
счастье, профильный показатель гриба (чистота/сахар/заварка), опыт и шанс мутации (с 75%).
"""
from __future__ import annotations

import json
import math
import random
import secrets
import time

from ..errors import ApiError
from ..extensions import get_redis
from . import antibot
from . import kombucha as kb
from . import kombucha_diary as diary
from . import wood
from .meditation import _roll_mutation, grade

SESSION_TTL = 180
COOLDOWN = 180
MUT_FROM_ACC = 0.75

GAMES = {
    # код: (название, эмодзи, какой показатель гриба поднимает, описание)
    "pour": ("Налей и не пролей", "🫖", "tea", "Банка трясётся, свет гаснет, чай пенится. Отпусти ровно на метке."),
    "memory": ("Память гриба", "🧠", "happy", "Гриб булькает по банкам — повтори цепочку."),
    "sugar": ("Сахар или соль", "🍬", "sweet", "Тапай только сахар. Соль, перец и чеснок — мимо!"),
    "flies": ("Отгони мушек", "🪰", "clean", "Тапни мушку, пока она не села на банку. Три севшие — конец."),
}

rng = random.Random()


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------- генераторы (детерминированы по seed)
POUR_ROUNDS = 6
POUR_TOL = 0.08
# Помехи — растут с каждым раундом. Все параметры из seed, сервер считает по тем же формулам, что и клиент.
#   shake — банка трясётся, метка ездит вверх-вниз (цель = метка В МОМЕНТ отпускания)
#   pulse — струя дёргается: то хлещет, то капает
#   foam  — чай пенится: после отпускания уровень ещё подрастёт на f·уровень
#   dark  — в середине налива гаснет свет (моргает лампочка)
#   hide  — метка исчезает, как только начал лить (запоминай!)
#   tiny  — узкая метка: допуск меньше
POUR_MODS = ("shake", "pulse", "foam", "dark", "hide", "tiny")
POUR_MODS_PER_ROUND = (1, 1, 2, 2, 3, 4)


def pour_level(rd: dict, ms: float) -> float:
    """Уровень во время налива: разгон струи + пульсация. Без пены."""
    t = max(0.0, ms) / 1000
    lvl = rd["rate"] * t + rd["accel"] * t * t
    pu = rd.get("pulse")
    if pu:
        w = pu["w"]
        lvl += rd["rate"] * pu["p"] * (math.sin(w * t - math.pi / 2) + 1) / w  # ∫ p·(1 - cos wt)
    return lvl


def pour_final(rd: dict, ms: float) -> float:
    """Итоговый уровень после того, как осядет/поднимется пена."""
    return pour_level(rd, ms) * (1 + (rd.get("foam") or {}).get("f", 0.0))


def pour_target(rd: dict, ms: float) -> float:
    """Где метка в момент ms от начала налива (трясётся — ездит)."""
    sh = rd.get("shake")
    if not sh:
        return rd["target"]
    return rd["target"] + sh["amp"] * math.sin(2 * math.pi * max(0.0, ms) / sh["period"] + sh["phase"])


def gen_pour(seed: int) -> dict:
    r = random.Random(seed)
    rounds = []
    for i in range(POUR_ROUNDS):
        mods = r.sample(POUR_MODS, POUR_MODS_PER_ROUND[i])
        if i == 0:
            mods = ["shake"]                                   # сразу даём понять, что будет весело
        rd = {"target": round(r.uniform(0.45, 0.78), 3), "rate": round(r.uniform(0.24, 0.34) + i * 0.035, 3),
              "accel": round(r.uniform(0.02, 0.06) + i * 0.012, 3),
              "jar": r.choice(["банка", "кружка", "пиала", "бутыль", "стакан"]), "mods": mods,
              "tol": round(POUR_TOL * (0.6 if "tiny" in mods else 1.0), 3)}
        if "shake" in mods:
            rd["shake"] = {"amp": round(r.uniform(0.05, 0.09) + i * 0.008, 3), "period": round(r.uniform(900, 1500) - i * 60),
                           "phase": round(r.uniform(0, 2 * math.pi), 3)}
        if "pulse" in mods:
            rd["pulse"] = {"p": round(r.uniform(0.6, 0.95), 3), "w": round(2 * math.pi / r.uniform(0.45, 0.8), 3)}
        if "foam" in mods:
            rd["foam"] = {"f": round(r.uniform(0.08, 0.2), 3)}
        if "dark" in mods:
            rd["dark"] = {"at": round(r.uniform(350, 900)), "dur": round(r.uniform(600, 1100))}
        rounds.append(rd)
    return {"rounds": rounds, "tolerance": POUR_TOL}


MEMORY_LEN = 12


def gen_memory(seed: int) -> list[int]:
    r = random.Random(seed)
    seq = [r.randrange(4)]
    while len(seq) < MEMORY_LEN:
        nxt = r.randrange(4)
        if len(seq) >= 2 and nxt == seq[-1] == seq[-2]:
            nxt = (nxt + 1) % 4          # без трёх одинаковых подряд
        seq.append(nxt)
    return seq


SUGAR_ITEMS = 40
BAD = {"salt": "🧂", "pepper": "🌶️", "garlic": "🧄", "onion": "🧅"}


def gen_sugar(seed: int) -> dict:
    r = random.Random(seed)
    items, t = [], 1800
    for i in range(SUGAR_ITEMS):
        kind = "sugar" if r.random() < 0.6 else r.choice(list(BAD))
        fall = round(3200 - i * 40)                       # падают всё быстрее
        items.append({"id": i, "t": t, "lane": r.randrange(5), "kind": kind, "fall": fall})
        t += round(r.uniform(380, 700) - i * 4)
    return {"items": items, "length": items[-1]["t"] + items[-1]["fall"] + 300}


FLIES = 45
LIVES = 3


def gen_flies(seed: int) -> dict:
    r = random.Random(seed)
    flies, t = [], 1500
    for i in range(FLIES):
        dur = round(max(1100, 3200 - i * 50))             # темп растёт
        flies.append({"id": i, "t": t, "dur": dur, "angle": round(r.uniform(0, 360), 1)})
        t += round(max(350, r.uniform(700, 1100) - i * 12))
    return {"flies": flies, "lives": LIVES, "length": max(f["t"] + f["dur"] for f in flies) + 300}


# ---------------------------------------------------------------- подсчёт (чистые функции — тестируются отдельно)
def score_pour(game: dict, holds: list) -> dict:
    if not isinstance(holds, list) or len(holds) != POUR_ROUNDS:
        raise ApiError(f"Нужно {POUR_ROUNDS} наливов", 400, "validation_error")
    rounds, total = [], 0.0
    for rd, ms in zip(game["rounds"], holds):
        if not isinstance(ms, (int, float)) or ms < 0 or ms > 20000:
            raise ApiError("Некорректный налив", 400, "validation_error")
        during, lvl, target = pour_level(rd, ms), pour_final(rd, ms), pour_target(rd, ms)
        spilled = during >= 1.0 or lvl >= 1.0
        err = abs(lvl - target)
        pts = 0.0 if spilled else max(0.0, 1 - err / rd["tol"])
        total += pts
        rounds.append({"level": round(min(lvl, 1.2), 3), "target": round(target, 3), "spilled": spilled,
                       "points": round(pts, 3)})
    return {"accuracy": round(total / POUR_ROUNDS, 3), "rounds": rounds, "min_ms": sum(holds)}


def score_sugar(game: dict, taps: list) -> dict:
    items = {it["id"]: it for it in game["items"]}
    seen, good, bad = set(), 0, 0
    for tp in taps[: SUGAR_ITEMS * 2]:
        if not isinstance(tp, dict):
            continue
        it = items.get(tp.get("id"))
        t = tp.get("t")
        if it is None or it["id"] in seen or not isinstance(t, (int, float)):
            continue
        if not (it["t"] - 50 <= t <= it["t"] + it["fall"] + 50):     # предмета в этот момент не было на экране
            continue
        seen.add(it["id"])
        if it["kind"] == "sugar":
            good += 1
        else:
            bad += 1
    sugars = sum(1 for it in game["items"] if it["kind"] == "sugar")
    acc = max(0.0, (good - bad * 2) / max(sugars, 1))
    return {"accuracy": round(min(acc, 1.0), 3), "caught": good, "wrong": bad, "missed": sugars - good}


def score_flies(game: dict, taps: list) -> dict:
    """Проигрываем партию: мушка отогнана, если по ней тапнули между вылетом и посадкой."""
    tapped = {}
    for tp in taps[: FLIES * 2]:
        if isinstance(tp, dict) and isinstance(tp.get("t"), (int, float)) and tp.get("id") not in tapped:
            tapped[tp.get("id")] = tp["t"]
    lives, swat, end = LIVES, 0, None
    for f in sorted(game["flies"], key=lambda f: f["t"] + f["dur"]):
        land = f["t"] + f["dur"]
        if end is not None and f["t"] > end:
            break
        tt = tapped.get(f["id"])
        if tt is not None and f["t"] - 50 <= tt <= land + 50 and (end is None or tt <= end):
            swat += 1
        else:
            lives -= 1
            if lives <= 0:
                end = land
                break
    return {"accuracy": round(swat / FLIES, 3), "swatted": swat, "landed": LIVES - max(lives, 0),
            "min_ms": end if end is not None else game["length"]}


# ---------------------------------------------------------------- сессии
def _cd_key(kid: int, game: str) -> str:
    return f"mg:cd:{kid}:{game}"


def start(user_id: int, k, game: str) -> dict:
    if game not in GAMES:
        raise ApiError("Нет такой игры", 404, "not_found")
    if not k.alive or k.frozen:
        raise ApiError("Играть может только живой и незамороженный гриб", 400, "kb_unavailable")
    r = get_redis()   # играть можно сколько угодно — ограничена только награда (см. reward)
    token, seed = secrets.token_urlsafe(16), rng.getrandbits(32)
    sess = {"uid": user_id, "kid": k.id, "game": game, "seed": seed, "t0": _now_ms()}
    out: dict = {"token": token, "game": game, "title": GAMES[game][0]}
    if game == "pour":
        out.update(gen_pour(seed))
    elif game == "memory":
        sess.update(step=1, last=_now_ms())
        out.update(seq=gen_memory(seed)[:1], total=MEMORY_LEN)
    elif game == "sugar":
        out.update(gen_sugar(seed), bad=BAD)
    elif game == "flies":
        out.update(gen_flies(seed))
    r.set(f"mg:{token}", json.dumps(sess), ex=SESSION_TTL)
    return out


def _load(token: str, user_id: int, kid: int, game: str, consume: bool) -> dict:
    r = get_redis()
    key = f"mg:{token}"
    raw = r.getdel(key) if consume else r.get(key)
    if not raw:
        raise ApiError("Игра не найдена или уже завершена", 400, "mg_session")
    sess = json.loads(raw)
    if sess["uid"] != user_id or sess["kid"] != kid or sess["game"] != game:
        if consume:
            r.set(key, raw, ex=SESSION_TTL)                   # чужой токен не должен сжигать чужую игру
        raise ApiError("Это чужая игра", 403, "forbidden")
    return sess


def memory_step(user_id: int, k, token: str, inputs) -> dict:
    """Проверить повтор цепочки. Верно — отдаём следующий элемент; ошибка или конец — игра окончена."""
    sess = _load(token, user_id, k.id, "memory", consume=False)
    seq, n = gen_memory(sess["seed"]), sess["step"]
    if _now_ms() - sess["last"] < n * 350:                  # цепочку сначала надо хотя бы увидеть
        raise ApiError("Слишком быстро", 400, "mg_too_fast")
    ok = isinstance(inputs, list) and inputs == seq[:n]
    if ok and n < MEMORY_LEN:
        sess.update(step=n + 1, last=_now_ms())
        get_redis().set(f"mg:{token}", json.dumps(sess), ex=SESSION_TTL)
        return {"ok": True, "done": False, "seq": seq[: n + 1]}
    reached = n if ok else n - 1
    sess.update(reached=reached, over=True)                   # итог фиксирует сервер
    get_redis().set(f"mg:{token}", json.dumps(sess), ex=SESSION_TTL)
    return {"ok": ok, "done": True, "reached": reached}


async def finish(s, user, k, game: str, token: str, data: dict) -> dict:
    sess = _load(token, user.id, k.id, game, consume=True)
    seed, elapsed = sess["seed"], _now_ms() - sess["t0"]
    if game == "pour":
        res = score_pour(gen_pour(seed), data.get("holds"))
        min_ms = res.pop("min_ms") + POUR_ROUNDS * 300
    elif game == "memory":
        # сколько шагов пройдено — знает только сервер (клиент может лишь бросить игру раньше)
        reached = sess["reached"] if sess.get("over") else sess["step"] - 1
        res = {"accuracy": round(reached / MEMORY_LEN, 3), "reached": reached, "total": MEMORY_LEN}
        min_ms = sum(i * 350 for i in range(1, reached + 1))
    elif game == "sugar":
        g = gen_sugar(seed)
        taps = data.get("taps") or []
        if not isinstance(taps, list):
            raise ApiError("Некорректные тапы", 400, "validation_error")
        res = score_sugar(g, taps)
        min_ms = g["length"] - 500
    elif game == "flies":
        taps = data.get("taps") or []
        if not isinstance(taps, list):
            raise ApiError("Некорректные тапы", 400, "validation_error")
        res = score_flies(gen_flies(seed), taps)
        min_ms = res.pop("min_ms") - 500
    else:
        raise ApiError("Нет такой игры", 404, "not_found")
    if elapsed < min_ms:
        raise ApiError("Слишком быстро — игру нужно пройти по-честному", 400, "mg_too_fast")
    res = _antibot(user.id, game, seed, data, res)
    return await reward(s, user, k, game, token, res)


def bot_reason(game: str, seed: int, data: dict, res: dict) -> str | None:
    """Поведенческие признаки автокликера (см. services/antibot.py)."""
    reason = antibot.check_client(data.get("meta"))
    taps = data.get("taps") if isinstance(data.get("taps"), list) else []
    if game == "sugar":
        items = {it["id"]: it for it in gen_sugar(seed)["items"]}
        reac = [tp["t"] - items[tp["id"]]["t"] for tp in taps
                if isinstance(tp, dict) and tp.get("id") in items and isinstance(tp.get("t"), (int, float))]
        reason = antibot.verdict(reason, antibot.check_reactions(reac))
    elif game == "flies":
        flies = {f["id"]: f for f in gen_flies(seed)["flies"]}
        reac = [tp["t"] - flies[tp["id"]]["t"] for tp in taps
                if isinstance(tp, dict) and tp.get("id") in flies and isinstance(tp.get("t"), (int, float))]
        reason = antibot.verdict(reason, antibot.check_reactions(reac))
    elif game == "pour":
        # с помехами 6 идеальных наливов подряд человеку не выдать
        if res.get("rounds") and all(r["points"] >= 0.99 for r in res["rounds"]):
            reason = antibot.verdict(reason, "perfect_pour")
    return reason


def _antibot(user_id: int, game: str, seed: int, data: dict, res: dict) -> dict:
    reason = None if antibot.disabled() else bot_reason(game, seed, data, res)
    if not reason:
        return res
    n = antibot.register(user_id, reason)
    return {**res, "accuracy": 0.0, "suspect": reason, "bot_flags": n}


async def reward(s, user, k, game: str, token: str, res: dict) -> dict:
    acc = res["accuracy"]
    r = get_redis()
    left = r.ttl(_cd_key(k.id, game))
    if left and left > 0:   # тренировка: результат считаем, награду — нет
        return {**res, "game": game, "grade": grade(acc), "practice": True, "reward_in": int(left),
                "happy": 0, "stat": GAMES[game][2], "boost": 0, "xp": 0, "wood": 0, "mutation": None, "mut_why": "practice",
                "cooldown": COOLDOWN}
    if res.get("suspect"):   # бот не сжигает окно награды
        acc = 0.0
    else:
        r.set(_cd_key(k.id, game), 1, ex=COOLDOWN)
    kb.tick(k)
    stat = GAMES[game][2]
    happy = round(20 * acc)
    boost = round(15 * acc)
    k.happy = min(100.0, k.happy + happy)
    if stat != "happy":
        cap = 90.0 if stat == "sweet" else 100.0          # сахарную кому игрой не устроить
        setattr(k, stat, min(cap, max(getattr(k, stat), min(cap, getattr(k, stat) + boost))))
    xp = 0 if k.mold else round(10 * acc)
    old_xp = k.xp
    k.xp += xp
    k.best_xp = max(k.best_xp, k.xp)
    if all(getattr(k, st) > 0 for st in kb.STATS):
        k.zero_since = None
    earned = await wood.earn(s, user.id, "minigame", f"{game}:{token}", amount=round(8 * acc))
    m = _roll_mutation(k, acc)
    mut = await kb.add_mutation(s, k, m, kb.now()) if m else None
    diary.stage_check(s, k, old_xp)
    if acc >= 0.95:
        diary.log(s, k, "game", title=GAMES[game][0], acc=round(acc * 100))
    size = kb.stage_for(k.xp)["size"]
    why = ("got" if mut else "low" if acc < MUT_FROM_ACC
           else "limit" if kb.stage_mut_counts(k).get(size, 0) >= kb.MAX_MUT_PER_STAGE else "luck")
    return {**res, "game": game, "grade": grade(acc), "happy": happy, "stat": stat, "boost": boost if stat != "happy" else 0,
            "xp": xp, "wood": earned, "mutation": mut, "mut_why": why, "cooldown": COOLDOWN}


def catalog() -> list[dict]:
    return [{"code": "meditation", "title": "Медитация гриба", "emoji": "🧘", "about": "Тапай в такт бульканью гриба."}] + \
           [{"code": c, "title": t, "emoji": e, "about": a} for c, (t, e, _, a) in GAMES.items()]
