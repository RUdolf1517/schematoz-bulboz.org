"""users.rating_tier теперь просто кэш роли для отображения: 2 — админ, 0 — игрок (модераторов больше нет)."""
from __future__ import annotations

from sqlalchemy import select, update

from ..models import Role, User, UserRole


async def sync_tier(s, user_id: int) -> int:
    codes = set((await s.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id)
                                 .where(UserRole.user_id == user_id))).all())
    tier = 2 if "admin" in codes else 0
    await s.execute(update(User).where(User.id == user_id).values(rating_tier=tier))
    return tier
