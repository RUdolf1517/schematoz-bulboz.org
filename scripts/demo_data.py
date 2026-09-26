"""Демо-контент и ТЕСТОВЫЕ аккаунты для локального превью.

    python scripts/demo_data.py          # после `alembic upgrade head` и `flask seed`

Аккаунты (пароли только для разработки — в проде не запускать!):
    admin / admin-demo-2026     — администратор (+ модератор)
    moder / moder-demo-2026     — модератор
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
from app.models import (  # noqa: E402
    AppealStatus, Answer, Ban, DebateSide, DebateVote, Question, QuestionKind, RepReason,
    Report, ReportReason, ReportTarget, ReputationEvent, Role, Room, User, UserBadge, UserRole,
    Vote,
)
from app.services.ranking import hot_score  # noqa: E402

ACCOUNTS = [
    # username, password, roles, birth_year
    ("admin", "admin-demo-2026", ["user", "moderator", "admin"], 1998),
    ("moder", "moder-demo-2026", ["user", "moderator"], 2002),
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


def rep(s, user, delta, reason, actor, answer, q):
    s.add(ReputationEvent(user_id=user.id, delta=delta, reason=reason, actor_id=actor.id,
                          answer_id=answer.id, question_id=q.id, room_id=q.room_id,
                          category_id=q.category_id))
    user.reputation += delta


async def demo():
    async with session_scope() as s:
        u = await ensure_accounts(s)
        if await s.scalar(select(Question.id).limit(1)):
            print("demo content already present")
            return
        rooms = {r.slug: r for r in (await s.scalars(select(Room))).all()}
        now = datetime.now(timezone.utc)

        def q(author, kind, title, room=None, body=None, a=None, b=None, ago_h=1):
            obj = Question(author_id=u[author].id, kind=kind, title=title, body=body,
                           room_id=rooms[room].id if room else None,
                           category_id=rooms[room].category_id if room else None,
                           debate_side_a=a, debate_side_b=b, created_at=now - timedelta(hours=ago_h))
            s.add(obj)
            return obj

        q1 = q("dasha", QuestionKind.KNOWLEDGE, "Почему шарик падает с ускорением, а не с постоянной скоростью?",
               "ege-physics", "Завтра контрольная, а я вообще не вдупляю 😭", ago_h=3)
        q2 = q("artem", QuestionKind.DEBATE, "Шаверма или шаурма?", a="Шаверма", b="Шаурма", ago_h=5)
        q3 = q("artem", QuestionKind.OPINION, "Можно ли пожарить воду, если очень хочется?", "golden-fund", ago_h=8)
        q4 = q("lena_2007", QuestionKind.KNOWLEDGE, "Как быстро выучить все даты по истории к ЕГЭ?", ago_h=2)
        q5 = q("kotik_na_fizmate", QuestionKind.STORY, "Расскажите, как вы пережили первую сессию",
               "first-year", ago_h=20)
        q6 = q("dasha", QuestionKind.OPINION, "Какого персонажа взять в пати новичку в Genshin?", "genshin", ago_h=1)
        q7 = q("lena_2007", QuestionKind.KNOWLEDGE, "Где ставить запятую в «однако»?", "ege-russian", ago_h=0.5)
        await s.flush()

        def ans(qq, author, body, side=None, ago_h=0.5):
            obj = Answer(question_id=qq.id, author_id=u[author].id, body=body, debate_side=side,
                         created_at=qq.created_at + timedelta(hours=ago_h))
            s.add(obj)
            qq.answers_count += 1
            return obj

        a1 = ans(q1, "kotik_na_fizmate", "На шарик всё время действует сила тяжести. По второму закону Ньютона "
                 "F = ma, значит есть ускорение g ≈ 9,8 м/с² — скорость растёт каждую секунду. "
                 "Постоянная скорость была бы, если бы силы уравновешивались (например, парашют).")
        a1b = ans(q1, "artem", "ну это гравитация лол", ago_h=0.2)
        a2 = ans(q2, "dasha", "Шаверма. Питер не обсуждается.", DebateSide.A)
        a2b = ans(q2, "lena_2007", "Шаурма — так говорит вся остальная страна 🤷‍♀️", DebateSide.B)
        a3 = ans(q3, "kotik_na_fizmate", "Технически — нет: вода закипит при 100 °C и испарится. "
                 "Но если очень хочется, можно пожарить лёд. Недолго.")
        a4 = ans(q4, "kotik_na_fizmate", "Делай ленту времени на стене и повторяй по 15 минут каждый день. "
                 "Интервальные повторения (Anki) реально работают.")
        a5 = ans(q5, "lena_2007", "Спала по 4 часа, жила на энергетиках, сдала всё. Не повторяйте 🙃")
        a_spam = ans(q6, "spamer777", "Бесплатные крутки тут >>> free-genshin-gems точка ру")
        await s.flush()

        # голоса и репутация
        s.add(Vote(answer_id=a1.id, voter_id=u["dasha"].id, value=5, is_author_vote=True))
        rep(s, u["kotik_na_fizmate"], 5, RepReason.AUTHOR_VOTE, u["dasha"], a1, q1)
        s.add(Vote(answer_id=a1.id, voter_id=u["lena_2007"].id, value=1, is_author_vote=False))
        rep(s, u["kotik_na_fizmate"], 1, RepReason.UPVOTE, u["lena_2007"], a1, q1)
        a1.score = 6
        q1.best_answer_id = a1.id
        s.add(Vote(answer_id=a1b.id, voter_id=u["dasha"].id, value=-1, is_author_vote=True))
        rep(s, u["artem"], -1, RepReason.AUTHOR_VOTE, u["dasha"], a1b, q1)
        a1b.score = -1
        s.add(Vote(answer_id=a3.id, voter_id=u["artem"].id, value=5, is_author_vote=True))
        rep(s, u["kotik_na_fizmate"], 5, RepReason.AUTHOR_VOTE, u["artem"], a3, q3)
        a3.score = 5
        q3.best_answer_id = a3.id
        s.add(Vote(answer_id=a2.id, voter_id=u["kotik_na_fizmate"].id, value=1, is_author_vote=False))
        rep(s, u["dasha"], 1, RepReason.UPVOTE, u["kotik_na_fizmate"], a2, q2)
        a2.score = 1
        for voter, side in [("dasha", DebateSide.A), ("kotik_na_fizmate", DebateSide.A),
                            ("lena_2007", DebateSide.B), ("moder", DebateSide.A)]:
            s.add(DebateVote(question_id=q2.id, user_id=u[voter].id, side=side))

        for qq, scores in [(q1, [6, -1]), (q2, [1, 0]), (q3, [5]), (q4, [0]), (q5, [0]), (q6, [0]), (q7, [])]:
            qq.score_hot = hot_score(sum(scores), len(scores), qq.created_at)

        # бейджи и стрики
        today = datetime.now(timezone.utc).date()
        u["kotik_na_fizmate"].streak_days, u["kotik_na_fizmate"].streak_last_date = 12, today
        u["dasha"].streak_days, u["dasha"].streak_last_date = 3, today
        for name, codes in {"kotik_na_fizmate": ["first_answer", "first_scheme", "streak_7", "night_watch", "first_question"],
                            "dasha": ["first_question", "first_answer", "debater"],
                            "lena_2007": ["first_question", "first_answer", "debater"]}.items():
            for c in codes:
                s.add(UserBadge(user_id=u[name].id, code=c))

        # жалобы — чтобы очередь модерации была не пустой
        s.add(Report(reporter_id=u["dasha"].id, target_type=ReportTarget.ANSWER, target_id=a_spam.id,
                     reason=ReportReason.SPAM, comment="Реклама левого сайта"))
        s.add(Report(reporter_id=u["lena_2007"].id, target_type=ReportTarget.ANSWER, target_id=a_spam.id,
                     reason=ReportReason.SPAM))
        s.add(Report(reporter_id=u["artem"].id, target_type=ReportTarget.ANSWER, target_id=a2b.id,
                     reason=ReportReason.BULLYING, comment="Она не права!!!"))
        # бан с апелляцией (выдал admin → разбирать может moder)
        s.add(Ban(user_id=u["spamer777"].id, issued_by=u["admin"].id, reason="Спам ссылками (п. 2 Правил)",
                  ends_at=now + timedelta(days=7), appeal_status=AppealStatus.PENDING,
                  appeal_text="Я больше не буду, это был не я, это брат с моего аккаунта", appeal_created_at=now))
    print("demo content created")


if __name__ == "__main__":
    with create_app().app_context():
        asyncio.run(demo())
