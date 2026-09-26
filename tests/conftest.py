"""Тесты гоняются на настоящем PostgreSQL 16 (pgserver) с миграциями Alembic.
Redis — fakeredis."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from itertools import count

import fakeredis
import pgserver
import pytest
from kremle_detect.integrations.flask_ext import SESSION_KEY
from sqlalchemy import select, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def database_url():
    srv = pgserver.get_server(tempfile.mkdtemp(prefix="bulboz-pg-"), cleanup_mode="delete")
    url = srv.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True,
                   env={**os.environ, "DATABASE_URL": url}, capture_output=True)
    yield url


@pytest.fixture()
def app(database_url):
    from app import create_app
    from app.db import get_engine
    from app.models import Base
    from app.seed import seed

    application = create_app({
        "TESTING": True,
        "DATABASE_URL": database_url,
        "REDIS_CLIENT": fakeredis.FakeRedis(decode_responses=True),
        "KREMLE_AUTO_GUARD": False,
        "NEW_ACCOUNT_VOTE_HOLD_HOURS": 0,
        "VOTE_CHANGE_COOLDOWN_SECONDS": 0,
        "ANTISPAM_POSTS_PER_MINUTE": 100,
    })

    async def reset():
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        async with get_engine().begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await seed()

    with application.app_context():
        asyncio.run(reset())
    yield application


def pass_captcha(client):
    with client.session_transaction() as sess:
        sess[SESSION_KEY] = True


_n = count(1)


@pytest.fixture()
def make_user(app):
    """make_user(role='user'|'moderator'|'admin') -> (client, user_json)"""
    def _make(role: str = "user", username: str | None = None):
        client = app.test_client()
        name = username or f"user{next(_n)}"
        r = client.post("/api/auth/register", json={
            "username": name, "email": f"{name}@example.com", "password": "correct-horse",
            "birth_year": 2008, "accept_terms": True,
        })
        assert r.status_code == 201, r.json
        user = r.json["user"]
        if role != "user":
            from app.auth.rbac import invalidate_perms
            from app.db import session_scope
            from app.models import Role, UserRole

            codes = {"moderator": ["moderator"], "admin": ["moderator", "admin"]}[role]

            async def grant():
                async with session_scope() as s:
                    for rid in await s.scalars(select(Role.id).where(Role.code.in_(codes))):
                        s.add(UserRole(user_id=user["id"], role_id=rid))
            with app.app_context():
                asyncio.run(grant())
                invalidate_perms(user["id"])
        return client, user
    return _make


@pytest.fixture()
def qa(make_user):
    """Автор вопроса, отвечающий, сторонний зритель + вопрос и ответ."""
    author_c, author = make_user()
    answerer_c, answerer = make_user()
    other_c, other = make_user()
    q = author_c.post("/api/questions", json={"kind": "knowledge",
                                              "title": "Почему шарик падает с ускорением?"}).json["question"]
    a = answerer_c.post(f"/api/questions/{q['id']}/answers",
                        json={"body": "Потому что на него действует сила тяжести, F = ma."}).json["answer"]
    return dict(author_c=author_c, author=author, answerer_c=answerer_c, answerer=answerer,
                other_c=other_c, other=other, q=q, a=a)
