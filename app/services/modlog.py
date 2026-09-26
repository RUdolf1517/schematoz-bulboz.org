from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ModAction


def log_action(s: AsyncSession, actor_id: int, action: str, target_type: str,
               target_id: int | None, **payload) -> ModAction:
    """Пишется в ТОЙ ЖЕ транзакции, что и само действие: нет записи — нет действия."""
    entry = ModAction(actor_id=actor_id, action=action, target_type=target_type,
                      target_id=target_id, payload=payload or None)
    s.add(entry)
    return entry
