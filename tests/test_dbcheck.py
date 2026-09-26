"""Понятные подсказки при проблемах с БД вместо traceback."""
import asyncpg
from sqlalchemy.exc import DBAPIError

from app.dbcheck import db_problem, mask_url


def _wrap(orig):
    return DBAPIError("SELECT 1", {}, orig)


def test_role_missing_hint():
    e = _wrap(asyncpg.exceptions.InvalidAuthorizationSpecificationError('role "bulboz" does not exist'))
    hint = db_problem(e, "postgresql+asyncpg://bulboz:secret@localhost:5432/bulboz")
    assert "нет пользователя (роли) «bulboz»" in hint and "createuser -P bulboz" in hint
    assert "secret" not in hint and "bulboz:***@" in hint


def test_other_hints():
    assert "brew services start" in db_problem(ConnectionRefusedError(61, "Connect call failed"))
    assert "createdb bulboz" in db_problem(_wrap(Exception('database "bulboz" does not exist')))
    assert "alembic upgrade head" in db_problem(_wrap(Exception('relation "users" does not exist')))
    assert db_problem(ValueError("что-то другое")) is None
    assert mask_url("postgresql://u:p@h/db") == "postgresql://u:***@h/db"


def test_api_returns_503_when_db_down(database_url):
    from app import create_app
    bad = database_url.replace("postgresql+asyncpg://", "postgresql+asyncpg://nobody_here:x@", 1) \
        if "@" not in database_url.split("//", 1)[1].split("/", 1)[0] else \
        "postgresql+asyncpg://nobody_here:x@" + database_url.split("@", 1)[1]
    import fakeredis
    app = create_app({"TESTING": True, "DATABASE_URL": bad,
                      "REDIS_CLIENT": fakeredis.FakeRedis(decode_responses=True)})
    r = app.test_client().get("/api/feed")
    assert r.status_code == 503 and r.json["error"] == "db_unavailable"
