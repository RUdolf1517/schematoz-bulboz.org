"""Каталог прав и базовых ролей. Источник для seed-команды и тестов.

Ролей две: игрок и админ (модераторов нет — баны и апелляции разбирает админ).
"""

USER_PERMS = {"kombucha.play", "market.trade"}
ADMIN_PERMS = USER_PERMS | {
    "ban.temporary", "ban.permanent", "ban.lift_any", "modlog.read_own", "modlog.read_all", "role.assign",
    "settings.captcha", "settings.antispam", "analytics.read", "legal.edit", "kombucha.debug", "quotes.edit",
    "clubs.manage", "events.manage",
}

ROLES = {
    "user": ("Игрок", USER_PERMS),
    "admin": ("Администратор", ADMIN_PERMS),
}
ALL_PERMS = ADMIN_PERMS
