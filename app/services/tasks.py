"""Задания за «Деревянные» (биржа мелких заданий внутри сайта).

Как устроено:
1. Автор создаёт задание: название, описание, что прислать как доказательство, награда за одно выполнение,
   число мест (исполнителей) и срок. Сразу списывается reward × slots + 10% комиссии — деньги «в эскроу»,
   поэтому исполнитель точно получит оплату. Комиссия сгорает (борьба с инфляцией и спамом заданиями).
2. Исполнитель откликается один раз: присылает текст/ссылку-доказательство.
3. Автор засчитывает (исполнителю уходит награда) или отклоняет с причиной.
   Если автор молчит 72 часа — отклик засчитывается автоматически.
4. На отказ исполнитель может подать спор: модератор засчитывает (платит из эскроу) или подтверждает отказ.
5. Задание закрывается само, когда кончились места или истёк срок, или вручную автором.
   Всё невыплаченное (кроме комиссии) возвращается автору, когда не останется откликов на рассмотрении.
6. Модератор может снять задание (нарушает правила) — висящие отклики отклоняются, остаток возвращается.

Все переходы считаются лениво при чтении (settle), фоновых воркеров не нужно.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from ..errors import ApiError
from ..models import Task, TaskSubmission
from . import wood
from .kombucha_achievements import award
from .notifications import notify

FEE = 0.10
MIN_REWARD, MAX_REWARD = 5, 5000
MAX_SLOTS = 50
MIN_DAYS, MAX_DAYS = 1, 14
MAX_OPEN_PER_USER = 5
AUTO_APPROVE = timedelta(hours=72)
PENDING = ("pending", "disputed")


def now() -> datetime:
    return datetime.now(timezone.utc)


def cost(reward: int, slots: int) -> tuple[int, int]:
    base = reward * slots
    fee = max(1, round(base * FEE))
    return base, fee


async def create(s, user, title: str, body: str, proof: str, reward: int, slots: int, days: int) -> Task:
    n = await s.scalar(select(func.count()).select_from(Task).where(Task.author_id == user.id, Task.status == "open"))
    if n >= MAX_OPEN_PER_USER:
        raise ApiError(f"Не больше {MAX_OPEN_PER_USER} открытых заданий одновременно", 429, "too_many_tasks")
    base, fee = cost(reward, slots)
    t = Task(author_id=user.id, title=title, body=body, proof=proof, reward=reward, slots=slots, slots_left=slots,
             fee=fee, status="open", deadline=now() + timedelta(days=days))
    s.add(t)
    await s.flush()
    await wood.spend(s, user.id, base + fee, "task_create", t.id)
    await award(s, user.id, "task_create")
    return t


async def _pending_count(s, t: Task) -> int:
    return await s.scalar(select(func.count()).select_from(TaskSubmission).where(
        TaskSubmission.task_id == t.id, TaskSubmission.status.in_(PENDING))) or 0


async def _pay(s, t: Task, sub: TaskSubmission, reason: str | None = None) -> None:
    if t.slots_left <= 0:
        raise ApiError("Места в задании закончились", 409, "no_slots")
    sub.status, sub.decided_at, sub.reason = "approved", now(), reason
    t.slots_left -= 1
    await wood.earn(s, sub.user_id, "task_reward", f"sub:{sub.id}", amount=t.reward)
    done = await s.scalar(select(func.count()).select_from(TaskSubmission).where(
        TaskSubmission.user_id == sub.user_id, TaskSubmission.status == "approved")) or 0
    await award(s, sub.user_id, "task_done")
    if done >= 10:
        await award(s, sub.user_id, "task_done10")
    notify(s, sub.user_id, "task", task_id=t.id, title=t.title[:80], result="approved", amount=t.reward)
    if t.slots_left == 0 and t.status == "open":
        t.status = "done"


async def settle(s, t: Task) -> None:
    """Ленивые переходы: автозачёт через 72 ч, истечение срока, возврат остатка автору."""
    at = now()
    stale = (await s.scalars(select(TaskSubmission).where(
        TaskSubmission.task_id == t.id, TaskSubmission.status == "pending",
        TaskSubmission.created_at < at - AUTO_APPROVE).order_by(TaskSubmission.id).with_for_update())).all()
    for sub in stale:
        if t.slots_left > 0:
            await _pay(s, t, sub, "Засчитано автоматически: автор не ответил за 72 часа")
    if t.status == "open" and at >= t.deadline:
        t.status = "expired"
    if t.status != "open" and t.refunded is None and await _pending_count(s, t) == 0:
        # всё, что не выплачено по местам, возвращаем; но не больше, чем отложено под свободные места
        back = t.slots_left * t.reward
        t.refunded = back
        if back > 0:
            await wood.earn(s, t.author_id, "task_refund", f"task:{t.id}", amount=back)


async def settle_open(s, limit: int = 50) -> None:
    rows = (await s.scalars(select(Task).where(Task.refunded.is_(None)).where(
        (Task.deadline <= now()) | (Task.status != "open")).limit(limit).with_for_update(skip_locked=True))).all()
    for t in rows:
        await settle(s, t)


async def submit(s, user, t: Task, body: str) -> TaskSubmission:
    await settle(s, t)
    if t.status != "open":
        raise ApiError("Задание уже закрыто", 409, "task_closed")
    if t.author_id == user.id:
        raise ApiError("Своё задание выполнять нельзя 🙃", 409, "own_task")
    if await _pending_count(s, t) >= max(3, t.slots_left * 2):   # не даём завалить автора откликами
        raise ApiError("Слишком много откликов на рассмотрении, загляни позже", 429, "task_busy")
    if await s.scalar(select(TaskSubmission.id).where(TaskSubmission.task_id == t.id, TaskSubmission.user_id == user.id)):
        raise ApiError("Ты уже откликался на это задание", 409, "already_submitted")
    sub = TaskSubmission(task_id=t.id, user_id=user.id, body=body)
    s.add(sub)
    await s.flush()
    notify(s, t.author_id, "task", task_id=t.id, title=t.title[:80], result="new_submission", username=user.username)
    return sub


async def decide(s, user, t: Task, sub: TaskSubmission, approve: bool, reason: str | None) -> None:
    if t.author_id != user.id:
        raise ApiError("Решать может только автор задания", 403, "forbidden")
    if sub.status != "pending":
        raise ApiError("Отклик уже рассмотрен", 409, "submission_closed")
    if approve:
        await _pay(s, t, sub)
    else:
        if not reason or len(reason) < 3:
            raise ApiError("Напиши причину отказа — исполнитель сможет её оспорить", 400, "validation_error",
                           field="reason")
        sub.status, sub.decided_at, sub.reason = "rejected", now(), reason[:300]
        notify(s, sub.user_id, "task", task_id=t.id, title=t.title[:80], result="rejected", reason=reason[:120])
    await settle(s, t)


async def dispute(s, user, t: Task, sub: TaskSubmission) -> None:
    if sub.user_id != user.id:
        raise ApiError("Это не твой отклик", 403, "forbidden")
    if sub.status != "rejected":
        raise ApiError("Оспорить можно только отказ", 409, "not_rejected")
    if sub.decided_at and now() - sub.decided_at > timedelta(days=3):
        raise ApiError("Оспорить можно в течение 3 дней", 409, "dispute_expired")
    if t.refunded is not None:
        raise ApiError("По заданию уже рассчитались", 409, "task_settled")
    sub.status = "disputed"


async def resolve_dispute(s, t: Task, sub: TaskSubmission, approve: bool, comment: str | None) -> None:
    if sub.status != "disputed":
        raise ApiError("Спора нет", 409, "not_disputed")
    if approve:
        await _pay(s, t, sub, f"Модератор: {comment}" if comment else "Засчитано модератором")
    else:
        sub.status, sub.decided_at = "rejected", now()
        sub.reason = f"Модератор подтвердил отказ{': ' + comment if comment else ''}"[:300]
        notify(s, sub.user_id, "task", task_id=t.id, title=t.title[:80], result="dispute_lost")
    await settle(s, t)


async def close(s, user, t: Task) -> None:
    if t.author_id != user.id:
        raise ApiError("Закрыть может только автор", 403, "forbidden")
    if t.status != "open":
        raise ApiError("Задание уже закрыто", 409, "task_closed")
    t.status = "closed"
    await settle(s, t)


async def remove(s, t: Task, reason: str) -> None:
    """Модератор снимает задание: висящие отклики отклоняются, остаток уходит автору."""
    t.status = "removed"
    await s.execute(update(TaskSubmission).where(TaskSubmission.task_id == t.id, TaskSubmission.status.in_(PENDING))
                    .values(status="rejected", reason=f"Задание снято модератором: {reason}"[:300], decided_at=now()))
    await settle(s, t)
