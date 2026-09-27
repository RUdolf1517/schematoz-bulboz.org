"""Каталог мутаций «Чайного гриба»: по 20 на каждую из 6 стадий = 120.

Как подарки в Telegram: у мутации есть редкость, а у каждого выпавшего экземпляра —
порядковый номер на весь сайт («Золотой #17»). Экземпляр живёт на грибе навсегда
и переходит вместе с грибом при продаже/обмене.

Коды 20 первых мутаций (sparkle, night, …, phoenix) сохранены — они уже могли выпасть.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

RARITY = {  # код: (название, шанс за подходящее действие)
    "common": ("Обычная", 0.06),
    "rare": ("Редкая", 0.025),
    "epic": ("Эпическая", 0.01),
    "legendary": ("Легендарная", 0.004),
}
RARITY_ORDER = ["legendary", "epic", "rare", "common"]


@dataclass(frozen=True)
class Ctx:
    action: str
    k: object                 # Kombucha
    hour: int                 # час по Москве
    weekday: int = 0          # 0 = понедельник
    answers_24h: int = 0
    debate_24h: int = 0
    was_in_danger: bool = False
    streak_days: int = 0


def _stats(c: Ctx):
    return [c.k.sweet, c.k.tea, c.k.clean, c.k.happy]


# условие: (функция, подсказка для коллекции)
CONDS: dict[str, tuple[Callable[[Ctx], bool], str]] = {
    "any": (lambda c: True, "Просто ухаживай"),
    "sugar": (lambda c: c.action == "sugar", "Корми сахаром"),
    "tea": (lambda c: c.action == "tea", "Подливай заварку"),
    "clean": (lambda c: c.action == "clean", "Мой банку"),
    "pet": (lambda c: c.action == "pet", "Болтай с грибом"),
    "daily": (lambda c: c.action == "daily", "Забирай «Схему дня»"),
    "night": (lambda c: 0 <= c.hour < 5, "Ночью, с 0 до 5"),
    "morning": (lambda c: 5 <= c.hour < 10, "Утром, с 5 до 10"),
    "evening": (lambda c: 18 <= c.hour < 24, "Вечером, с 18 до 24"),
    "weekend": (lambda c: c.weekday >= 5, "По выходным"),
    "happy": (lambda c: min(_stats(c)) >= 60, "Когда все показатели 60+"),
    "low": (lambda c: min(_stats(c)) < 20, "Когда какой-то показатель ниже 20"),
    "all_high": (lambda c: min(_stats(c)) >= 80, "Идеальный уход: всё 80+"),
    "gen2": (lambda c: c.k.generation >= 2, "Гриб второго поколения и старше"),
    "sprout": (lambda c: c.k.parent_id is not None, "Только у отростков"),
    "streak": (lambda c: c.streak_days >= 3, "Стрик ответов 3+ дня"),
    "answers": (lambda c: c.action == "daily" and c.answers_24h >= 3, "«Схема дня» после 3+ ответов"),
    "debate": (lambda c: c.action == "daily" and c.debate_24h >= 1, "«Схема дня» после голоса в холиваре"),
    "many_muts": (lambda c: len(c.k.mutations or []) >= 5, "Когда у гриба уже 5+ мутаций"),
    "sweet_high": (lambda c: c.action == "sugar" and c.k.sweet > 80, "Сахар, когда и так сладко"),
    "tea_low": (lambda c: c.action == "tea" and c.k.tea < 30, "Заварка, когда её почти нет"),
    "clean_high": (lambda c: c.action == "clean" and c.k.clean > 70, "Мыть и так чистую банку"),
    "chatty": (lambda c: c.action == "pet" and c.k.pet_count >= 50, "Поболтать 50+ раз"),
    "rescued": (lambda c: c.was_in_danger, "Спасти гриб, когда показатель был на нуле"),
}


@dataclass(frozen=True)
class Mutation:
    code: str
    title: str
    emoji: str
    stage: int
    rarity: str
    cond: str
    color: str        # цвет диска гриба, если это самая редкая мутация на нём

    @property
    def chance(self) -> float:
        return RARITY[self.rarity][1]

    @property
    def hint(self) -> str:
        return CONDS[self.cond][1]

    def check(self, ctx: Ctx) -> bool:
        return CONDS[self.cond][0](ctx)


# стадия → 20 × (code, title, emoji, rarity, cond, color)
_RAW = {
    1: [
        ("sparkle", "Искристый", "✨", "common", "any", "#fff4c2"),
        ("night", "Ночной", "🌙", "rare", "night", "#51639e"),
        ("sweet_tooth", "Сладкоежка", "🍭", "rare", "sweet_high", "#ffc2e0"),
        ("s1_dew", "Росинка", "💧", "common", "tea", "#bfe8ff"),
        ("s1_fluffy", "Пушистик", "☁️", "common", "pet", "#f4f4f4"),
        ("s1_dot", "Крапинка", "🔘", "common", "any", "#e3d2b0"),
        ("s1_mint", "Мятный", "🌿", "common", "clean", "#b8f0cf"),
        ("s1_lemon", "Лимонный", "🍋", "common", "sugar", "#fff27a"),
        ("s1_sleepy", "Сонный", "😴", "common", "evening", "#c9c3e6"),
        ("s1_snow", "Первый снег", "❄️", "rare", "morning", "#e8f6ff"),
        ("s1_caramel", "Карамельный", "🍯", "rare", "sugar", "#e0a45a"),
        ("s1_bubble", "Пузырёк", "🫧", "common", "tea", "#d6f3ff"),
        ("s1_raspberry", "Малиновый", "🍓", "rare", "weekend", "#ff7a9c"),
        ("s1_marsh", "Зефирный", "🍥", "rare", "happy", "#ffe0ef"),
        ("s1_dust", "Чайная пыль", "🍂", "common", "low", "#b98a55"),
        ("s1_sunny", "Солнечный", "☀️", "rare", "morning", "#ffe066"),
        ("s1_fog", "Туманный", "🌫️", "epic", "night", "#cfd6dc"),
        ("s1_vanilla", "Ванильный", "🍦", "epic", "all_high", "#fff6dc"),
        ("s1_bead", "Бусинка", "📿", "epic", "streak", "#d9b38c"),
        ("s1_crystal", "Хрустальная спора", "🔹", "legendary", "all_high", "#9fd8ff"),
    ],
    2: [
        ("striped", "Полосатый", "🦓", "common", "any", "#d9c29a"),
        ("bubbly", "Газировка", "🥤", "rare", "tea_low", "#c7ecff"),
        ("clean_freak", "Чистюля", "🧼", "rare", "clean_high", "#e6fbff"),
        ("early", "Жаворонок", "🌅", "rare", "morning", "#ffc58a"),
        ("s2_lace", "Кружевной", "🕸️", "common", "pet", "#f0ece4"),
        ("s2_silk", "Шёлковый", "🎀", "common", "clean", "#ffd3e6"),
        ("s2_amber", "Янтарный", "🟠", "common", "tea", "#ffb347"),
        ("s2_leopard", "Пятнистый", "🐆", "common", "any", "#e8c170"),
        ("s2_marble", "Мраморный", "🪨", "common", "sugar", "#dcdcdc"),
        ("s2_aqua", "Акварельный", "🎨", "common", "weekend", "#a8e0ff"),
        ("s2_glass", "Витражный", "🪟", "rare", "happy", "#8fd3ff"),
        ("s2_check", "Клетчатый", "🏁", "common", "daily", "#e5e5e5"),
        ("s2_cloud", "Облачный", "⛅", "common", "evening", "#eef4fa"),
        ("s2_storm", "Грозовой", "⛈️", "rare", "low", "#7d8aa3"),
        ("s2_autumn", "Осенний", "🍁", "rare", "gen2", "#e0763a"),
        ("s2_spring", "Весенний", "🌸", "epic", "sprout", "#ffc6dd"),
        ("s2_teal", "Бирюзовый", "🩵", "epic", "all_high", "#7fe3df"),
        ("s2_lavender", "Лавандовый", "💜", "epic", "night", "#c7a6ff"),
        ("s2_honey", "Медовый", "🐝", "rare", "streak", "#ffcf4a"),
        ("s2_pearl", "Перламутровый", "🐚", "legendary", "many_muts", "#f5eaff"),
    ],
    3: [
        ("golden", "Золотой", "🥇", "legendary", "any", "#ffd54a"),
        ("spotted", "Мухоморный", "🍄", "common", "any", "#e0442f"),
        ("chatty", "Болтун", "🗣️", "rare", "chatty", "#ffe5b4"),
        ("survivor", "Выживший", "🩹", "epic", "rescued", "#d7b9a0"),
        ("s3_pancake", "Блинный", "🥞", "common", "sugar", "#f0c27b"),
        ("s3_waffle", "Вафельный", "🧇", "common", "clean", "#e7b86a"),
        ("s3_donut", "Пончик", "🍩", "common", "sweet_high", "#ff9ec7"),
        ("s3_carnival", "Масленица", "🎭", "rare", "weekend", "#ffb3a7"),
        ("s3_cheese", "Сырный", "🧀", "common", "tea", "#ffe27a"),
        ("s3_choco", "Шоколадный", "🍫", "common", "sugar", "#8b5a3c"),
        ("s3_coffee", "Кофейный", "☕", "common", "morning", "#a47551"),
        ("s3_croissant", "Круассан", "🥐", "common", "pet", "#e9b76c"),
        ("s3_pixel", "Пиксельный", "👾", "rare", "night", "#9d7bff"),
        ("s3_retro", "Ретро", "📼", "rare", "evening", "#ff8f6b"),
        ("s3_disco", "Диско", "🪩", "epic", "happy", "#d4d4ff"),
        ("s3_jazz", "Джазовый", "🎷", "rare", "daily", "#ffcf6b"),
        ("s3_rock", "Рок-н-ролльный", "🎸", "rare", "streak", "#ff5a5a"),
        ("s3_graffiti", "Граффити", "🖍️", "common", "any", "#7ce0a0"),
        ("s3_skater", "Скейтер", "🛹", "epic", "answers", "#6bc4ff"),
        ("s3_gamer", "Геймер", "🎮", "epic", "debate", "#7a7aff"),
    ],
    4: [
        ("glow", "Светящийся", "💡", "rare", "any", "#fffbb0"),
        ("jelly", "Желейный", "🍮", "common", "any", "#ffc36b"),
        ("scholar", "Ботаник", "🎓", "epic", "answers", "#c8d7ff"),
        ("holivar", "Холиварщик", "⚔️", "epic", "debate", "#ff8a8a"),
        ("phoenix", "Феникс", "🔥", "legendary", "gen2", "#ff7a00"),
        ("s4_jellyfish", "Медузный", "🪼", "common", "tea", "#d4b8ff"),
        ("s4_coral", "Коралловый", "🪸", "common", "clean", "#ff7f6b"),
        ("s4_deep", "Глубоководный", "🐙", "rare", "night", "#3a5a9c"),
        ("s4_pearl", "Жемчужный", "🦪", "rare", "happy", "#f2efe8"),
        ("s4_wave", "Штормовой", "🌊", "common", "low", "#4aa3df"),
        ("s4_mermaid", "Русалочий", "🧜", "epic", "weekend", "#6fe3c8"),
        ("s4_neon", "Неоновый", "🔆", "common", "evening", "#b6ff4d"),
        ("s4_holo", "Голографический", "💿", "rare", "all_high", "#e0f0ff"),
        ("s4_ghost", "Призрачный", "👻", "rare", "night", "#eef0ff"),
        ("s4_moon", "Лунный", "🌕", "common", "evening", "#f5e6a8"),
        ("s4_aurora", "Северное сияние", "🌌", "epic", "morning", "#6effc4"),
        ("s4_electric", "Электрический", "⚡", "common", "pet", "#fff04d"),
        ("s4_magnet", "Магнитный", "🧲", "common", "sugar", "#ff6464"),
        ("s4_nuclear", "Ядерный", "☢️", "rare", "sweet_high", "#c6ff3d"),
        ("s4_nebula", "Туманность", "🌀", "legendary", "many_muts", "#9a7dff"),
    ],
    5: [
        ("rainbow", "Радужный", "🌈", "legendary", "any", "#ff7ab8"),
        ("crystal", "Кристальный", "💎", "epic", "all_high", "#aef4ff"),
        ("cosmic", "Космический", "🪐", "epic", "night", "#6b4fd8"),
        ("s5_titan", "Титан", "🗿", "common", "any", "#a9a9a9"),
        ("s5_volcano", "Вулканический", "🌋", "rare", "low", "#e0482f"),
        ("s5_glacier", "Ледниковый", "🧊", "rare", "clean_high", "#cdf2ff"),
        ("s5_ancient", "Древний", "🏺", "common", "gen2", "#c98f5a"),
        ("s5_forest", "Лесной великан", "🌲", "common", "tea", "#4caf6a"),
        ("s5_mountain", "Горный", "⛰️", "common", "morning", "#9fb3c8"),
        ("s5_meteor", "Метеоритный", "☄️", "rare", "night", "#ff9a3d"),
        ("s5_dragon", "Драконий", "🐉", "epic", "streak", "#3ddc84"),
        ("s5_knight", "Рыцарский", "🛡️", "common", "clean", "#c0c8d8"),
        ("s5_pirate", "Пиратский", "🏴‍☠️", "rare", "weekend", "#3a3a3a"),
        ("s5_samurai", "Самурайский", "🗡️", "common", "daily", "#ff5a6e"),
        ("s5_viking", "Викинг", "🪓", "common", "sugar", "#b58a5a"),
        ("s5_robo", "Робо", "🤖", "common", "pet", "#b8c4d6"),
        ("s5_cyber", "Кибер", "🦾", "rare", "evening", "#4de1ff"),
        ("s5_alchemy", "Алхимический", "⚗️", "epic", "answers", "#8affc1"),
        ("s5_rune", "Рунный", "🔮", "rare", "debate", "#a77bff"),
        ("s5_star", "Звёздный", "⭐", "common", "happy", "#ffe35a"),
    ],
    6: [
        ("crown", "Коронованный", "👑", "rare", "any", "#ffd700"),
        ("s6_immortal", "Бессмертный", "♾️", "legendary", "rescued", "#e8e8ff"),
        ("s6_unicorn", "Мифический", "🦄", "epic", "happy", "#ffb8f0"),
        ("s6_angel", "Божественный", "😇", "epic", "all_high", "#fff8d6"),
        ("s6_empire", "Императорский", "🏛️", "rare", "daily", "#e6d3a3"),
        ("s6_galaxy", "Галактический", "🌠", "epic", "night", "#5a3fd8"),
        ("s6_blackhole", "Чёрная дыра", "🕳️", "legendary", "night", "#1a1a2e"),
        ("s6_time", "Время", "⏳", "rare", "morning", "#e0c48a"),
        ("s6_trident", "Абсолют", "🔱", "rare", "gen2", "#4dd0e1"),
        ("s6_runet", "Легенда рунета", "🌐", "epic", "answers", "#5b8cff"),
        ("s6_meme", "Мемный", "🐸", "common", "pet", "#7ed957"),
        ("s6_prime", "Бульбоз-прайм", "🧬", "legendary", "many_muts", "#ff5a36"),
        ("s6_mage", "Архимаг", "🧙", "rare", "evening", "#8a6bff"),
        ("s6_keeper", "Хранитель банки", "🫙", "common", "clean", "#d9f2ff"),
        ("s6_golden_age", "Золотой век", "🏆", "rare", "streak", "#ffcf33"),
        ("s6_solstice", "Солнцестояние", "🌞", "common", "weekend", "#ffd166"),
        ("s6_karma", "Кармический", "☯️", "common", "any", "#f2f2f2"),
        ("s6_quantum", "Квантовый", "⚛️", "epic", "debate", "#6bf2ff"),
        ("s6_singularity", "Сингулярность", "🎇", "legendary", "sprout", "#ffffff"),
        ("s6_boss", "Последний босс", "💀", "epic", "low", "#4a4a4a"),
    ],
}

MUTATIONS: list[Mutation] = [Mutation(code, title, emoji, stage, rarity, cond, color)
                             for stage, rows in _RAW.items() for code, title, emoji, rarity, cond, color in rows]
MUT_BY_CODE = {m.code: m for m in MUTATIONS}

assert len(MUTATIONS) == 120 and len(MUT_BY_CODE) == 120
assert all(sum(1 for m in MUTATIONS if m.stage == st) == 20 for st in range(1, 7))
assert all(m.cond in CONDS and m.rarity in RARITY for m in MUTATIONS)
