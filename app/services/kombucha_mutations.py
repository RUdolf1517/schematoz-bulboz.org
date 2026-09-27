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


# ---------------------------------------------------------------- вторая волна: ещё по 20 на стадию (итого 240)
CONDS.update({
    "talk": (lambda c: c.action == "talk", "Разговаривай с грибом о философии"),
    "cure": (lambda c: c.action == "cure", "Вылечи гриб от плесени"),
    "monday": (lambda c: c.weekday == 0, "По понедельникам (сочувствуем)"),
    "noon": (lambda c: 12 <= c.hour < 14, "В обед, с 12 до 14"),
    "balanced": (lambda c: max(_stats(c)) - min(_stats(c)) <= 10, "Все показатели почти равны (разброс ≤ 10)"),
    "gen3": (lambda c: c.k.generation >= 3, "Гриб третьего поколения и старше"),
    "traded": (lambda c: len(getattr(c.k, "owners", None) or []) >= 2, "Гриб, сменивший хозяина"),
})

_EXTRA = {
    1: [
        ("s1b_crumb", "Крошка", "🍪", "common", "sugar", "#e8c396"), ("s1b_puddle", "Лужица", "💦", "common", "tea", "#9fd8ff"),
        ("s1b_soap", "Мыльный", "🧼", "common", "clean", "#e9f7ff"), ("s1b_yawn", "Зевака", "🥱", "common", "morning", "#f5e6c8"),
        ("s1b_pixel", "Пиксельный", "👾", "common", "any", "#b58cff"), ("s1b_sock", "Носочный", "🧦", "common", "pet", "#ff9fb2"),
        ("s1b_lunch", "Обеденный", "🥪", "common", "noon", "#f7d08a"), ("s1b_monday", "Понедельничный", "😩", "common", "monday", "#9aa5b1"),
        ("s1b_think", "Задумчивый", "🤔", "common", "talk", "#ffe08a"), ("s1b_candy", "Леденец", "🍬", "common", "sweet_high", "#ff7eb6"),
        ("s1b_owl", "Совёнок", "🦉", "rare", "night", "#8b6b4a"), ("s1b_zen", "Дзен", "🧘", "rare", "balanced", "#c9f2c7"),
        ("s1b_pill", "Выздоравливающий", "💊", "rare", "cure", "#ffffff"), ("s1b_socr", "Сократик", "🏛️", "rare", "talk", "#e6dcc8"),
        ("s1b_hand", "Передаренный", "🎁", "rare", "traded", "#ff6b6b"), ("s1b_ghost", "Призрак", "👻", "epic", "night", "#e8e8ff"),
        ("s1b_ufo", "НЛО", "🛸", "epic", "weekend", "#7df9ff"), ("s1b_mirror", "Зеркальный", "🪞", "epic", "balanced", "#dfe9f5"),
        ("s1b_oracle", "Оракул", "🔮", "legendary", "talk", "#9b5de5"), ("s1b_egg", "Пасхалка", "🥚", "legendary", "gen3", "#fff8e7"),
    ],
    2: [
        ("s2b_foam", "Пенка", "🫧", "common", "tea", "#e0f4ff"), ("s2b_honey", "Медовый", "🍯", "common", "sugar", "#f2b134"),
        ("s2b_broom", "Веник", "🧹", "common", "clean", "#c9a66b"), ("s2b_purr", "Мурчащий", "🐈", "common", "pet", "#f0c27b"),
        ("s2b_sun", "Солнечный", "🌤️", "common", "morning", "#ffe27a"), ("s2b_moon", "Лунатик", "🌛", "common", "evening", "#c5cae9"),
        ("s2b_soup", "Супчик", "🍲", "common", "noon", "#e07a5f"), ("s2b_coffee", "Кофеман", "☕", "common", "monday", "#6f4e37"),
        ("s2b_book", "Книжный", "📚", "common", "talk", "#a1887f"), ("s2b_dust", "Пыльный", "🌫️", "common", "low", "#b0a99f"),
        ("s2b_scale", "Весы", "⚖️", "rare", "balanced", "#d4af37"), ("s2b_bandage", "Пластырь", "🩹", "rare", "cure", "#f8c9a0"),
        ("s2b_plato", "Платоник", "📜", "rare", "talk", "#efe3c2"), ("s2b_dj", "Диджей", "🎧", "rare", "weekend", "#ff4fd8"),
        ("s2b_barter", "Бартерный", "🔄", "rare", "traded", "#4ecdc4"), ("s2b_vamp", "Вампирчик", "🧛", "epic", "night", "#8b0000"),
        ("s2b_rain", "Радужный дождь", "🌦️", "epic", "all_high", "#7fd1ff"), ("s2b_ninja", "Ниндзя", "🥷", "epic", "gen2", "#2b2b2b"),
        ("s2b_philo", "Философский камень", "💠", "legendary", "talk", "#00c2ff"), ("s2b_dragon", "Дракончик", "🐉", "legendary", "rescued", "#3ecf5a"),
    ],
    3: [
        ("s3b_waffle", "Вафельный", "🧇", "common", "sugar", "#e3b04b"), ("s3b_kettle", "Чайник", "🫖", "common", "tea", "#7aa6c2"),
        ("s3b_sponge", "Губка", "🧽", "common", "clean", "#ffe66d"), ("s3b_hug", "Обнимашка", "🤗", "common", "pet", "#ffb4a2"),
        ("s3b_rooster", "Петушок", "🐓", "common", "morning", "#e63946"), ("s3b_neon", "Неоновый", "💡", "common", "evening", "#39ff14"),
        ("s3b_pelmen", "Пельмешек", "🥟", "common", "noon", "#f1e3c6"), ("s3b_grumpy", "Ворчун", "😤", "common", "monday", "#c0392b"),
        ("s3b_quote", "Цитатник", "💬", "common", "talk", "#ffffff"), ("s3b_toxic", "Токсичный", "☢️", "common", "low", "#b7ff00"),
        ("s3b_yinyang", "Гармония", "🎐", "rare", "balanced", "#a8dadc"), ("s3b_doctor", "Доктор", "🩺", "rare", "cure", "#48cae4"),
        ("s3b_stoic", "Стоик", "🗿", "rare", "talk", "#9e9e9e"), ("s3b_party", "Тусовщик", "🪩", "rare", "weekend", "#f72585"),
        ("s3b_merchant", "Купеческий", "🪙", "rare", "traded", "#d4a017"), ("s3b_kraken", "Кракен", "🦑", "epic", "tea_low", "#6a0572"),
        ("s3b_robot", "Робот", "🤖", "epic", "streak", "#adb5bd"), ("s3b_lava", "Лавовый", "🌋", "epic", "sweet_high", "#ff4800"),
        ("s3b_diogenes", "Бочка Диогена", "🛢️", "legendary", "talk", "#8d6e63"), ("s3b_unicorn", "Единорог", "🦄", "legendary", "all_high", "#ffafcc"),
    ],
    4: [
        ("s4b_jam", "Вареньевый", "🍓", "common", "sugar", "#d62828"), ("s4b_samovar", "Самоварный", "🏺", "common", "tea", "#b87333"),
        ("s4b_shower", "Душевой", "🚿", "common", "clean", "#90e0ef"), ("s4b_tickle", "Щекотун", "🪶", "common", "pet", "#fefae0"),
        ("s4b_jogger", "Бегун", "🏃", "common", "morning", "#06d6a0"), ("s4b_candle", "Свечной", "🕯️", "common", "evening", "#ffd166"),
        ("s4b_borsch", "Борщевой", "🥣", "common", "noon", "#9d0208"), ("s4b_alarm", "Будильник", "⏰", "common", "monday", "#ef233c"),
        ("s4b_owlbook", "Совиный том", "📖", "common", "talk", "#7f5539"), ("s4b_rust", "Ржавый", "🔩", "common", "low", "#a0522d"),
        ("s4b_tao", "Дао", "🌀", "rare", "balanced", "#3a86ff"), ("s4b_herb", "Травник", "🌿", "rare", "cure", "#52b788"),
        ("s4b_kant", "Категорический", "🎩", "rare", "talk", "#343a40"), ("s4b_karaoke", "Караоке", "🎤", "rare", "weekend", "#ff006e"),
        ("s4b_auction", "Аукционный", "🔨", "rare", "traded", "#bc6c25"), ("s4b_cthulhu", "Ктулху", "🐙", "epic", "night", "#264653"),
        ("s4b_phoenix2", "Пепельный", "🐦‍🔥", "epic", "rescued", "#ff7b00"), ("s4b_crystal2", "Аметист", "🔷", "epic", "clean_high", "#9966cc"),
        ("s4b_zarathustra", "Заратустра", "🦅", "legendary", "talk", "#e9c46a"), ("s4b_hydra", "Гидра", "🐍", "legendary", "gen3", "#2a9d8f"),
    ],
    5: [
        ("s5b_cake", "Тортик", "🎂", "common", "sugar", "#ffc8dd"), ("s5b_matcha", "Матча", "🍵", "common", "tea", "#88b04b"),
        ("s5b_vacuum", "Пылесос", "🌪️", "common", "clean", "#adb5bd"), ("s5b_pat", "Поглаженный", "🖐️", "common", "pet", "#ffddd2"),
        ("s5b_dawn", "Рассветный", "🌅", "common", "morning", "#ff9e00"), ("s5b_stars", "Звездочёт", "🔭", "common", "evening", "#14213d"),
        ("s5b_canteen", "Столовский", "🍛", "common", "noon", "#dda15e"), ("s5b_meeting", "Планёрка", "📊", "common", "monday", "#577590"),
        ("s5b_debater", "Спорщик", "🗣️", "common", "talk", "#f4a261"), ("s5b_swamp", "Болотный", "🐊", "common", "low", "#4f772d"),
        ("s5b_equil", "Равновесие", "🪨", "rare", "balanced", "#8d99ae"), ("s5b_alch", "Алхимик", "⚗️", "rare", "cure", "#7209b7"),
        ("s5b_seneca", "Сенека", "🍷", "rare", "talk", "#6d2e46"), ("s5b_rave", "Рейвер", "🎆", "rare", "weekend", "#00f5d4"),
        ("s5b_nomad", "Кочевник", "🐫", "rare", "traded", "#c68b59"), ("s5b_titan", "Титан", "🗻", "epic", "all_high", "#6c757d"),
        ("s5b_storm", "Шторм", "⛈️", "epic", "tea_low", "#1d3557"), ("s5b_king", "Король вечеринки", "🤴", "epic", "streak", "#ffd60a"),
        ("s5b_marcus", "Марк Аврелий", "🏺", "legendary", "talk", "#c9a227"), ("s5b_leviathan", "Левиафан", "🐋", "legendary", "gen3", "#023e8a"),
    ],
    6: [
        ("s6b_ambrosia", "Амброзия", "🍾", "common", "sugar", "#fff3b0"), ("s6b_elixir", "Эликсир", "🧃", "common", "tea", "#80ed99"),
        ("s6b_diamond", "Бриллиантовый блеск", "💎", "common", "clean", "#caf0f8"), ("s6b_bff", "Лучший друг", "🫶", "common", "pet", "#ff8fab"),
        ("s6b_aurora", "Аврора", "🌌", "common", "morning", "#72efdd"), ("s6b_eclipse", "Затмение", "🌑", "common", "evening", "#212529"),
        ("s6b_feast", "Пир", "🍗", "common", "noon", "#e76f51"), ("s6b_survivor", "Переживший понедельник", "🧟", "common", "monday", "#6a994e"),
        ("s6b_sage", "Мудрец", "🧓", "common", "talk", "#e9ecef"), ("s6b_abyss", "Бездна", "🕳️", "common", "low", "#000814"),
        ("s6b_nirvana", "Нирвана", "🪷", "rare", "balanced", "#ffc6ff"), ("s6b_panacea", "Панацея", "⚕️", "rare", "cure", "#00b4d8"),
        ("s6b_socrates", "Сократ", "🥛", "rare", "talk", "#f8f9fa"), ("s6b_festival", "Фестиваль", "🎪", "rare", "weekend", "#ff595e"),
        ("s6b_heirloom", "Семейная реликвия", "📿", "rare", "traded", "#b08968"), ("s6b_cosmos", "Космос", "🪐", "epic", "night", "#3c096c"),
        ("s6b_eternal", "Вечный", "♾️", "epic", "gen3", "#ffffff"), ("s6b_emperor", "Император", "🏯", "epic", "many_muts", "#9d0208"),
        ("s6b_logos", "Логос", "📯", "legendary", "talk", "#ffba08"), ("s6b_bulboz", "Бульбоз Абсолютный", "🍄", "legendary", "all_high", "#ff006e"),
    ],
}

MUTATIONS.extend(Mutation(code, title, emoji, stage, rarity, cond, color)
                 for stage, rows in _EXTRA.items() for code, title, emoji, rarity, cond, color in rows)
MUT_BY_CODE.update({m.code: m for m in MUTATIONS})
PER_STAGE = 40

assert len(MUTATIONS) == 240 and len(MUT_BY_CODE) == 240, len(MUT_BY_CODE)
assert all(sum(1 for m in MUTATIONS if m.stage == st) == PER_STAGE for st in range(1, 7))
assert all(m.cond in CONDS and m.rarity in RARITY for m in MUTATIONS)
