from __future__ import annotations

import asyncio
from datetime import date

import click
from flask import Flask
from sqlalchemy import select

from .auth.passwords import hash_password
from .db import get_engine, session_scope
from .models import Base, Role, User, UserRole
from .seed import seed


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed_cmd():
        """Роли, права, юр. страницы, стартовые комнаты."""
        asyncio.run(seed())
        click.echo("seeded")

    @app.cli.command("create-db-dev")
    def create_db_dev():
        """ТОЛЬКО для локальной разработки: create_all без Alembic."""
        async def _run():
            async with get_engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        asyncio.run(_run())
        click.echo("tables created")

    @app.cli.command("create-admin")
    @click.argument("username")
    @click.argument("email")
    @click.password_option()
    def create_admin(username, email, password):
        async def _run():
            async with session_scope() as s:
                u = User(username=username.lower(), email=email.lower(),
                         password_hash=hash_password(password), display_name=username,
                         birth_year=date.today().year - 18)
                s.add(u)
                await s.flush()
                for r in (await s.scalars(select(Role).where(Role.code.in_(["user", "moderator", "admin"])))):
                    s.add(UserRole(user_id=u.id, role_id=r.id))
        asyncio.run(_run())
        click.echo(f"admin @{username} created")
