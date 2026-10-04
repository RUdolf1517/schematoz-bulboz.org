"""Дневник чайного гриба. Пишет сам гриб, от первого лица: «родился», «вырос», «мутировал», «чуть не помер».

log() синхронный (просто s.add) — его можно звать откуда угодно внутри session_scope.
Смерть tick() фиксирует без сессии, поэтому её досчитываем при чтении (synthetic) и
записываем по-настоящему в момент реанимации/перезапуска (flush_death).
"""
from __future__ import annotations

import random
from datetime import datetime

from sqlalchemy import select

from ..models import Kombucha, KombuchaEvent

rng = random.Random()
PAGE = 50

LINES = {
    "born": ["Я родился. Банка тесная, но своя.", "Первый день в банке. Пахнет чаем и надеждой.",
             "Появился на свет. Пока что я блинчик, но с амбициями."],
    "sprout_born": ["Я отпочковался от {parent}. Весь в родителя, только моложе."],
    "sprout": ["У меня родился отросток — {child}. Теперь я родитель, ответственность давит.",
               "Отпочковал {child}. Пусть растёт и не повторяет моих ошибок."],
    "stage": ["Я вырос: теперь я «{stage}».", "Новая стадия — «{stage}». Чувствую себя солиднее.",
              "Дорос до «{stage}». Банка вдруг стала маловата."],
    "mutation": ["Мутировал: {emoji} «{title}» ({rarity}, #{serial}). Мама бы не узнала.",
                 "Проснулся с новой мутацией — {emoji} «{title}» ({rarity}, #{serial})."],
    "inherited": ["Унаследовал от родителя {emoji} «{title}» (#{serial})."],
    "rescued": ["Чуть не помер — {hours} ч на нуле. Спасли в последний момент, я всё помню.",
                "Был на волоске ({hours} ч без сил). Откачали. Ставлю свечку за хозяина."],
    "died": ["Закис. Если читаешь это — поливай своих грибов вовремя."],
    "revived": ["Меня реанимировали за {price} $₽. Видел свет в конце банки."],
    "restart": ["Начал жизнь заново. Поколение {gen}. Прошлое оставил в старом чае."],
    "cured": ["Вылечили от плесени уксусной ванной. Щиплет, но я снова чистый."],
    "frozen": ["Меня заморозили. Лежу на полке, не старею — почти как в криокамере."],
    "unfrozen": ["Разморозили! Потягиваюсь, пускаю пузыри."],
    "moved": ["Переехал к @{to}{how}. Новая банка, новая жизнь."],
    "renamed": ["Теперь меня зовут «{new}». Раньше был «{old}», но это в прошлом."],
    "pets": ["Меня погладили уже {n} раз. Я ручной."],
    "game": ["Сыграли в «{title}» на {acc}%. Я был великолепен."],
    "haunted": ["Я исчез из банки. Не ищи меня в темноте — я уже ищу тебя.",
                "На стекле паутина. Чая меньше не стало, а меня — да.",
                "Кто-то стучал по банке изнутри. Я не отвечал. Почти."],
    "halloween_mutation": ["Под плесенью проступила мутация «{title}». Она шевелится, когда никто не смотрит.",
                           "Я изменился: «{title}». Это не навсегда. Наверное.",
                           "Ночью у меня появилась «{title}». Я не помню, чтобы соглашался."],
}
EMOJI = {"born": "🐣", "sprout_born": "🌱", "sprout": "🌱", "stage": "📈", "mutation": "🧬", "inherited": "🧬",
         "rescued": "🚑", "died": "🪦", "revived": "⚡", "restart": "🔄", "cured": "🧴", "frozen": "🧊",
         "unfrozen": "🔥", "moved": "📦", "renamed": "🏷️", "pets": "🤲", "game": "🎮",
         "haunted": "🕸️", "halloween_mutation": "👁️"}
PET_MILESTONES = (10, 50, 100, 250, 500, 1000)


def log(s, k: Kombucha, kind: str, at: datetime | None = None, **data) -> KombuchaEvent:
    text = rng.choice(LINES[kind]).format(**data)[:300]
    ev = KombuchaEvent(kombucha_id=k.id, kind=kind, body=text, emoji=EMOJI[kind], data=data)
    if at is not None:
        ev.at = at
    s.add(ev)
    return ev


def stage_check(s, k: Kombucha, old_xp: int) -> None:
    from .kombucha import stage_for
    a, b = stage_for(old_xp), stage_for(k.xp)
    if b["size"] > a["size"]:
        log(s, k, "stage", stage=b["title"])


def flush_death(s, k: Kombucha) -> None:
    """Перед реанимацией/перезапуском записать смерть в дневник по-настоящему."""
    if k.died_at:
        log(s, k, "died", at=k.died_at)


async def read(s, k: Kombucha, before: int | None = None) -> dict:
    q = select(KombuchaEvent).where(KombuchaEvent.kombucha_id == k.id)
    if before:
        q = q.where(KombuchaEvent.id < before)
    rows = (await s.execute(q.order_by(KombuchaEvent.id.desc()).limit(PAGE + 1))).scalars().all()
    items = [{"id": e.id, "kind": e.kind, "emoji": e.emoji, "text": e.body, "at": e.at.isoformat()} for e in rows[:PAGE]]
    if not before and not k.alive and k.died_at:            # свежая смерть — ещё не записана
        items.insert(0, {"id": None, "kind": "died", "emoji": EMOJI["died"], "text": LINES["died"][0],
                         "at": k.died_at.isoformat()})
    return {"items": items, "next": rows[PAGE - 1].id if len(rows) > PAGE else None}
