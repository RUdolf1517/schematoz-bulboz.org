"""«Деревянные» ($₽) — внутренняя валюта сайта.

Начисляется за активность, тратится в магазине «Чайного гриба» (банки, новые грибы, реанимация).
Каждое начисление идёт через журнал wood_tx с уникальным (user_id, reason, ref):
одно событие — одна выплата, даже при повторном запросе. У «фармовых» причин
есть дневной лимит (по Москве), чтобы автокликер не печатал деньги.
Реальными деньгами $₽ не покупаются и не выводятся — это игровая валюта.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..errors import ApiError
from ..models import User, WoodTx

SIGN = "$₽"
MSK = timezone(timedelta(hours=3))

# причина: (сумма, дневной лимит выплат или None, подпись для истории)
EARN = {
    "daily_login": (10, None, "Зашёл проведать гриба"),
    "kombucha_care": (1, 20, "Уход за грибом"),
    "daily_bonus": (20, None, "Бонус дня (до 20, зависит от ухода)"),
    "mutation": (15, None, "Новая мутация гриба"),
    "sprout": (50, None, "Гриб дал отросток"),
    "minigame": (8, 10, "Мини-игры гриба (до 8 за игру, по точности)"),
    "meditation": (10, 5, "Медитация гриба (до 10 за раз, по точности)"),
    "sale": (0, None, "Продал гриб"),
}
# старые причины из Q&A-эпохи — только чтобы история кошелька читалась
LEGACY_TITLES = {"demo_grant": "Демо-пополнение кошелька (превью)", "question": "Задал вопрос", "answer": "Ответил на вопрос", "comment": "Комментарий",
                 "debate_vote": "Голос в холиваре", "debate_answer": "Аргумент в холиваре", "scheme": "Ответ стал «Схемой»",
                 "wall_post": "Запись на стене", "task_reward": "Награда за задание", "task_refund": "Возврат за задание",
                 "task_create": "Создал задание (эскроу)"}
SPEND_TITLES = {"buy_jar": "Купил банку", "revive": "Реанимация гриба",
                "buy_kombucha": "Купил гриб на рынке", "buy_new_kombucha": "Купил нового гриба",
                "club_create": "Основал кооператив", "club_deposit": "Взнос в копилку клуба"}
MARKET_FEE = 0.05          # комиссия рынка сгорает — борьба с инфляцией
MIN_PRICE, MAX_PRICE = 10, 1_000_000
PRICES = {"jar": 300, "mushroom": 1000, "revive": 150}
MAX_JARS = 5


def msk_day_start(now: datetime | None = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(MSK)
    return datetime.combine(now.date(), time(0), MSK)


def daily_login_amount(streak_days: int) -> int:
    """10 $₽ за заход + до 10 $₽ сверху за стрик ухода."""
    return EARN["daily_login"][0] + min(max(streak_days, 0), 10)


async def earn(s, user_id: int, reason: str, ref, amount: int | None = None) -> int:
    """Начислить $₽. Возвращает сколько реально начислено (0 — уже было или лимит)."""
    base, cap, _ = EARN[reason]
    amount = base if amount is None else amount
    if amount <= 0:
        return 0
    if cap is not None:
        n = await s.scalar(select(func.count(WoodTx.id)).where(
            WoodTx.user_id == user_id, WoodTx.reason == reason, WoodTx.created_at >= msk_day_start()))
        if n >= cap:
            return 0
    tx_id = (await s.execute(
        insert(WoodTx).values(user_id=user_id, delta=amount, reason=reason, ref=str(ref)[:64], balance_after=0)
        .on_conflict_do_nothing().returning(WoodTx.id))).scalar()
    if tx_id is None:
        return 0
    bal = (await s.execute(update(User).where(User.id == user_id).values(wood=User.wood + amount)
                           .returning(User.wood))).scalar()
    await s.execute(update(WoodTx).where(WoodTx.id == tx_id).values(balance_after=bal))
    if bal >= 1000:
        from .kombucha_achievements import check_rich
        await check_rich(s, user_id, bal)
    return amount


async def demo_grant(s, user_id: int, amount: int, ref: str) -> int:
    """Пополнение кошелька для DEMO_MODE/e2e (в проде путь недоступен). Не входит в EARN:
    экономика игры не должна знать о демо-деньгах."""
    await s.execute(insert(WoodTx).values(user_id=user_id, delta=amount, reason="demo_grant",
                                          ref=str(ref)[:64], balance_after=0))
    bal = (await s.execute(update(User).where(User.id == user_id).values(wood=User.wood + amount)
                           .returning(User.wood))).scalar()
    await s.execute(update(WoodTx).where(WoodTx.user_id == user_id, WoodTx.reason == "demo_grant",
                                         WoodTx.ref == str(ref)[:64]).values(balance_after=bal))
    return bal


async def spend(s, user_id: int, amount: int, reason: str, ref) -> int:
    """Списать $₽ или 402 not_enough_wood. Возвращает новый баланс."""
    bal = (await s.execute(update(User).where(User.id == user_id, User.wood >= amount)
                           .values(wood=User.wood - amount).returning(User.wood))).scalar()
    if bal is None:
        have = await s.scalar(select(User.wood).where(User.id == user_id)) or 0
        raise ApiError(f"Не хватает деревянных: нужно {amount} {SIGN}, у тебя {have} {SIGN}", 402,
                       "not_enough_wood", need=amount, have=have)
    s.add(WoodTx(user_id=user_id, delta=-amount, reason=reason, ref=str(ref)[:64], balance_after=bal))
    await s.flush()
    return bal


async def balance(s, user_id: int) -> int:
    return await s.scalar(select(User.wood).where(User.id == user_id)) or 0


def title_for(reason: str) -> str:
    return EARN[reason][2] if reason in EARN else SPEND_TITLES.get(reason) or LEGACY_TITLES.get(reason, reason)


def rules() -> list[dict]:
    return [{"reason": r, "amount": a, "daily_cap": c, "title": t} for r, (a, c, t) in EARN.items() if a > 0]
