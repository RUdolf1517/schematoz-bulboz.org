"""Каталог прав и базовых ролей. Источник для seed-команды и тестов."""

USER_PERMS = {"kombucha.play", "market.trade"}
MODERATOR_PERMS = USER_PERMS | {"ban.temporary", "modlog.read_own"}
ADMIN_PERMS = MODERATOR_PERMS | {
    "ban.permanent", "ban.lift_any", "modlog.read_all", "role.assign",
    "settings.captcha", "settings.antispam", "analytics.read", "legal.edit", "kombucha.debug",
}

ROLES = {
    "user": ("Игрок", USER_PERMS),
    "moderator": ("Модератор", MODERATOR_PERMS),
    "admin": ("Администратор", ADMIN_PERMS),
}
ALL_PERMS = ADMIN_PERMS
