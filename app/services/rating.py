"""Рейтинги: юзер, вопрос, ответ, комментарий. Только формулы, без ML.

═══ Рейтинг юзера — «Бульбоз-индекс» ═══════════════════════════════════════════

    вклад    = 3·ln(1+Q) + 5·ln(1+A) + 1.5·ln(1+C) + 2·ln(1+K)
    качество = 8·√P − 11·√N + 20·ln(1+S) + 3·sgn(V)·√|V|
    уверенность w = нижняя граница Уилсона для доли плюсов среди оценок ответов (z = 1.96)
    ядро     = вклад + качество · (0.5 + w)
    активность = 1 + 0.5 · D/30
    свежесть   = 0.3 + 0.7 · 0.5^(I/60)
    доверие    = 0.8^H · (0.5, если был бан за последние 90 дней, иначе 1)

    РЕЙТИНГ = 10 · max(0, ядро · активность · свежесть · доверие), округление до 0.1

где Q — вопросы, A — ответы, C — комментарии, K — комментарии, которые оставили ДРУГИЕ
к ответам юзера (ответ «зацепил»), P / N — сумма плюсов / минусов за ответы (+5 автора
вопроса весит 5), S — «Схемы», V — сумма голосов за вопросы юзера, D — дни с активностью
за последние 30, I — дней с последней активности, H — сколько контента скрыла модерация.

Почему так:
  • логарифмы у количества — сотый коммент приносит в разы меньше первого, накрутка
    флудом не окупается; качество (оценки, «Схемы») весит больше количества;
  • минус бьёт сильнее плюса (11 против 8) — токсичные ответы невыгодны;
  • Уилсон: 3 плюса из 3 ≠ 300 из 300 — чем больше оценок, тем больше доверия к качеству;
  • свежесть: пропал на 2 месяца — рейтинг тает до ~65%, но не ниже 30% (заслуги помнятся);
  • скрытый модерацией контент и баны режут рейтинг множителем, а не вычитанием.

Админ и модератор: рейтинг бесконечный (rating_tier = 2 и 1). Сортировка везде идёт
по (rating_tier DESC, rating DESC), поэтому модер всегда выше любого юзера, а админ — выше модера.

═══ Рейтинг вопроса ════════════════════════════════════════════════════════════
    рейтинг = голоса(±1) + 2·ответы + 0.5·комментарии к ответам
    горячесть = sgn·log10(|рейтинг|) + возраст/12.5ч + буст автора
    буст автора: юзер — 0.5·log10(1 + рейтинг/10); модер — +2 (≈ 25 ч свежести); админ — +3 (≈ 37 ч)
В ленте «бесконечность» админа ограничена бустом: иначе его вопрос трёхлетней давности
висел бы первым вечно. В ответах и комментариях — честная бесконечность (tier первым).

═══ Порядок ответов ════════════════════════════════════════════════════════════
    «Схема» → tier автора → (очки + 0.5·комментарии + 2·ln(1 + рейтинг автора/10)) → старше выше
═══ Порядок комментариев ═══════════════════════════════════════════════════════
    tier автора → рейтинг автора → старше выше
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, case, cast, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Answer, Ban, Comment, ContentStatus, Question, QuestionVote, User, Vote
from .ranking import EPOCH

TIER_ADMIN, TIER_MOD, TIER_USER = 2, 1, 0
TIER_BOOST = {TIER_ADMIN: 3.0, TIER_MOD: 2.0}


# ───────────────────────────── чистые формулы (тестируются без БД)
def wilson_lower(pos: int, neg: int, z: float = 1.96) -> float:
    n = pos + neg
    if n == 0:
        return 0.0
    p = pos / n
    return (p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def user_rating_formula(*, questions: int, answers: int, comments: int, comments_received: int,
                        plus: int, minus: int, plus_votes: int, minus_votes: int, schemes: int,
                        question_votes: int, active_days_30: int, idle_days: float, hidden: int,
                        recent_ban: bool) -> float:
    contribution = (3 * math.log1p(questions) + 5 * math.log1p(answers)
                    + 1.5 * math.log1p(comments) + 2 * math.log1p(comments_received))
    sgn = 1 if question_votes > 0 else -1 if question_votes < 0 else 0
    quality = (8 * math.sqrt(plus) - 11 * math.sqrt(minus) + 20 * math.log1p(schemes)
               + 3 * sgn * math.sqrt(abs(question_votes)))
    core = contribution + quality * (0.5 + wilson_lower(plus_votes, minus_votes))
    activity = 1 + 0.5 * min(active_days_30, 30) / 30
    freshness = 0.3 + 0.7 * 0.5 ** (max(idle_days, 0) / 60)
    trust = 0.8 ** hidden * (0.5 if recent_ban else 1.0)
    return round(10 * max(0.0, core * activity * freshness * trust), 1)


def tier_for(role_codes: set[str]) -> int:
    return TIER_ADMIN if "admin" in role_codes else TIER_MOD if "moderator" in role_codes else TIER_USER


def question_rating(votes_score: int, answers_count: int, comments_count: int) -> float:
    return votes_score + 2 * answers_count + 0.5 * comments_count


def author_boost(tier: int, rating: float) -> float:
    return TIER_BOOST.get(tier, 0.5 * math.log10(1 + max(rating, 0) / 10))


def question_hot(rating: float, created_at: datetime, tier: int, author_rating: float) -> float:
    order = math.log10(max(abs(rating), 1))
    sign = 1 if rating > 0 else -1 if rating < 0 else 0
    age = (created_at - EPOCH).total_seconds()
    return round(sign * order + age / 45000 + author_boost(tier, author_rating), 7)


def public_rating(u: User) -> dict:
    """Для API: у админа/модера — ∞."""
    if u.rating_tier >= TIER_MOD:
        return {"rating": None, "rating_display": "∞", "rating_tier": u.rating_tier}
    return {"rating": u.rating, "rating_display": f"{u.rating:g}", "rating_tier": u.rating_tier}


# ───────────────────────────── SQL-выражения сортировки
def answer_order(best_answer_id):
    return ((Answer.id == best_answer_id).desc(), User.rating_tier.desc(),
            (Answer.score + 0.5 * Answer.comments_count + 2 * func.ln(1 + User.rating / 10)).desc(),
            Answer.id)


def comment_order():
    return (User.rating_tier.desc(), User.rating.desc(), Comment.id)


# ───────────────────────────── пересчёт
async def recompute_user(s: AsyncSession, user_id: int) -> float:
    user = await s.get(User, user_id)
    if user is None:
        return 0.0
    await s.refresh(user, ["roles"])
    user.rating_tier = tier_for({r.code for r in user.roles})
    active = ContentStatus.ACTIVE
    now = datetime.now(timezone.utc)

    async def count(model, *where):
        return await s.scalar(select(func.count()).select_from(model).where(*where)) or 0

    q_n = await count(Question, Question.author_id == user_id, Question.status == active)
    a_n = await count(Answer, Answer.author_id == user_id, Answer.status == active)
    c_n = await count(Comment, Comment.author_id == user_id, Comment.status == active)
    received = await s.scalar(
        select(func.count()).select_from(Comment).join(Answer, Answer.id == Comment.answer_id)
        .where(Answer.author_id == user_id, Answer.status == active,
               Comment.status == active, Comment.author_id != user_id)) or 0
    plus, minus, plus_n, minus_n = (await s.execute(
        select(func.coalesce(func.sum(case((Vote.value > 0, Vote.value), else_=0)), 0),
               func.coalesce(func.sum(case((Vote.value < 0, -Vote.value), else_=0)), 0),
               func.count().filter(Vote.value > 0), func.count().filter(Vote.value < 0))
        .join(Answer, Answer.id == Vote.answer_id)
        .where(Answer.author_id == user_id, Answer.status == active, Vote.counted.is_(True)))).one()
    schemes = await s.scalar(
        select(func.count()).select_from(Question).join(Answer, Answer.id == Question.best_answer_id)
        .where(Answer.author_id == user_id, Question.status == active)) or 0
    qv = await s.scalar(
        select(func.coalesce(func.sum(QuestionVote.value), 0))
        .join(Question, Question.id == QuestionVote.question_id)
        .where(Question.author_id == user_id, Question.status == active)) or 0

    moments = union_all(
        select(Question.created_at.label("t")).where(Question.author_id == user_id),
        select(Answer.created_at).where(Answer.author_id == user_id),
        select(Comment.created_at).where(Comment.author_id == user_id),
    ).subquery()
    since = now - timedelta(days=30)
    days = await s.scalar(select(func.count(func.distinct(
        cast(func.timezone("Europe/Moscow", moments.c.t), Date)))).where(moments.c.t >= since)) or 0
    last = await s.scalar(select(func.max(moments.c.t))) or user.created_at
    hidden = sum([
        await count(Question, Question.author_id == user_id, Question.status == ContentStatus.HIDDEN),
        await count(Answer, Answer.author_id == user_id, Answer.status == ContentStatus.HIDDEN),
        await count(Comment, Comment.author_id == user_id, Comment.status == ContentStatus.HIDDEN),
    ])
    recent_ban = await count(Ban, Ban.user_id == user_id, Ban.starts_at >= now - timedelta(days=90),
                             Ban.lifted_at.is_(None)) > 0  # снятый по апелляции бан не штрафует

    user.rating = user_rating_formula(
        questions=q_n, answers=a_n, comments=c_n, comments_received=received,
        plus=int(plus), minus=int(minus), plus_votes=plus_n, minus_votes=minus_n, schemes=schemes,
        question_votes=int(qv), active_days_30=days, idle_days=(now - last).total_seconds() / 86400,
        hidden=hidden, recent_ban=recent_ban)
    return user.rating


async def refresh_question(s: AsyncSession, question: Question) -> None:
    author = await s.get(User, question.author_id)
    question.rating = question_rating(question.votes_score, question.answers_count, question.comments_count)
    question.score_hot = question_hot(question.rating, question.created_at,
                                      author.rating_tier if author else 0, author.rating if author else 0)


async def recompute_all(s: AsyncSession) -> int:
    ids = (await s.scalars(select(User.id))).all()
    for uid in ids:
        await recompute_user(s, uid)
    for q in (await s.scalars(select(Question))).all():
        q.votes_score = await s.scalar(select(func.coalesce(func.sum(QuestionVote.value), 0))
                                       .where(QuestionVote.question_id == q.id)) or 0
        await refresh_question(s, q)
    return len(ids)


