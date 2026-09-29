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
        "QUOTES_REMOTE": False,
        "DATABASE_URL": database_url,
        "REDIS_CLIENT": fakeredis.FakeRedis(decode_responses=True),
        "KREMLE_AUTO_GUARD": False,
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
                    await s.flush()
                    from app.services.roles import sync_tier
                    await sync_tier(s, user["id"])
            with app.app_context():
                asyncio.run(grant())
                invalidate_perms(user["id"])
        return client, user
    return _make
