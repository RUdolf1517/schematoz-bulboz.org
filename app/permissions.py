"""Каталог прав и базовых ролей. Источник для seed-команды и тестов."""

USER_PERMS = {"question.create", "answer.create", "vote.cast", "report.create"}
MODERATOR_PERMS = USER_PERMS | {
    "debate.create",  # холивары запускают только модеры и админы
    "report.review", "content.hide", "content.restore", "ban.temporary", "modlog.read_own",
}
ADMIN_PERMS = MODERATOR_PERMS | {
    "ban.permanent", "ban.lift_any", "modlog.read_all", "role.assign", "category.manage",
    "room.manage", "settings.captcha", "settings.antispam", "settings.features",
    "analytics.read", "legal.edit",
}

ROLES = {
    "user": ("Пользователь", USER_PERMS),
    "moderator": ("Модератор", MODERATOR_PERMS),
    "admin": ("Администратор", ADMIN_PERMS),
}
ALL_PERMS = ADMIN_PERMS
