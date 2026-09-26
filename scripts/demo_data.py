"""Демо-контент для локального превью. Запуск: python scripts/demo_data.py (после flask seed)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app import create_app  # noqa: E402
from app.auth.passwords import hash_password  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Answer, DebateSide, Question, QuestionKind, Role, Room, User, UserRole, Vote,
)


async def demo():
    async with session_scope() as s:
        if await s.scalar(select(User.id).where(User.username == "dasha")):
            print("demo data already present")
            return
        role_id = await s.scalar(select(Role.id).where(Role.code == "user"))
        u = {}
        for name in ["dasha", "kotik_na_fizmate", "artem"]:
            u[name] = User(username=name, email=f"{name}@example.com", display_name=name,
                           password_hash=hash_password("demo-password"), birth_year=2008)
            s.add(u[name])
            await s.flush()
            s.add(UserRole(user_id=u[name].id, role_id=role_id))
        room = await s.scalar(select(Room).where(Room.slug == "ege-physics"))
        q1 = Question(author_id=u["dasha"].id, kind=QuestionKind.KNOWLEDGE, room_id=room.id,
                      category_id=room.category_id,
                      title="Почему шарик падает с ускорением, а не с постоянной скоростью?")
        q2 = Question(author_id=u["artem"].id, kind=QuestionKind.DEBATE, title="Шаверма или шаурма?",
                      debate_side_a="Шаверма", debate_side_b="Шаурма")
        q3 = Question(author_id=u["artem"].id, kind=QuestionKind.OPINION,
                      title="Можно ли пожарить воду, если очень хочется?")
        s.add_all([q1, q2, q3])
        await s.flush()
        a1 = Answer(question_id=q1.id, author_id=u["kotik_na_fizmate"].id, score=5,
                    body="На шарик всё время действует сила тяжести. По второму закону Ньютона "
                         "F = ma, значит есть ускорение g ≈ 9,8 м/с² — скорость растёт каждую секунду.")
        a2 = Answer(question_id=q2.id, author_id=u["dasha"].id, debate_side=DebateSide.A,
                    body="Шаверма. Питер не обсуждается.")
        s.add_all([a1, a2])
        await s.flush()
        s.add(Vote(answer_id=a1.id, voter_id=u["dasha"].id, value=5, is_author_vote=True))
        u["kotik_na_fizmate"].reputation = 5
        q1.best_answer_id, q1.answers_count, q1.score_hot = a1.id, 1, 10
        q2.answers_count, q2.score_hot = 1, 5
    print("demo data created")


if __name__ == "__main__":
    with create_app().app_context():
        asyncio.run(demo())
