"""Alembic env в асинхронном режиме (SQLAlchemy AsyncEngine + asyncpg)."""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Config
from app.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
URL = os.environ.get("DATABASE_URL", Config.DATABASE_URL)

# Индексы по выражениям Alembic сравнивать не умеет — даёт ложный diff.
EXPRESSION_INDEXES = {"ix_questions_fts"}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "index" and name in EXPRESSION_INDEXES)


def run_migrations_offline() -> None:
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True,
                      compare_type=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
