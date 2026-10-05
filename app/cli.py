from __future__ import annotations

import asyncio
import base64
import json
from datetime import date

import click
from flask import Flask
from sqlalchemy import select

from .auth.passwords import hash_password
from .db import get_engine, session_scope
from .models import Base, Role, User, UserRole
from .seed import seed


def _run_db(app: Flask, coro):
    """asyncio.run с человеческой ошибкой вместо traceback, если БД недоступна."""
    from .dbcheck import db_problem
    try:
        return asyncio.run(coro)
    except Exception as e:  # noqa: BLE001
        hint = db_problem(e, app.config.get("DATABASE_URL", ""))
        if hint is None:
            raise
        raise click.ClickException("Не удалось подключиться к базе данных.\n   " + hint) from None


def register_cli(app: Flask) -> None:
    @app.cli.command("doctor")
    def doctor():
        """Проверить окружение: .env, PostgreSQL, миграции, роли, Redis."""
        import os

        from sqlalchemy import text

        from .dbcheck import db_problem, mask_url, redis_problem
        ok = True
        click.echo(f".env: {'найден' if os.path.exists('.env') else 'нет (используются переменные окружения и значения по умолчанию)'}")
        url = app.config["DATABASE_URL"]
        click.echo(f"DATABASE_URL: {mask_url(url)}")

        async def check_db():
            async with get_engine().connect() as conn:
                ver = await conn.scalar(text("SHOW server_version"))
                rev = await conn.scalar(text(
                    "SELECT version_num FROM alembic_version LIMIT 1")) if await conn.scalar(text(
                    "SELECT to_regclass('alembic_version') IS NOT NULL")) else None
                roles = await conn.scalar(text("SELECT count(*) FROM roles")) if rev else 0
                return ver, rev, roles
        try:
            ver, rev, roles = asyncio.run(check_db())
            click.echo(f"  ✅ PostgreSQL {ver}")
            if not rev:
                ok = False
                click.echo("  ❌ миграции не применены → alembic upgrade head")
            else:
                click.echo(f"  ✅ миграции: {rev}")
                if not roles:
                    ok = False
                    click.echo("  ❌ роли не созданы → flask --app app seed")
                else:
                    click.echo("  ✅ роли и права на месте")
        except Exception as e:  # noqa: BLE001
            ok = False
            click.echo("  ❌ " + (db_problem(e, url) or f"{type(e).__name__}: {e}"))
        rurl = app.config["REDIS_URL"]
        click.echo(f"REDIS_URL: {mask_url(rurl)}")
        try:
            from .extensions import get_redis
            get_redis().ping()
            click.echo("  ✅ Redis отвечает")
        except Exception as e:  # noqa: BLE001
            ok = False
            click.echo("  ❌ " + (redis_problem(e, rurl) or f"{type(e).__name__}: {e}"))
        from .services.push import vapid_status
        push_ok, push_reason = vapid_status(app.config)
        if push_ok:
            click.echo("  ✅ Web Push: VAPID-ключи и контакт владельца на месте")
        else:
            click.echo(f"  ⚪ Web Push выключен ({push_reason}); сайт и внутренние уведомления работают")
            click.echo("     включить: flask --app app generate-vapid → VAPID_* в .env → systemctl restart bulboz")
        if not ok:
            raise SystemExit(1)
        click.echo("Всё готово: hypercorn \"app.asgi:asgi_app\" --bind 0.0.0.0:8000")

    @app.cli.command("seed")
    def seed_cmd():
        """Роли, права, юр. страницы."""
        _run_db(app, seed())
        click.echo("seeded")

    @app.cli.command("run-notification-jobs")
    @click.option("--limit", default=200, show_default=True, type=click.IntRange(1, 5000))
    def run_notification_jobs(limit: int):
        """Сканировать игровые напоминания и отправлять очередь Web Push (запускать раз в 5 минут)."""
        from .services.notification_jobs import scan_notifications
        from .services.push import dispatch_pushes

        async def _run():
            scanned = await scan_notifications()
            delivered = await dispatch_pushes(limit=limit)
            return {"notifications": scanned, "push": delivered}
        click.echo(json.dumps(_run_db(app, _run()), ensure_ascii=False))

    @app.cli.command("generate-vapid")
    @click.option("--subject", default="", help="Контакт владельца домена для push-сервисов: mailto: с реальным адресом (RFC 8292).")
    def generate_vapid(subject: str):
        """Сгенерировать P-256 VAPID-пару: приватный ключ одной строкой base64 — удобно для .env."""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:
            raise click.ClickException("Для генерации установи зависимости проекта: pip install -e .") from None
        from .services.push import vapid_subject_ok
        if subject and not vapid_subject_ok(subject):
            raise click.ClickException(
                "VAPID_SUBJECT должен быть реальным контактом владельца: mailto: с адресом владельца домена (RFC 8292)."
            )
        private = ec.generate_private_key(ec.SECP256R1())
        private_pem = private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii").strip()
        public = private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        public_b64 = base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")
        private_b64 = base64.urlsafe_b64encode(private_pem.encode("ascii")).rstrip(b"=").decode("ascii")
        click.echo("Добавь эти строки в .env (VAPID_PRIVATE_KEY — одной строкой, безопасно для systemd).")
        click.echo("Ключи генерируются один раз: не пересоздавай их на каждом деплое и не коммить в git.")
        click.echo(f"VAPID_PUBLIC_KEY={public_b64}")
        click.echo(f"VAPID_PRIVATE_KEY=base64:{private_b64}")
        if subject:
            click.echo(f"VAPID_SUBJECT={subject}")
        else:
            click.echo("VAPID_SUBJECT=mailto:CHANGE-ME@example.com   ← замени на реальный адрес владельца домена")
        click.echo("Затем: sudo systemctl restart bulboz")
        click.echo("Планировщик отправки (каждые 5 минут): flask --app app run-notification-jobs "
                   "(deploy.sh ставит таймер bulboz-notifications.timer)")

    @app.cli.command("create-db-dev")
    def create_db_dev():
        """ТОЛЬКО для локальной разработки: create_all без Alembic."""
        async def _run():
            async with get_engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        _run_db(app, _run())
        click.echo("tables created")

    @app.cli.command("create-admin")
    @click.argument("username")
    @click.argument("email")
    @click.password_option()
    def create_admin(username, email, password):
        from sqlalchemy import func, or_

        from .services.roles import sync_tier

        async def _run():
            async with session_scope() as s:
                roles = (await s.scalars(select(Role).where(Role.code.in_(["user", "admin"])))).all()
                if len(roles) < 2:
                    raise click.ClickException("Роли ещё не созданы. Сначала: alembic upgrade head && flask --app app seed")
                taken = await s.scalar(select(User.id).where(or_(
                    User.username == username.lower(), func.lower(User.email) == email.lower())))
                if taken:
                    raise click.ClickException(f"Ник «{username}» или email «{email}» уже заняты")
                u = User(username=username.lower(), email=email.lower(),
                         password_hash=hash_password(password), display_name=username,
                         birth_year=date.today().year - 18)
                s.add(u)
                await s.flush()
                for r in roles:
                    s.add(UserRole(user_id=u.id, role_id=r.id))
                await s.flush()
                await sync_tier(s, u.id)
        _run_db(app, _run())
        click.echo(f"Админ @{username.lower()} создан. Вход: /login")
