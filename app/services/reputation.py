"""Голоса за ответы и репутация.

Правило:
  * автор вопроса ставит ответу ТОЛЬКО +5 или −1;
  * все остальные — ТОЛЬКО +1 или −1;
  * за свой ответ голосовать нельзя; один голос на ответ, его можно поменять или снять.
Ответ, которому автор поставил +5, становится «Схемой» вопроса (best_answer_id).
Правило продублировано CHECK-ограничением в таблице votes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import Answer, ContentStatus, Question, RepReason, ReputationEvent, User, Vote
from .gamification import on_scheme
from .ranking import hot_score

AUTHOR_VALUES = frozenset({5, -1})
USER_VALUES = frozenset({1, -1})
BEST_ANSWER_VALUE = 5


def level_for(reputation: int) -> int:
    """Уровни 1–50: каждый следующий требует чуть больше очков."""
    lvl, need, total = 1, 10, 0
    while lvl < 50 and reputation >= total + need:
        total += need
        need = int(need * 1.25) + 5
        lvl += 1
    return lvl


def allowed_values(is_author: bool) -> frozenset[int]:
    return AUTHOR_VALUES if is_author else USER_VALUES


def _reason(value: int, is_author: bool) -> RepReason:
    if is_author:
        return RepReason.AUTHOR_VOTE
    return RepReason.UPVOTE if value > 0 else RepReason.DOWNVOTE


async def _apply_rep(s: AsyncSession, *, user_id: int, delta: int, reason: RepReason,
                     actor_id: int, answer: Answer, question: Question) -> None:
    if delta == 0:
        return
    s.add(ReputationEvent(user_id=user_id, delta=delta, reason=reason, actor_id=actor_id,
                          answer_id=answer.id, question_id=question.id,
                          room_id=question.room_id, category_id=question.category_id))
    new_rep = await s.scalar(
        update(User).where(User.id == user_id)
        .values(reputation=User.reputation + delta).returning(User.reputation)
    )
    await s.execute(update(User).where(User.id == user_id).values(level=level_for(new_rep)))


async def _load(s: AsyncSession, answer_id: int) -> tuple[Answer, Question]:
    answer = await s.get(Answer, answer_id, with_for_update=True)
    if answer is None or answer.status != ContentStatus.ACTIVE:
        raise ApiError("Ответ не найден", 404, "not_found")
    question = await s.get(Question, answer.question_id, with_for_update=True)
    if question is None or question.status != ContentStatus.ACTIVE:
        raise ApiError("Вопрос не найден", 404, "not_found")
    return answer, question


async def _refresh_question(s: AsyncSession, question: Question) -> None:
    rows = (await s.execute(
        select(Answer.score).where(Answer.question_id == question.id,
                                   Answer.status == ContentStatus.ACTIVE)
    )).scalars().all()
    question.score_hot = hot_score(sum(rows), len(rows), question.created_at)


async def cast_vote(s: AsyncSession, voter: User, answer_id: int, value: int) -> dict:
    answer, question = await _load(s, answer_id)
    if answer.author_id == voter.id:
        raise ApiError("Нельзя оценивать свой ответ", 400, "own_answer")

    is_author = question.author_id == voter.id
    if value not in allowed_values(is_author):
        allowed = sorted(allowed_values(is_author), reverse=True)
        raise ApiError(
            f"Недопустимая оценка. Можно: {', '.join(f'{v:+d}' for v in allowed)}",
            400, "invalid_vote_value", allowed=allowed,
        )

    cfg = current_app.config
    now = datetime.now(timezone.utc)
    hold = timedelta(hours=cfg["NEW_ACCOUNT_VOTE_HOLD_HOURS"])
    counted = (now - voter.created_at) >= hold  # голоса «свежих» аккаунтов не влияют на репутацию

    existing = await s.get(Vote, (answer.id, voter.id), with_for_update=True)
    old_value, old_counted = 0, False
    if existing is not None:
        if existing.value == value:
            return _vote_result(answer, question, value)
        cooldown = timedelta(seconds=cfg["VOTE_CHANGE_COOLDOWN_SECONDS"])
        if now - existing.updated_at < cooldown:
            raise ApiError("Голос можно менять не чаще раза в 10 минут", 429, "vote_cooldown")
        old_value, old_counted = existing.value, existing.counted
        existing.value, existing.counted = value, counted
        existing.updated_at = now
    else:
        s.add(Vote(answer_id=answer.id, voter_id=voter.id, value=value,
                   is_author_vote=is_author, counted=counted))

    answer.score += value - old_value

    if old_counted:
        await _apply_rep(s, user_id=answer.author_id, delta=-old_value, reason=RepReason.VOTE_REVOKED,
                         actor_id=voter.id, answer=answer, question=question)
    new_badges: list[str] = []
    if counted:
        await _apply_rep(s, user_id=answer.author_id, delta=value, reason=_reason(value, is_author),
                         actor_id=voter.id, answer=answer, question=question)
        if is_author and value == BEST_ANSWER_VALUE:
            new_badges = await on_scheme(s, answer.author_id)  # бейджи получает автор ответа

    if is_author:
        if value == BEST_ANSWER_VALUE:
            question.best_answer_id = answer.id
        elif question.best_answer_id == answer.id:
            question.best_answer_id = None

    await _refresh_question(s, question)
    return {**_vote_result(answer, question, value), "author_new_badges": new_badges}


async def remove_vote(s: AsyncSession, voter: User, answer_id: int) -> dict:
    answer, question = await _load(s, answer_id)
    existing = await s.get(Vote, (answer.id, voter.id), with_for_update=True)
    if existing is None:
        return _vote_result(answer, question, None)
    answer.score -= existing.value
    if existing.counted:
        await _apply_rep(s, user_id=answer.author_id, delta=-existing.value,
                         reason=RepReason.VOTE_REVOKED, actor_id=voter.id,
                         answer=answer, question=question)
    if existing.is_author_vote and question.best_answer_id == answer.id:
        question.best_answer_id = None
    await s.delete(existing)
    await _refresh_question(s, question)
    return _vote_result(answer, question, None)


def _vote_result(answer: Answer, question: Question, my_vote: int | None) -> dict:
    return {
        "answer_id": answer.id,
        "score": answer.score,
        "my_vote": my_vote,
        "is_best": question.best_answer_id == answer.id,
    }
