"""Демо-контент и ТЕСТОВЫЕ аккаунты для локального превью.

    python scripts/demo_data.py          # после `alembic upgrade head` и `flask seed`

Аккаунты (пароли только для разработки — в проде не запускать!):
    admin / admin-demo-2026     — администратор (+ модератор)
    dasha / demo-password       — обычный пользователь
    kotik_na_fizmate, artem, lena_2007 / demo-password
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.auth.passwords import hash_password  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import AppealStatus, Ban, Kombucha, Role, User, UserBadge, UserRole  # noqa: E402

ACCOUNTS = [
    # username, password, roles, birth_year
    ("admin", "admin-demo-2026", ["user", "admin"], 1998),
    ("dasha", "demo-password", ["user"], 2009),
    ("kotik_na_fizmate", "demo-password", ["user"], 2006),
    ("artem", "demo-password", ["user"], 2004),
    ("lena_2007", "demo-password", ["user"], 2007),
    ("spamer777", "demo-password", ["user"], 2000),
]


async def ensure_accounts(s) -> dict[str, User]:
    roles = {r.code: r.id for r in (await s.scalars(select(Role))).all()}
    if not roles:
        raise SystemExit("Сначала выполни: flask --app app seed")
    users = {}
    old = datetime.now(timezone.utc) - timedelta(days=40)  # «прогретые» аккаунты — их голоса считаются
    for name, password, role_codes, by in ACCOUNTS:
        u = await s.scalar(select(User).where(User.username == name))
        if u is None:
            u = User(username=name, email=f"{name}@example.com", display_name=name,
                     password_hash=hash_password(password), birth_year=by, created_at=old)
            s.add(u)
            await s.flush()
            for code in role_codes:
                s.add(UserRole(user_id=u.id, role_id=roles[code]))
            print(f"  + @{name} ({', '.join(role_codes)})  пароль: {password}")
        users[name] = u
    return users


async def demo():
    async with session_scope() as s:
        u = await ensure_accounts(s)
        if await s.scalar(select(Kombucha.id).where(Kombucha.name == "Бульбоз").limit(1)):
            print("demo content already present")
            return
        now = datetime.now(timezone.utc)

        # бейджи и стрики
        today = datetime.now(timezone.utc).date()
        u["kotik_na_fizmate"].streak_days, u["kotik_na_fizmate"].streak_last_date = 12, today
        u["dasha"].streak_days, u["dasha"].streak_last_date = 3, today
        for name, codes in {"kotik_na_fizmate": ["streak_7", "night_watch"], "dasha": ["night_watch"]}.items():
            for c in codes:
                s.add(UserBadge(user_id=u[name].id, code=c))

        # чайные грибы с мутациями — чтобы сразу было видно косметику (по 3 мутации на стадию)
        from app.services import kombucha as kb
        from app.services.kombucha_mutations import MUTATIONS
        u["dasha"].jars = 4
        await s.flush()
        for owner, nm, xp, shift in [("dasha", "Бульбоз", 4200, 0), ("dasha", "Медузий", 1300, 5),
                                     ("dasha", "Блинчик", 600, 11), ("kotik_na_fizmate", "Грибозавр", 4500, 17)]:
            k = await kb.plant(s, u[owner], nm)
            k.xp = xp
            size = kb.stage_for(xp)["size"]
            for st in range(1, size + 1):
                pool = [m for m in MUTATIONS if m.stage == st]
                for i in range(3):
                    await kb.add_mutation(s, k, pool[(shift + i * 13 + st * 7) % len(pool)], now)
        await s.flush()

        # бан с апелляцией (выдал admin, разбирает тоже admin)
        s.add(Ban(user_id=u["spamer777"].id, issued_by=u["admin"].id, reason="Спам ссылками (п. 2 Правил)",
                  ends_at=now + timedelta(days=7), appeal_status=AppealStatus.PENDING,
                  appeal_text="Я больше не буду, это был не я, это брат с моего аккаунта", appeal_created_at=now))
        await s.flush()
        from app.services.roles import sync_tier
        for x in u.values():
            await sync_tier(s, x.id)
    print("demo content created")


if __name__ == "__main__":
    with create_app().app_context():
        asyncio.run(demo())
