"""Достижения «Чайного гриба». Это обычные бейджи сайта (каталог — gamification.BADGES),
поэтому они видны в профиле и попадают в витрину."""
from __future__ import annotations

from sqlalchemy import func, select

from ..models import KombuchaCodex

KB_BADGES = [
    ("kb_first", "Грибовод", "🍄", "Завёл первый чайный гриб"),
    ("kb_first_mut", "Мутант", "🧬", "Первая мутация гриба"),
    ("kb_mut10", "Генетик", "🔬", "10 разных мутаций в коллекции"),
    ("kb_mut50", "Селекционер", "🧪", "50 разных мутаций в коллекции"),
    ("kb_mut120", "Половина пути", "🧫", "120 разных мутаций в коллекции"),
    ("kb_mut240", "Полная коллекция", "🏆", "Все 240 мутаций"),
    ("kb_split4", "Династия", "🌳", "Один гриб разделился 4 раза"),
    ("kb_mold", "Санэпидстанция", "🧪", "Вылечил гриб от плесени"),
    ("kb_philo", "Философ", "📜", "Поговорил с грибом 30 раз"),
    ("kb_gift", "Щедрая душа", "🎁", "Подарил гриб"),
    ("task_create", "Работодатель", "📋", "Создал первое задание"),
    ("task_done", "Исполнитель", "✅", "Выполнил первое задание"),
    ("task_done10", "Фрилансер", "💼", "Выполнил 10 заданий"),
    ("wall_first", "Стеночник", "📝", "Написал на чужой стене"),
    ("kb_epic", "Эпичная находка", "💜", "Выпала эпическая мутация"),
    ("kb_legendary", "Легендарная находка", "🌟", "Выпала легендарная мутация"),
    ("kb_legend", "Легендарный грибовод", "👑", "Гриб дорос до «Легенды трёхлитровой банки»"),
    ("kb_split", "Деление", "🌱", "Гриб разделился и дал отросток"),
    ("kb_jars", "Подоконник", "🫙", "Собрал все 5 банок"),
    ("kb_revive", "Некромант", "💉", "Реанимировал закисший гриб"),
    ("kb_freeze", "Морозилка", "🧊", "Заморозил гриб и выставил на полку"),
    ("kb_trade", "Бартер", "🤝", "Обменялся грибами"),
    ("kb_sale", "Барыга", "💰", "Продал гриб на рынке"),
    ("kb_buy", "Коллекционер", "🛒", "Купил гриб на рынке"),
    ("kb_rich", "Деревянный миллионер", "🪵", "Накопил 1000 $₽"),
]
KB_CODES = [c for c, *_ in KB_BADGES]


async def award(s, user_id: int, code: str) -> bool:
    from .gamification import award as _award
    return await _award(s, user_id, code)


async def after_plant(s, user_id: int) -> None:
    await award(s, user_id, "kb_first")


async def after_mutation(s, user_id: int, m) -> None:
    await award(s, user_id, "kb_first_mut")
    if m.rarity == "epic":
        await award(s, user_id, "kb_epic")
    if m.rarity == "legendary":
        await award(s, user_id, "kb_legendary")
    n = await s.scalar(select(func.count()).select_from(KombuchaCodex).where(KombuchaCodex.user_id == user_id)) or 0
    for need, code in ((10, "kb_mut10"), (50, "kb_mut50"), (120, "kb_mut120"), (240, "kb_mut240")):
        if n >= need:
            await award(s, user_id, code)


async def check_rich(s, user_id: int, balance: int) -> None:
    if balance >= 1000:
        await award(s, user_id, "kb_rich")
