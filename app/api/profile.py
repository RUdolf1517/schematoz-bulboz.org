from __future__ import annotations

from sqlalchemy import case, func, select

from ..db import session_scope
from ..errors import ApiError
from ..auth.sessions import current_user_id
from ..models import (
    Answer, ContentStatus, Follow, Question, RepReason, ReputationEvent, Room, User,
)
from flask import g

from ..auth.rbac import login_required
from ..services.gamification import user_badges
from ..services.markdown import render as render_md
from ..services.profile_custom import apply_update, options, public_custom
from . import bp
from .utils import json_body, user_public

EXPERT_MIN_BEST = 15
CONNOISSEUR_MIN_BEST = 5


def topic_status(schemes: int, plus: int, minus: int) -> str:
    votes = plus + minus
    minus_share = minus / votes if votes else 0
    if schemes >= EXPERT_MIN_BEST and minus_share < 0.15:
        return "expert"
    if schemes >= CONNOISSEUR_MIN_BEST:
        return "connoisseur"
    return "newbie"


@bp.get("/users/<username>")
async def profile(username: str):
    """Прозрачная репутация: разбивка по темам + бейджи + последние «Схемы»."""
    async with session_scope() as s:
        user = await s.scalar(select(User).where(User.username == username.lower()))
        if user is None:
            raise ApiError("Пользователь не найден", 404, "not_found")
        # схемы считаем по уникальным ответам (автор мог менять голос туда-обратно)
        scheme_answers = (select(ReputationEvent.answer_id).where(
            ReputationEvent.user_id == user.id, ReputationEvent.reason == RepReason.AUTHOR_VOTE,
            ReputationEvent.delta == 5))
        rows = (await s.execute(
            select(
                ReputationEvent.room_id, Room.title, Room.slug,
                func.count(func.distinct(case(
                    ((ReputationEvent.reason == RepReason.AUTHOR_VOTE) & (ReputationEvent.delta == 5),
                     ReputationEvent.answer_id)))).label("schemes"),
                func.sum(case((ReputationEvent.delta > 0, 1), else_=0)).label("plus"),
                func.sum(case((ReputationEvent.delta < 0, 1), else_=0)).label("minus"),
                func.sum(ReputationEvent.delta).label("total"),
            )
            .outerjoin(Room, Room.id == ReputationEvent.room_id)
            .where(ReputationEvent.user_id == user.id,
                   ReputationEvent.reason != RepReason.VOTE_REVOKED)
            .group_by(ReputationEvent.room_id, Room.title, Room.slug)
            .order_by(func.sum(ReputationEvent.delta).desc())
        )).all()
        best = (await s.execute(
            select(Answer, Question).join(Question, Question.id == Answer.question_id)
            .where(Answer.id.in_(scheme_answers), Question.best_answer_id == Answer.id,
                   Answer.status == ContentStatus.ACTIVE, Question.status == ContentStatus.ACTIVE)
            .order_by(Answer.id.desc()).limit(10)
        )).all()
        stats = (await s.execute(select(
            select(func.count(Question.id)).where(Question.author_id == user.id,
                                                  Question.status == ContentStatus.ACTIVE).scalar_subquery(),
            select(func.count(Answer.id)).where(Answer.author_id == user.id,
                                                Answer.status == ContentStatus.ACTIVE).scalar_subquery(),
        ))).one()
        badges = await user_badges(s, user.id)
        from .social import follow_counts
        counts = await follow_counts(s, user.id)
        viewer = current_user_id()
        pinned = None
        pid = (user.profile or {}).get("pinned_answer_id")
        if pid:
            row = (await s.execute(select(Answer, Question).join(Question, Question.id == Answer.question_id)
                                   .where(Answer.id == pid, Answer.author_id == user.id,
                                          Answer.status == ContentStatus.ACTIVE,
                                          Question.status == ContentStatus.ACTIVE))).first()
            if row:
                pinned = {"answer_id": row[0].id, "question_id": row[1].id, "question_title": row[1].title,
                          "body_html": render_md(row[0].body), "score": row[0].score,
                          "is_best": row[1].best_answer_id == row[0].id}
        i_follow = None
        if viewer and viewer != user.id:
            i_follow = await s.get(Follow, (viewer, user.id)) is not None

    topics = [{
        "room_id": room_id, "room_slug": slug, "title": title or "Общая лента",
        "schemes": schemes, "plus": plus or 0, "minus": minus or 0, "points": total or 0,
        "status": topic_status(schemes, plus or 0, minus or 0),
    } for room_id, title, slug, schemes, plus, minus, total in rows]
    custom = public_custom(user)
    is_owner = viewer == user.id
    hidden = set(custom["hidden_sections"]) if not is_owner else set()
    # витрина: выбранные бейджи первыми
    order = {c: i for i, c in enumerate(custom["showcase_badges"])}
    badges = sorted(badges, key=lambda b: (order.get(b["code"], 99),))
    for b in badges:
        b["showcase"] = b["code"] in order
    out = {
        "user": {**user_public(user), "bio": user.bio, "created_at": user.created_at.isoformat()},
        "custom": custom,
        "about_html": render_md(custom["about"]),
        "pinned_answer": pinned,
        "is_owner": is_owner,
        "stats": {"questions": stats[0], "answers": stats[1],
                  "schemes": sum(t["schemes"] for t in topics), **counts},
        "i_follow": i_follow,
        "topics": topics,
        "badges": badges,
        "best_answers": [{"answer_id": a.id, "question_id": q.id, "question_title": q.title,
                          "body": (a.body or "")[:280]} for a, q in best],
    }
    # скрытые разделы чужим не отдаём вообще (а не просто прячем на фронте)
    if "topics" in hidden:
        out["topics"] = []
    if "badges" in hidden:
        out["badges"] = []
    if "best_answers" in hidden:
        out["best_answers"] = []
    if "follows" in hidden:
        out["stats"].pop("followers", None)
        out["stats"].pop("following", None)
    if "stats" in hidden:
        for k in ("questions", "answers", "schemes"):
            out["stats"].pop(k, None)
    if "streak" in hidden:
        out["user"]["streak_days"] = None
        out["user"]["streak_freeze_available"] = None
    return out


@bp.get("/me/profile")
@login_required
async def my_profile_settings():
    """Текущие настройки + варианты (темы, шрифты, рамки…) + что доступно юзеру."""
    async with session_scope() as s:
        user = await s.get(User, g.user.id)
        badges = await user_badges(s, user.id)
        answers = (await s.execute(
            select(Answer.id, Question.title).join(Question, Question.id == Answer.question_id)
            .where(Answer.author_id == user.id, Answer.status == ContentStatus.ACTIVE,
                   Question.status == ContentStatus.ACTIVE)
            .order_by(Answer.score.desc(), Answer.id.desc()).limit(50))).all()
    return {"user": {**user_public(user), "bio": user.bio}, "settings": public_custom(user),
            "options": options(), "badges": badges,
            "answers": [{"id": aid, "question_title": t} for aid, t in answers]}


@bp.patch("/me/profile")
@login_required
async def update_profile_settings():
    data = json_body()
    async with session_scope() as s:
        user = await s.get(User, g.user.id, with_for_update=True)
        await apply_update(s, user, data)
        await s.flush()
        out = {"user": {**user_public(user), "bio": user.bio}, "settings": public_custom(user)}
    return out
