"""Redis. Синхронный клиент redis-py: он потокобезопасен и не привязан к event loop,
в отличие от redis.asyncio (см. комментарий в app/db.py). Вызовы Redis — микросекунды."""
from __future__ import annotations

import redis
from flask import current_app


def init_redis(app) -> None:
    client = app.config.get("REDIS_CLIENT")
    if client is None:
        url = app.config["REDIS_URL"]
        if url.startswith("memory://"):  # только для локальной разработки без Redis
            import fakeredis
            client = fakeredis.FakeRedis(decode_responses=True)
        else:
            client = redis.Redis.from_url(url, decode_responses=True)
    app.extensions["redis"] = client


def get_redis() -> redis.Redis:
    return current_app.extensions["redis"]


def redis_pop(r, key: str):
    """Атомарно прочитать и удалить ключ. GETDEL есть только с Redis 6.2 (в Ubuntu 22.04 — 6.0),
    поэтому GET+DEL в транзакции MULTI/EXEC — работает на любом Redis."""
    pipe = r.pipeline(transaction=True)
    pipe.get(key)
    pipe.delete(key)
    return pipe.execute()[0]
